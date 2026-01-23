# ROS2 Node Manager

Web-интерфейс для мониторинга и управления ROS2 нодами в Docker контейнерах.

![Version](https://img.shields.io/badge/version-0.1.0-blue)
![Python](https://img.shields.io/badge/python-3.10+-green)
![React](https://img.shields.io/badge/react-18-blue)

## Возможности

- 🌳 **Дерево нод** по namespace с подсчётом количества
- 🔄 **Real-time обновления** статуса нод через WebSocket
- 📊 **Счётчики**: total | active | inactive
- 💾 **Сохранение истории** — inactive ноды не удаляются
- 🔌 **Локальный Docker** и **SSH подключение** к удалённым серверам
- ⚙️ **Параметры ноды**: просмотр всех параметров
- 📡 **Subscribers/Publishers**: что нода слушает и публикует
- 🛑 **Shutdown** для lifecycle нод
- 💀 **Kill** для обычных нод (с предупреждением)
- 📜 **Логи** в реальном времени из /rosout

## Быстрый старт

### 1. Установка зависимостей

```bash
# Backend
cd ros2_node_manager
python -m venv venv
source venv/bin/activate  # Linux/Mac
# или: venv\Scripts\activate  # Windows
pip install -r requirements.txt

# Frontend
cd web
npm install
```

### 2. Настройка

Отредактируйте `config/servers.yaml`:

```yaml
servers:
  - id: local
    name: "Local Docker"
    type: local
    container: tram_autoware  # Имя вашего контейнера

  # Для удалённого сервера:
  - id: remote
    name: "Remote Server"
    type: ssh
    host: 192.168.1.100
    user: ubuntu
    container: tram_autoware
    ssh_key: ~/.ssh/id_rsa
```

### 3. Запуск

**Development mode (два терминала):**

```bash
# Терминал 1: Backend
cd ros2_node_manager
source venv/bin/activate
uvicorn server.main:app --reload --port 8080

# Терминал 2: Frontend
cd ros2_node_manager/web
npm run dev
```

Откройте http://localhost:3000

**Production mode:**

```bash
# Собрать frontend
cd web
npm run build

# Запустить backend (будет раздавать статику)
cd ..
uvicorn server.main:app --host 0.0.0.0 --port 8080
```

Откройте http://localhost:8080

## Структура проекта

```
ros2_node_manager/
├── server/                    # Backend (FastAPI)
│   ├── connection/           # Подключения (local, ssh)
│   ├── services/             # Бизнес-логика
│   ├── state/                # Персистентность
│   ├── routers/              # API endpoints
│   ├── models.py             # Pydantic модели
│   ├── config.py             # Конфигурация
│   └── main.py               # Точка входа
├── web/                       # Frontend (React)
│   └── src/
│       ├── components/       # React компоненты
│       ├── hooks/            # Custom hooks
│       └── services/         # API клиент
├── config/
│   └── servers.yaml          # Конфигурация серверов
├── data/                      # Сохранённое состояние (gitignore)
├── requirements.txt
├── ROADMAP.md                 # План развития
└── README.md
```

## API

### REST API

| Endpoint | Method | Описание |
|----------|--------|----------|
| `/api/servers` | GET | Список серверов |
| `/api/servers/connect` | POST | Подключиться к серверу |
| `/api/servers/disconnect` | POST | Отключиться |
| `/api/nodes` | GET | Список нод |
| `/api/nodes/{name}` | GET | Детали ноды |
| `/api/nodes/{name}/shutdown` | POST | Выключить ноду |
| `/health` | GET | Статус сервера |

### WebSocket

| Endpoint | Описание |
|----------|----------|
| `/ws/nodes/status` | Real-time статус нод |
| `/ws/logs/{node_name}` | Стрим логов ноды |

## Типы нод

| Тип | Описание | Действия |
|-----|----------|----------|
| `lifecycle` | Lifecycle нода | Shutdown через `ros2 lifecycle set` |
| `regular` | Обычная нода | Kill процесса |
| `unknown` | Тип ещё не определён | Действия недоступны |

## Требования

- Python 3.10+
- Node.js 18+
- Docker (на целевой машине)
- SSH доступ (для удалённых серверов)

## Переменные окружения

```bash
ROS2_NODE_MANAGER_HOST=0.0.0.0
ROS2_NODE_MANAGER_PORT=8080
```

## Известные ограничения

1. **Kill обычных нод** — работает не всегда, зависит от имени процесса
2. **Запуск нод** — не реализован (требует launch-файлы)
3. **Изменение параметров** — только просмотр

## Roadmap

Смотрите [ROADMAP.md](ROADMAP.md) для планов развития.

## Лицензия

MIT
