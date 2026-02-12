# ROS2 Node Manager — Спецификация проекта

## 1. Обзор

**Цель:** Веб-интерфейс для мониторинга и управления ROS2 нодами, работающими в Docker-контейнере (локально или на удалённом сервере).

**Принципы:**
- Простота реализации и понимания
- Без парсинга launch-файлов — всё через `ros2` CLI
- Минимум зависимостей

---

## 2. Архитектура

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                              LOCAL MACHINE                                   │
│                                                                             │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │                         Browser (React)                              │   │
│  │  ┌──────────────┐  ┌──────────────┐  ┌────────────────────────────┐ │   │
│  │  │ Server       │  │  Node Tree   │  │      Log Panel             │ │   │
│  │  │ Selector     │  │  (namespace) │  │  [realtime WebSocket]      │ │   │
│  │  │ [combobox]   │  │              │  │                            │ │   │
│  │  └──────────────┘  └──────────────┘  └────────────────────────────┘ │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│              │                                                              │
│              │ HTTP/WebSocket (:8080)                                       │
│              ▼                                                              │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │                    Python Server (FastAPI)                           │   │
│  │                    Запускается ВНЕ Docker                            │   │
│  │  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐ │   │
│  │  │ Connection  │  │ Node        │  │ Log         │  │ State       │ │   │
│  │  │ Manager     │  │ Service     │  │ Collector   │  │ Persister   │ │   │
│  │  │ (SSH/local) │  │             │  │ (/rosout)   │  │ (JSON file) │ │   │
│  │  └──────┬──────┘  └─────────────┘  └─────────────┘  └─────────────┘ │   │
│  │         │                                                            │   │
│  │         │ Выполняет команды внутри Docker                            │   │
│  └─────────┼────────────────────────────────────────────────────────────┘   │
│            │                                                                │
│            ▼                                                                │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │                         Docker Container                             │   │
│  │                                                                      │   │
│  │   ros2 node list    ros2 param dump    ros2 lifecycle set           │   │
│  │   ros2 node info    /rosout topic      kill <pid>                   │   │
│  │                                                                      │   │
│  │   ┌──────────────────────────────────────────────────────────────┐  │   │
│  │   │                     ROS2 Nodes                                │  │   │
│  │   │  /sensing/radar/front/...   /planning/...   /control/...     │  │   │
│  │   └──────────────────────────────────────────────────────────────┘  │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────────────┘

                              ИЛИ (удалённый сервер)

┌─────────────────────────────────────────────────────────────────────────────┐
│                              LOCAL MACHINE                                   │
│  ┌─────────────┐      ┌─────────────────────────────────────────────────┐   │
│  │  Browser    │◄────►│  Python Server (FastAPI)                        │   │
│  └─────────────┘      │                                                 │   │
│                       │  SSH Connection ──────────────────────────────┐ │   │
│                       └─────────────────────────────────────────────┐ │ │   │
└─────────────────────────────────────────────────────────────────────┼─┼─────┘
                                                                      │ │
                                          SSH (encrypted)             │ │
                                                                      ▼ │
                       ┌──────────────────────────────────────────────────┐
                       │              REMOTE SERVER                        │
                       │  ┌────────────────────────────────────────────┐  │
                       │  │              Docker Container               │  │
                       │  │  ros2 node list / ros2 param dump / ...    │  │
                       │  │  ROS2 Nodes                                 │  │
                       │  └────────────────────────────────────────────┘  │
                       └──────────────────────────────────────────────────┘
```

---

## 3. Способы подключения к Docker

### 3.1 Локальный Docker

```python
import subprocess

def exec_in_docker(container: str, cmd: str) -> str:
    """Выполнить команду внутри локального Docker контейнера"""
    result = subprocess.run(
        ["docker", "exec", container, "bash", "-c", f"source /opt/ros/humble/setup.bash && {cmd}"],
        capture_output=True, text=True
    )
    return result.stdout
```

### 3.2 Удалённый сервер через SSH

```python
import asyncssh

async def exec_remote_docker(ssh_conn, container: str, cmd: str) -> str:
    """Выполнить команду в Docker на удалённом сервере"""
    full_cmd = f"docker exec {container} bash -c 'source /opt/ros/humble/setup.bash && {cmd}'"
    result = await ssh_conn.run(full_cmd)
    return result.stdout
