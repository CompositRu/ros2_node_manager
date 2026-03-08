# Tram Monitoring System

Веб-интерфейс для мониторинга ROS2 нод на автономных трамваях. Подключается к Docker контейнеру с ROS2 через **monitoring_agent** (WebSocket JSON-RPC).

![Python](https://img.shields.io/badge/python-3.10+-green)
![React](https://img.shields.io/badge/react-18-blue)
![FastAPI](https://img.shields.io/badge/fastapi-0.100+-teal)

## Обзор

Интерфейс в стиле VS Code: панель навигации слева, рабочая область справа. Восемь секций: Dashboard, Diagnostics, Nodes, Topics, Services, Logs, History, App Stats.

Подключается к одному из настроенных серверов (агентов внутри Docker). Первый сервер подключается автоматически при старте.

---

## Возможности

### Dashboard

Сводная панель состояния системы:

- **Статус автопилота** — баннер с цветовой индикацией (зелёный — работает, жёлтый — частично, красный — критический, серый — offline). Анимированная точка пульсации.
- **Скорость** — текущая скорость в км/ч из `/localization/kinematic_state`. Отображается только при работающем автопилоте.
- **Ресурсы** — CPU%, GPU%, RAM с цветными прогресс-барами (красный >90%, жёлтый >70%, зелёный <70%).
- **Статистика** — количество нод (active/total), топиков, сервисов, аптайм контейнера.
- **Недавние алерты** — последние алерты с цветовой кодировкой по severity.
- **Быстрый доступ** — кнопки навигации к основным секциям.

### Diagnostics

Мониторинг диагностик из топика `/diagnostics` (DiagnosticArray):

- **Виджеты ресурсов** — три кольцевых индикатора: CPU (температура + загрузка), GPU (температура + VRAM), RAM (использовано / всего).
- **Карточки диагностик** — адаптивная сетка (2–5 колонок). Каждая карточка: статус (OK/WARN/ERROR/STALE), имя, сообщение, ключевые метрики.
- **Специальные карточки**:
  - Localization (NDT) — расширенная карточка с метриками: iterations, likelihood, transform probability, skip pub. Цветовая кодировка по пороговым значениям.
  - Bag Recorder — статус записи.
  - Lidar Sync — синхронизация лидаров.
  - MRM — статус минимально-рискового манёвра (NORMAL/ERROR/OPERATING).
- **Детальный вид** — по клику: все key-value пары, hardware ID, история последних 20 записей.
- **Фильтры** — по уровню (OK/WARN/ERROR/STALE), поиск по имени. Счётчики по каждому уровню.
- **Стриминг в реальном времени** через WebSocket с индикатором подключения.

### Nodes

Управление и мониторинг ROS2 нод:

- **Дерево нод** — иерархия по namespace с подсчётом (active/total) на каждом уровне. Раскрытие/сворачивание всех веток.
- **Индикаторы** — зелёная точка (active), серая (inactive), фиолетовая полуточка (lifecycle).
- **Детальная панель** — по клику на ноду:
  - Статус, тип, lifecycle state.
  - Параметры (подгрузка по требованию).
  - Subscribers (cyan), Publishers (зелёный), Services (жёлтый) — сворачиваемые секции.
- **Lifecycle-управление** — кнопки: Configure, Activate, Deactivate, Cleanup, Shutdown. Доступны для lifecycle-нод.
- **Kill** — для обычных нод (с подтверждением).
- **Групповые действия** — правый клик на namespace: shutdown всех lifecycle-нод или kill всех нод в ветке.
- **Логи ноды** — выдвижная панель снизу с real-time стримингом из /rosout. Пауза/продолжение, авто-прокрутка, цветовая кодировка по уровню (DEBUG/INFO/WARN/ERROR/FATAL).
- **Обновления** — статус нод обновляется каждые 5 секунд через WebSocket.

Технические ноды (transform_listener, ros2cli, daemon, launch_ros) скрыты из отображения.

### Topics

Два режима просмотра:

**Groups** — конфигурированные группы топиков (из `topic_groups.yaml`):
- Карточки групп с общим префиксом.
- Кнопка Hz — включает мониторинг частоты публикации (shared между клиентами, без дублирования процессов).
- Кнопка Echo — стриминг сообщений группы. Панель снизу: тема + JSON-данные, пауза, очистка.

**Tree** — все топики в виде дерева по namespace:
- Фильтр по имени или типу сообщения.
- На каждом топике: кнопка Info (тип, publishers, subscribers), Hz (частота), Echo (стриминг).
- Echo с фильтрацией полей — чипы для скрытия/показа отдельных полей.

### Services

Просмотр и вызов ROS2 сервисов:

- **Дерево сервисов** — иерархия по namespace, оранжевый индикатор «S».
- **Info** — тип сервиса, структура request и response полей.
- **Call** — редактор YAML-запроса с автозаполнением шаблона (типы полей: bool, int, string и т.д.). Выполнение вызова и просмотр ответа.
- **Фильтр** — поиск по имени или типу. Технические сервисы (lifecycle, parameters, actions) скрыты по умолчанию.

### Logs

Единый поток логов со всех нод (/rosout):

- Цветовая кодировка: DEBUG (серый), INFO (синий), WARN (жёлтый), ERROR (красный), FATAL (красный).
- Фильтры по уровню и имени ноды.
- Пауза/продолжение с индикатором буферизованных сообщений.
- Авто-прокрутка, очистка.
- При подключении — replay истории (до 1000 записей, не старше 5 минут).

### History

Персистентная история с хранением в SQLite:

**Log History**:
- Фильтры: уровень, имя ноды, полнотекстовый поиск по сообщению.
- Пагинация с навигацией по страницам.
- Экспорт в JSON или текстовый формат.
- Хранение до 50 000 записей (уровень WARN и выше).

**Alert History**:
- Фильтры: тип алерта, severity, имя ноды.
- Карточки с цветовой полосой по severity.
- Бейджи: тип (зелёный для recovered, красный для inactive/missing), severity, нода.
- Хранение до 10 000 записей.

### App Stats

Внутренние метрики сервера:

- CPU% (сервер), RSS (физическая память).
- Количество активных стримов, WebSocket-соединений.
- Аптайм сервера, общее количество выполненных запросов.

### Алерты

Система алертов в реальном времени (настраивается в `alerts.yaml`):

| Тип | Описание |
|-----|----------|
| Node Inactive | Нода перешла в INACTIVE |
| Node Recovered | Нода снова ACTIVE |
| Missing Topic | Важный топик отсутствует |
| Topic Recovered | Топик появился |
| Error Pattern | Regex-паттерн найден в логах |
| Topic Value | Критическое значение в топике |

Дедупликация с настраиваемым cooldown (по умолчанию 60 сек). Toast-уведомления в правом нижнем углу (макс. 5, автоскрытие через 7 сек).

---

## Архитектура подключения

Backend подключается к **monitoring_agent** — ROS2-ноде внутри Docker-контейнера, которая предоставляет WebSocket JSON-RPC API на порту 9090.

```
Browser ↔ FastAPI backend ↔ WebSocket JSON-RPC ↔ monitoring_agent (внутри Docker) ↔ ROS2
```

Agent обеспечивает:
- Прямой доступ к ROS2 API (rclpy) без `docker exec`
- JSON-стриминг топиков (diagnostics, logs, echo, hz)
- Сбор системных метрик (CPU, GPU, RAM, uptime)

---

## Быстрый старт

### Установка

```bash
# Backend
cd ros2_node_manager
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt

# Frontend
cd web && npm install
```

### Настройка

`config/config.yaml` — серверы:
```yaml
servers:
  - id: local-agent
    name: "Local Agent"
    agent_url: "ws://localhost:9090"
```

`config/topic_groups.yaml` — группы топиков для мониторинга Hz и echo:
```yaml
topic_groups:
  - id: lidar_raw
    name: "LiDAR Raw"
    topics:
      - /sensing/lidar/top/packets
```

`config/alerts.yaml` — правила алертов:
```yaml
enabled: true
cooldown_seconds: 60
important_topics:
  - /perception/lidar/pointcloud
error_patterns:
  - pattern: "FATAL"
    severity: critical
monitored_topics:
  - topic: /system/emergency
    field: data
    alert_on_value: true
```

### Запуск

**Development** (два терминала):
```bash
# Backend
uvicorn server.main:app --reload --port 8080

# Frontend
cd web && npm run dev
```
UI: http://localhost:3000

**Production**:
```bash
cd web && npm run build && cd ..
uvicorn server.main:app --host 0.0.0.0 --port 8080
```
UI: http://localhost:8080

---

## Деплой на трамвай

**Простой деплой** (без systemd):
```bash
./deploy/deploy-simple.sh <host> [user]       # Копирует код
./deploy/start-remote.sh <host> [user]         # Запускает сервер через SSH
```

**Полный деплой** (с systemd):
```bash
./deploy/deploy.sh <host> [user]               # Копирует, ставит в автозагрузку, запускает
```

**Управление**:
```bash
./deploy/stop.sh                               # Остановить (локально)
./deploy/start.sh                              # Запустить (локально)
./deploy/update.sh                             # Обновить код и перезапустить
./deploy/uninstall-remote.sh <host> [user]     # Убрать из systemd
./deploy/uninstall-remote.sh <host> [user] --purge  # + удалить файлы
```

---

## API

### REST

| Endpoint | Описание |
|----------|----------|
| `GET /api/servers` | Список серверов |
| `POST /api/servers/connect` | Подключиться к серверу |
| `POST /api/servers/disconnect` | Отключиться |
| `GET /api/nodes` | Список нод (active/inactive/total) |
| `GET /api/nodes/{name}` | Детали ноды |
| `GET /api/nodes/{name}/params` | Параметры ноды |
| `POST /api/nodes/{name}/lifecycle` | Lifecycle-переход |
| `POST /api/nodes/{name}/shutdown` | Остановить ноду |
| `POST /api/nodes/group/action` | Групповое действие по namespace |
| `GET /api/topics/list` | Список топиков |
| `GET /api/topics/info/{topic}` | Info топика (publishers/subscribers) |
| `GET /api/topics/groups` | Группы топиков с Hz |
| `POST /api/topics/groups/{id}/hz` | Вкл/выкл Hz мониторинг |
| `GET /api/services/list` | Список сервисов |
| `GET /api/services/interface/{type}` | Интерфейс сервиса |
| `POST /api/services/call/{name}` | Вызов сервиса |
| `GET /api/dashboard` | Данные для Dashboard |
| `GET /api/history/logs` | История логов (с фильтрами и пагинацией) |
| `GET /api/history/alerts` | История алертов |
| `GET /api/history/logs/export` | Экспорт логов (JSON/text) |
| `GET /api/debug/stats` | Метрики приложения |

### WebSocket

| Endpoint | Описание |
|----------|----------|
| `/ws/nodes/status` | Статус нод (каждые 5 сек) |
| `/ws/logs/all` | Все логи из /rosout |
| `/ws/logs/{node}` | Логи конкретной ноды |
| `/ws/diagnostics` | Диагностики |
| `/ws/alerts` | Алерты |
| `/ws/topics/hz` | Hz всех активных групп |
| `/ws/topics/hz-single/{topic}` | Hz одного топика |
| `/ws/topics/echo/{group_id}` | Echo группы топиков |
| `/ws/topics/echo-single/{topic}` | Echo одного топика |

---

## Структура проекта

```
ros2_node_manager/
├── server/
│   ├── connection/          # AgentConnection (WebSocket JSON-RPC)
│   ├── services/            # NodeService, LogCollector, DiagnosticsCollector,
│   │                        # TopicHzMonitor, SharedEchoMonitor, AlertService,
│   │                        # HistoryStore, SpeedMonitor, Metrics
│   ├── state/               # StatePersister (JSON-состояние нод)
│   ├── routers/             # REST и WebSocket endpoints
│   ├── models.py            # Pydantic-модели
│   ├── config.py            # Загрузка конфигурации
│   └── main.py              # FastAPI app, lifecycle, middleware
├── web/src/
│   ├── components/          # React-компоненты (секции, UI-утилиты)
│   ├── hooks/               # Custom hooks (данные, WebSocket)
│   └── services/            # REST и WebSocket клиенты
├── config/
│   ├── config.yaml          # Серверы (agent_url)
│   ├── topic_groups.yaml    # Группы топиков
│   └── alerts.yaml          # Правила алертов
├── deploy/                  # Скрипты деплоя
├── data/                    # Состояние нод, SQLite история
└── requirements.txt
```

## Требования

- Python 3.10+
- Node.js 18+
- monitoring_agent (ROS2 нода с WebSocket сервером на порту 9090)

## Лицензия

MIT
