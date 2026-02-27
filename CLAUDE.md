# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**Tram Monitoring System** — веб-интерфейс для мониторинга ROS2 нод в Docker контейнерах на автономных трамваях. Основной фокус — мониторинг и диагностика, а не управление. Управление нодами (lifecycle, kill) есть, но развивается в меньшем приоритете.

Подключается к Docker контейнеру с ROS2 через локальный docker exec или удалённо через SSH.

Планируется связка с **Fleet Radar** — отдельным приложением с обзором всех единиц флота, откуда можно быстро перейти в Tram Monitoring System конкретного трамвая.

## Development Commands

### Backend (FastAPI/Python)
```bash
# Setup
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt

# Run development server (auto-reload)
uvicorn server.main:app --reload --port 8080

# Run production
uvicorn server.main:app --host 0.0.0.0 --port 8080
```

### Frontend (React/Vite)
```bash
cd web
npm install
npm run dev      # Development (port 3000)
npm run build    # Production build to web/dist/
```

### Full Stack Development
Run backend on port 8080, frontend dev server on port 3000. Frontend proxies API calls to backend.

## Deployment

Основной сценарий деплоя на трамвай:

1. **Деплой с локального компьютера:** `deploy/deploy-simple.sh <host> [user]` — копирует код на целевую машину
2. **Запуск удалённо:** `deploy/start-remote.sh <host> [user]` — запускает сервер на трамвае через SSH

После стабилизации — полный деплой через `deploy/deploy.sh` с регистрацией в systemd (`deploy/ros2-monitor.service`).

Остальные скрипты: `deploy/start.sh` (локальный запуск), `deploy/stop.sh` (остановка), `deploy/update.sh` (обновление), `deploy/monitor-resources.sh` (мониторинг ресурсов).

## Architecture

### Backend (`server/`)

**Connection Layer** (`connection/`):
- `BaseConnection` — абстрактный класс для выполнения команд внутри Docker
- `LocalDockerConnection` — `docker exec` локально
- `SSHDockerConnection` — `docker exec` через SSH (asyncssh)
- ROS2 CLI обёрнуты в методы: `ros2_node_list()`, `ros2_node_info()`, `ros2_topic_list()`, `ros2_topic_info()`, `ros2_param_dump()`, `ros2_lifecycle_set()`, и т.д.
- Кеш ROS environment переменных и сервисов для быстрых повторных вызовов

**Services** (`services/`):
- `NodeService` — бизнес-логика нод (список, статусы, lifecycle, параметры)
- `LogCollector` — стриминг логов из `/rosout`
- `DiagnosticsCollector` — стриминг `/diagnostics` топика, парсинг DiagnosticArray
- `TopicHzMonitor` — on-demand мониторинг Hz по группам топиков (shared cache между клиентами)
- `topic_echo_streamer` — per-client echo топиков с мультиплексингом
- `AlertService` — мониторинг алертов (inactive ноды, паттерны логов) с дедупликацией и cooldown
- `Metrics` — внутренние метрики (subprocess, streams, WebSocket connections)

**State** (`state/`):
- `StatePersister` — сохраняет состояние нод в `data/{server_id}.json`
- Отслеживает inactive ноды (были раньше, сейчас пропали)

**Routers** (`routers/`):
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

**Key Models** (`models.py`):
- `NodeType`: LIFECYCLE | REGULAR | UNKNOWN
- `NodeStatus`: ACTIVE | INACTIVE
- `LifecycleState`: UNCONFIGURED | INACTIVE | ACTIVE | FINALIZED
- `TopicGroup`, `TopicGroupsConfig` — конфигурация групп топиков

### Frontend (`web/src/`)

React 18 + Vite + TailwindCSS. Структура VS Code-style: Activity Bar слева, секции переключаются по клику.

**Секции (Activity Bar)**:
- **Nodes** — дерево нод по namespace, детали, параметры, lifecycle, логи
- **Diagnostics** — dashboard-сетка диагностик с карточками и виджетами CPU/GPU/RAM
- **Topics** — два режима: Groups (конфигурированные группы с Hz) и Tree (все топики деревом с echo, Hz, info, фильтрацией полей)
- **Logs** — unified log stream со всех нод, фильтрация по уровню и ноде
- **App Stats** — внутренние метрики приложения (CPU, RSS, connections)

**Components** (`components/`):
- `ActivityBar` — навигация секций
- `NodeTree`, `NodeDetailPanel` — дерево нод и детали
- `Diagnostics` — dashboard диагностик
- `Topics`, `TopicTree` — два вида топиков
- `UnifiedLogs`, `LogPanel` — логи
- `AppStats` — системные метрики
- `ServerSelector` — выбор сервера
- `ConfirmModal`, `ContextMenu`, `Resizer`, `StatusBar`, `ToastContainer` — UI утилиты

**Hooks** (`hooks/`):
- `useNodes`, `useServer` — ноды и сервер
- `useDiagnostics` — диагностики
- `useTopicGroups`, `useTopicEcho` — топики
- `useUnifiedLogs` — unified логи
- `useAlerts` — алерты
- `useSystemStats` — метрики
- `useNotifications` — toast-уведомления

**Services** (`services/`):
- `api.js` — REST API клиент
- `websocket.js` — WebSocket фабрики для каждого типа стрима

## Configuration

**`config/servers.yaml`** — список серверов (Docker контейнеры):
```yaml
servers:
  - id: local
    name: "Local Docker"
    type: local           # или "ssh"
    container: your_container_name
    # Для SSH: host, user, port, ssh_key или password
```

**`config/topic_groups.yaml`** — группы топиков для мониторинга Hz и echo:
```yaml
topic_groups:
  - id: lidar_raw
    name: "LiDAR Raw"
    topics:
      - /sensing/lidar/top/packets
```

**`config/alerts.yaml`** — правила алертов (inactive ноды, паттерны логов).

Первый сервер в списке подключается автоматически. Состояние нод сохраняется в `data/{server_id}.json`.

## ROS2 Environment

Подключение к ROS2 внутри Docker:
- Sources `/opt/ros/humble/setup.bash`
- Читает `ROS_DOMAIN_ID` из `$HOME/tram.autoware/.ros_domain_id`
- `ROS_LOCALHOST_ONLY=1`, `RMW_IMPLEMENTATION=rmw_cyclonedds_cpp`
- Технические ноды (transform_listener, ros2cli, daemon, launch_ros) отфильтрованы из отображения