```

### 3.3 Конфигурация серверов

```yaml
# config/servers.yaml
servers:
  - id: local
    name: "Local Docker"
    type: local
    container: ros2_container
    
  - id: tram-dev
    name: "Tram Development Server"
    type: ssh
    host: 192.168.1.100
    port: 22
    user: autopilot
    ssh_key: ~/.ssh/tram_key      # или password в отдельном файле
    container: autoware_container
    
  - id: tram-test
    name: "Tram Test Server"
    type: ssh
    host: 10.0.0.50
    port: 22
    user: autopilot
    container: autoware_container
```

---

## 4. Хранение состояния (State Persistence)

### 4.1 Структура файла состояния

```json
// data/node_state.json
{
  "last_updated": "2026-01-19T15:30:00Z",
  "server_id": "tram-dev",
  "nodes": {
    "/sensing/radar/front/pe_ars408_node": {
      "first_seen": "2026-01-15T10:00:00Z",
      "last_seen": "2026-01-19T15:30:00Z",
      "type": "lifecycle",           // "lifecycle" | "regular" | "unknown"
      "status": "active",            // "active" | "inactive"
      "lifecycle_state": "active",   // только для type="lifecycle"
      "parameters": {
        "frame_id": "radar_front",
        "interface": "can0",
        "timeout_sec": 0.01
      },
      "subscribers": ["/input/frame"],
      "publishers": ["/output/objects", "/output/scan"]
    },
    "/sensing/lidar/top/velodyne_driver": {
      "first_seen": "2026-01-15T10:00:00Z",
      "last_seen": "2026-01-19T15:25:00Z",
      "type": "regular",
      "status": "inactive",          // не видим в ros2 node list
      "parameters": { ... }
    },
    "/planning/new_node": {
      "first_seen": "2026-01-19T15:30:00Z",
      "last_seen": "2026-01-19T15:30:00Z",
      "type": "unknown",             // ещё не проверяли тип
      "status": "active",
      "parameters": {}
    }
  }
}
```

### 4.2 Типы нод

| type | Описание | Как определяем |
|------|----------|----------------|
| `unknown` | Тип ещё не определён | Начальное значение при первом обнаружении |
| `lifecycle` | Lifecycle нода | Есть сервис `/{node}/get_state` |
| `regular` | Обычная нода | Нет сервиса `/{node}/get_state` |

```python
async def determine_node_type(node_name: str) -> str:
    """Определить тип ноды. Вызывается асинхронно после добавления в список."""
    result = await exec_cmd(f"ros2 service list | grep '{node_name}/get_state'")
    if result.strip():
        return "lifecycle"
    return "regular"
```

**Логика обновления типа:**
1. Новая нода появляется → `type = "unknown"`
2. В фоне запускаем проверку `determine_node_type()`
3. Получили результат → обновляем `type` в JSON и в UI
```

### 4.3 Логика обновления

```
При загрузке страницы:
1. Загрузить node_state.json → показать дерево (серым — inactive)
2. Выполнить `ros2 node list` → обновить статусы (active/inactive)
3. Для новых нод:
   a) Добавить с type="unknown", status="active"
   b) Запустить фоновую проверку типа (lifecycle/regular)
   c) Запустить `ros2 param dump` для получения параметров
4. Для исчезнувших нод → status="inactive" (не удалять!)
5. Сохранить обновлённый node_state.json

Периодическое обновление (каждые 5 сек):
1. `ros2 node list` → обновить статусы
2. Для нод с type="unknown" → повторить проверку типа
```

---

## 5. Определение типа ноды и управление

### 5.1 Определение типа (уже описано в 4.2)

При первом обнаружении ноды — `type = "unknown"`. Затем асинхронно проверяем наличие lifecycle сервисов.

### 5.2 Управление нодами

| type | Действие "Выключить" | Действие "Включить" (будущее) |
|----------|---------------------|-------------------------------|
| `lifecycle` | `ros2 lifecycle set {node} shutdown` | `ros2 lifecycle set {node} activate` |
| `regular` | `kill {pid}` (⚠️ с предупреждением) | Требует launch-файл (не в MVP) |
| `unknown` | Кнопка недоступна | — |

### 5.3 Получение PID обычной ноды (для kill)

```bash
# Внутри Docker контейнера
ps aux | grep {executable_name} | grep -v grep | awk '{print $2}'
```

