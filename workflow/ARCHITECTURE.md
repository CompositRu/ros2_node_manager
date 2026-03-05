# Architecture

## Обзор системы

**Tram Monitoring System** — два связанных проекта:

1. **ros2_node_manager** (этот репозиторий) — веб-интерфейс (FastAPI + React)
2. **monitoring_agent** (`~/tram.autoware/src/system/monitoring_agent/`) — ROS2 нода внутри Docker, WebSocket API для прямого доступа к ROS2

Связь: ros2_node_manager подключается к monitoring_agent по WebSocket (JSON-RPC 2.0) вместо docker exec, что даёт latency 1-20ms вместо 200-500ms.

---

## Backend (`server/`)

### Connection Layer (`connection/`)
- `BaseConnection` — абстрактный класс для выполнения команд внутри Docker
- `LocalDockerConnection` — `docker exec` локально
- `SSHDockerConnection` — `docker exec` через SSH (asyncssh)
- `AgentConnection` — WebSocket клиент к monitoring_agent (JSON-RPC 2.0)
- ROS2 CLI обёрнуты в методы: `ros2_node_list()`, `ros2_node_info()`, `ros2_topic_list()`, `ros2_topic_info()`, `ros2_param_dump()`, `ros2_lifecycle_set()`, и т.д.
- Кеш ROS environment переменных и сервисов для быстрых повторных вызовов

### Services (`services/`)
- `NodeService` — бизнес-логика нод (список, статусы, lifecycle, параметры)
- `LogCollector` — стриминг логов из `/rosout`
- `DiagnosticsCollector` — стриминг `/diagnostics` топика, парсинг DiagnosticArray
- `TopicHzMonitor` — on-demand мониторинг Hz по группам топиков (shared cache между клиентами)
- `topic_echo_streamer` — per-client echo топиков с мультиплексингом
- `AlertService` — мониторинг алертов (inactive ноды, паттерны логов) с дедупликацией и cooldown
- `Metrics` — внутренние метрики (subprocess, streams, WebSocket connections)

### State (`state/`)
- `StatePersister` — сохраняет состояние нод в `data/{server_id}.json`
- Отслеживает inactive ноды (были раньше, сейчас пропали)

### Routers (`routers/`)
- `servers.py` — `/api/servers/*` — подключение к серверам
- `nodes.py` — `/api/nodes/*` — операции с нодами (список, детали, параметры)
- `topics.py` — `/api/topics/*` — список топиков, info (publishers/subscribers), группы
- `debug.py` — `/api/debug/stats` — внутренние метрики приложения
- `websocket.py` — WebSocket эндпоинты:
  - `/ws/nodes/status` — real-time статус нод
  - `/ws/logs/{node}`, `/ws/logs/all` — логи (per-node и unified)
  - `/ws/diagnostics` — диагностики
  - `/ws/topics/hz`, `/ws/topics/hz-single/{topic}` — мониторинг Hz
  - `/ws/topics/echo/{group_id}`, `/ws/topics/echo-single/{topic}` — echo топиков
  - `/ws/alerts` — алерты

### Key Models (`models.py`)
- `NodeType`: LIFECYCLE | REGULAR | UNKNOWN
- `NodeStatus`: ACTIVE | INACTIVE
- `LifecycleState`: UNCONFIGURED | INACTIVE | ACTIVE | FINALIZED
- `TopicGroup`, `TopicGroupsConfig` — конфигурация групп топиков

---

## Frontend (`web/src/`)

React 18 + Vite + TailwindCSS. Структура VS Code-style: Activity Bar слева, секции переключаются по клику.

### Секции (Activity Bar)
- **Nodes** — дерево нод по namespace, детали, параметры, lifecycle, логи
- **Diagnostics** — dashboard-сетка диагностик с карточками и виджетами CPU/GPU/RAM
- **Topics** — два режима: Groups (конфигурированные группы с Hz) и Tree (все топики деревом с echo, Hz, info, фильтрацией полей)
- **Logs** — unified log stream со всех нод, фильтрация по уровню и ноде
- **App Stats** — внутренние метрики приложения (CPU, RSS, connections)

### Components (`components/`)
- `ActivityBar` — навигация секций
- `NodeTree`, `NodeDetailPanel` — дерево нод и детали
- `Diagnostics` — dashboard диагностик
- `Topics`, `TopicTree` — два вида топиков
- `UnifiedLogs`, `LogPanel` — логи
- `AppStats` — системные метрики
- `ServerSelector` — выбор сервера
- `ConfirmModal`, `ContextMenu`, `Resizer`, `StatusBar`, `ToastContainer` — UI утилиты

### Hooks (`hooks/`)
- `useNodes`, `useServer` — ноды и сервер
- `useDiagnostics` — диагностики
- `useTopicGroups`, `useTopicEcho` — топики
- `useUnifiedLogs` — unified логи
- `useAlerts` — алерты
- `useSystemStats` — метрики
- `useNotifications` — toast-уведомления

### Services (`services/`)
- `api.js` — REST API клиент
- `websocket.js` — WebSocket фабрики для каждого типа стрима

---

## Monitoring Agent (`~/tram.autoware/src/system/monitoring_agent/`)

ROS2 нода (Python, ament_python), работает внутри Docker контейнера. WebSocket сервер на порту 9090.

### Структура
```
monitoring_agent/
├── main.py                 # Entry point (asyncio + rclpy)
├── node.py                 # MonitoringAgentNode(Node)
├── ws_server.py            # WebSocket сервер, JSON-RPC dispatch
├── protocol.py             # Хелперы протокола
├── load_generator.py       # Нагрузочное тестирование
└── handlers/
    ├── graph.py             # Node/topic/service introspection
    ├── topics.py            # Echo + Hz streaming
    ├── lifecycle.py         # Lifecycle state management
    ├── params.py            # Parameter dump/set
    ├── services.py          # Service calls
    ├── process.py           # Process management (kill)
    ├── logs.py              # /rosout streaming
    └── diagnostics.py       # /diagnostics streaming
```

### Протокол
- Спецификация: `docs/agent_protocol.md`
- Транспорт: WebSocket, JSON-RPC 2.0
- Команды: `graph.*`, `lifecycle.*`, `params.*`, `service.call`, `process.kill`
- Подписки: `topic.echo`, `topic.hz`, `logs`, `diagnostics`
- Heartbeat: 10s ping, 30s timeout

---

## Конфигурация

- `config/servers.yaml` — серверы (local/ssh/agent)
- `config/topic_groups.yaml` — группы топиков для Hz/echo мониторинга
- `config/alerts.yaml` — правила алертов

## ROS2 Environment

- ROS2 Humble, cyclonedds
- Sources `/opt/ros/humble/setup.bash`
- `ROS_DOMAIN_ID` из `$HOME/tram.autoware/.ros_domain_id`
- `ROS_LOCALHOST_ONLY=1`, `RMW_IMPLEMENTATION=rmw_cyclonedds_cpp`
- Технические ноды (transform_listener, ros2cli, daemon, launch_ros) отфильтрованы