**Проблема:** Нужно знать имя исполняемого файла, а не имя ноды. 
**Решение для MVP:** 
- Для `regular` нод показываем кнопку "Shutdown" с предупреждением
- Пробуем найти PID через `pgrep -f {node_name}`
- Если не нашли — сообщаем пользователю

---

## 6. API Endpoints

### 6.1 REST API

```
# Серверы
GET  /api/servers                    # Список серверов из конфига
POST /api/servers/connect            # Подключиться к серверу
     body: { "server_id": "tram-dev" }
GET  /api/servers/current            # Текущий подключённый сервер

# Ноды
GET  /api/nodes                      # Список всех нод (из кэша + обновление)
GET  /api/nodes/{node_name}/info     # Детали ноды (subscribers, publishers)
GET  /api/nodes/{node_name}/params   # Параметры ноды
POST /api/nodes/{node_name}/shutdown # Выключить ноду
     body: { "force": false }        # force=true для kill

# Топики (задел на будущее)
GET  /api/topics                     # Список топиков
POST /api/topics/{topic}/hz/start    # Начать измерение частоты
POST /api/topics/{topic}/hz/stop     # Остановить измерение
POST /api/topics/{topic}/echo/start  # Начать echo
POST /api/topics/{topic}/echo/stop   # Остановить echo
```

### 6.2 WebSocket API

```
WS /ws/logs/{node_name}    # Стрим логов для конкретной ноды
   → { "timestamp": "...", "level": "INFO", "message": "..." }

WS /ws/nodes/status        # Периодические обновления статуса всех нод
   → { "nodes": { "/node1": "active", "/node2": "inactive" } }

# Будущее (топики)
WS /ws/topics/{topic}/hz   # Стрим частоты
WS /ws/topics/{topic}/echo # Стрим сообщений
```

---

## 7. Компоненты Frontend

### 7.1 Layout

```
┌─────────────────────────────────────────────────────────────────────────┐
│  [Server: tram-dev ▼]  [🔄 Refresh]  [⚙️ Settings]                      │
│                                                                         │
│  Nodes: 127 total | 98 active | 29 inactive                            │
├────────────────────────┬────────────────────────────────────────────────┤
│                        │                                                │
│   NODE TREE            │   DETAIL PANEL                                 │
│                        │                                                │
│   ▼ /sensing (45)      │   Node: /sensing/radar/front/pe_ars408_node   │
│     ▼ /radar (12)      │   ─────────────────────────────────────────   │
│       ▼ /front (3)     │   Status: ● Active                            │
│         ● pe_ars408    │   Type: ◐ Lifecycle (active)                  │
│         ○ can_receiver │   [Shutdown] [View Logs]                      │
│       ▶ /rear (3)      │                                                │
│     ▶ /lidar (18)      │   Parameters:                                  │
│   ▼ /planning (32)     │   ├─ frame_id: "radar_front"                  │
│     ● planner_node     │   ├─ interface: "can0"                        │
│   ▶ /control (24)      │   └─ timeout_sec: 0.01                        │
│                        │                                                │
│   ─────────────────    │   Subscribers:                                 │
│   Legend:              │   └─ /input/frame                             │
│   ● Active             │                                                │
│   ○ Inactive           │   Publishers:                                  │
│   ◐ Lifecycle          │   ├─ /output/objects                          │
│   ? Unknown type       │   └─ /output/scan                             │
│                        │                                                │
├────────────────────────┴────────────────────────────────────────────────┤
│                           LOG PANEL (collapsible)                       │
│  Node: /sensing/radar/front/pe_ars408_node                    [✕ Close] │
│  ──────────────────────────────────────────────────────────────────────│
│  [15:30:01] INFO  Node started successfully                             │
│  [15:30:02] INFO  CAN interface initialized: can0                       │
│  [15:30:05] WARN  Low signal quality detected                           │
│  [15:30:10] INFO  Objects detected: 5                                   │
│  [auto-scroll ▼]                                                        │
└─────────────────────────────────────────────────────────────────────────┘
```

**Счётчики:**
- **total** — все известные ноды (из node_state.json)
- **active** — ноды, которые сейчас видны в `ros2 node list`
- **inactive** — ноды, которые были раньше, но сейчас не запущены

**Счётчики в дереве** (в скобках):
- Показывают количество нод в каждом namespace
- Помогают ориентироваться в большом дереве

### 7.2 Компоненты React

```
src/
├── components/
│   ├── ServerSelector.jsx     # Комбобокс выбора сервера
│   ├── StatusBar.jsx          # Счётчики: total | active | inactive
│   ├── NodeTree.jsx           # Дерево нод по namespace
│   ├── NodeTreeItem.jsx       # Элемент дерева (с индикатором статуса)
│   ├── NodeDetailPanel.jsx    # Панель деталей ноды
│   ├── NodeParameters.jsx     # Отображение параметров
│   ├── NodeActions.jsx        # Кнопки действий (Shutdown, Logs)
│   ├── LogPanel.jsx           # Панель логов (WebSocket)
│   └── TopicPanel.jsx         # Заготовка для топиков (будущее)
├── hooks/
│   ├── useNodes.js            # Хук для работы с нодами
│   ├── useWebSocket.js        # Хук для WebSocket подключений
│   └── useServerConnection.js # Хук для управления подключением
├── services/
│   ├── api.js                 # HTTP запросы к backend
│   └── websocket.js           # WebSocket клиент
└── App.jsx
```

---

## 8. Структура Backend

```
ros2_node_manager/
├── server/
│   ├── __init__.py
│   ├── main.py                # FastAPI app, точка входа
│   ├── config.py              # Загрузка конфигурации
│   ├── models.py              # Pydantic модели
│   │
│   ├── connection/
│   │   ├── __init__.py
│   │   ├── base.py            # Абстрактный класс ConnectionManager
│   │   ├── local.py           # LocalDockerConnection
│   │   └── ssh.py             # SSHDockerConnection
│   │
│   ├── services/
│   │   ├── __init__.py
│   │   ├── node_service.py    # Работа с нодами (list, info, params)
│   │   ├── lifecycle.py       # Lifecycle управление
│   │   └── log_collector.py   # Сбор логов через /rosout
│   │
│   ├── state/
│   │   ├── __init__.py
│   │   └── persister.py       # Сохранение/загрузка node_state.json
│   │
│   └── routers/
│       ├── __init__.py
│       ├── servers.py         # /api/servers/*
│       ├── nodes.py           # /api/nodes/*
│       └── websocket.py       # WebSocket endpoints
│
├── web/                       # React приложение (или static build)
│   └── ...
│
├── config/
│   └── servers.yaml           # Конфигурация серверов
│
├── data/
│   └── node_state.json        # Персистентное состояние
│
├── requirements.txt
├── Dockerfile                 # Задел на будущее
└── README.md
```

---

## 9. Логи нод

### 9.1 Источник логов

Основной источник — топик `/rosout` (стандартный ROS2 топик для логов).

```python
# Внутри Docker выполняем:
ros2 topic echo /rosout --no-arr | grep "{node_name}"
```

Или через rclpy подписку (сложнее, но надёжнее):

```python
# log_collector.py (запускается внутри Docker как отдельный процесс)
import rclpy
from rcl_interfaces.msg import Log

class LogCollector:
    def __init__(self):
        self.node = rclpy.create_node('log_collector')
        self.subscription = self.node.create_subscription(
            Log, '/rosout', self.log_callback, 10)
        self.subscribers = {}  # node_name -> [websocket_queues]
    
    def log_callback(self, msg):
        node_name = msg.name
        if node_name in self.subscribers:
            for queue in self.subscribers[node_name]:
                queue.put_nowait({
                    "timestamp": msg.stamp,
                    "level": self._level_to_str(msg.level),
                    "message": msg.msg
                })
```

### 9.2 Простой вариант (для MVP)

```python
# Просто grep по /rosout
async def stream_logs(node_name: str, websocket):
    cmd = f"ros2 topic echo /rosout --no-arr"
    process = await asyncio.create_subprocess_shell(
        docker_exec(cmd),
        stdout=asyncio.subprocess.PIPE
    )
    
    async for line in process.stdout:
        if node_name in line.decode():
            await websocket.send_text(line.decode())
```

---

## 10. Задел для топиков (будущее)

### 10.1 Topic Hz

```python
# Запуск измерения (subprocess)
processes = {}  # topic -> subprocess

async def start_hz(topic: str):
    if len(processes) >= 5:
        return {"error": "Max 5 topics for hz monitoring"}
    
    cmd = f"ros2 topic hz {topic}"
    processes[topic] = await asyncio.create_subprocess_shell(...)

async def stream_hz(topic: str, websocket):
    # Парсить вывод ros2 topic hz и отправлять в WebSocket
    pass
```

### 10.2 Topic Echo

Горизонтальная панель с вкладками:

```
┌─────────────────────────────────────────────────────────────────────┐
│  TOPIC ECHO                                                   [✕]   │
├─────────────────┬─────────────────┬─────────────────┬───────────────┤
│ /radar/scan     │ /lidar/points   │ /odom           │    [+ Add]    │
│ ────────────────│─────────────────│─────────────────│               │
│ header:         │ header:         │ pose:           │               │
│   stamp: ...    │   stamp: ...    │   position:     │               │
│ ranges: [...]   │ points: [...]   │     x: 1.5      │               │
│                 │                 │     y: 0.3      │               │
│ [⏸ Pause]       │ [⏸ Pause]       │ [⏸ Pause]       │               │
└─────────────────┴─────────────────┴─────────────────┴───────────────┘
```

---

## 11. План реализации (этапы)

### Этап 1: Базовая инфраструктура (2-3 дня)
- [ ] Структура проекта
- [ ] FastAPI сервер с базовыми endpoints
- [ ] Подключение к локальному Docker
- [ ] `ros2 node list` → JSON

### Этап 2: Дерево нод (2-3 дня)
- [ ] Парсинг namespace в дерево
- [ ] React компонент NodeTree
- [ ] Сохранение состояния в JSON файл
- [ ] Отображение active/inactive

### Этап 3: Детали ноды (2 дня)
- [ ] `ros2 node info` → subscribers/publishers
- [ ] `ros2 param dump` → параметры
- [ ] Определение lifecycle нод
- [ ] NodeDetailPanel компонент

### Этап 4: Управление нодами (2 дня)
- [ ] Shutdown для lifecycle нод
- [ ] Kill для обычных нод (с предупреждением)
- [ ] Обновление UI после действий

### Этап 5: Логи (2-3 дня)
- [ ] WebSocket endpoint для логов
- [ ] Подписка на /rosout с фильтрацией
- [ ] LogPanel компонент
- [ ] Auto-scroll, pause

### Этап 6: SSH подключение (2 дня)
- [ ] SSHDockerConnection класс
- [ ] Конфигурация серверов
- [ ] ServerSelector компонент

### Этап 7: Полировка (2 дня)
- [ ] Обработка ошибок
- [ ] Loading states
- [ ] Reconnection logic
- [ ] Документация

**Итого MVP: ~2-3 недели**

---

## 12. Технологии

| Компонент | Технология | Почему |
|-----------|------------|--------|
| Backend | Python 3.10+ / FastAPI | Простота, async, хорошая документация |
| WebSocket | FastAPI WebSocket | Встроенная поддержка |
| SSH | asyncssh | Async SSH клиент для Python |
| Frontend | React 18 + Vite | Быстрая разработка, хуки |
| Styling | Tailwind CSS | Utility-first, быстрая вёрстка |
| State | React hooks + Context | Без лишних библиотек |
| Docker exec | subprocess / asyncssh | Минимум зависимостей |

---

## 13. Открытые вопросы

1. **Kill обычных нод:** Как надёжно получить PID процесса ноды внутри Docker?
   - Вариант: `pgrep -f executable_name`
   - Вариант: Парсить `/proc` внутри контейнера
   
2. **Reconnection:** Что делать при потере SSH соединения?
   - Auto-reconnect с экспоненциальным backoff?
   
3. **Множественные пользователи:** Если два человека откроют UI одновременно?
   - Пока игнорируем (single-user scenario)

4. **Безопасность:** SSH ключи/пароли в конфиге — это ОК для внутреннего инструмента?

---

## 14. Команды для разработки

```bash
# Backend
cd ros2_node_manager
python -m venv venv
source venv/bin/activate
pip install fastapi uvicorn asyncssh pyyaml

uvicorn server.main:app --reload --port 8080

# Frontend
cd web
npm create vite@latest . -- --template react
npm install
npm run dev

# Docker (тестовый контейнер)
docker run -it --name ros2_test ros:humble bash
```

---

## 15. Ссылки

- [FastAPI WebSocket](https://fastapi.tiangolo.com/advanced/websockets/)
- [asyncssh documentation](https://asyncssh.readthedocs.io/)
- [ROS2 CLI tools](https://docs.ros.org/en/humble/Tutorials/Beginner-CLI-Tools.html)
- [rcl_interfaces/msg/Log](http://docs.ros.org/en/humble/p/rcl_interfaces/interfaces/msg/Log.html)
