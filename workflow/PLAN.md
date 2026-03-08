# Plan — Текущие фазы работы

## Завершённые фазы

| Версия | Название | Статус |
|--------|----------|--------|
| v0.1 | MVP: Docker, SSH, ноды, параметры, логи, lifecycle | Done |
| v0.2 | Activity Bar + App Stats + Unified Logs | Done |
| v0.3 | Diagnostics dashboard | Done |
| v0.5 | Topics (Groups + Tree, Hz, Echo) | Done |
| v0.6 | Log History + Alert History (SQLite) | Done |
| v0.7 | Services + Actions | Done |

### Monitoring Agent (отдельный трек)
| Фаза | Название | Статус |
|-------|----------|--------|
| 0 | Протокол JSON-RPC + тип сервера "agent" | Done |
| 1 | ROS2 нода monitoring_agent (все 10 модулей) | Done |
| 2 | Backend AgentConnection (WebSocket клиент) | Done |
| 3 | Интеграция и деплой | Partial (launch done, E2E testing remaining) |
| 4 | E2E Test Fixes | Done |
| 5 | Оптимизация agent mode — JSON streaming, shared echo, приоритизация | Done |

## Текущая фаза

**Нагрузочное тестирование + финальная полировка**

Все основные задачи оптимизации agent mode реализованы:
- subscribe_json() — прямой JSON streaming без YAML round-trip
- SharedEchoMonitor — один поток на топик, fan-out всем клиентам
- DroppableQueue — отслеживание дропнутых сообщений с уведомлением клиента
- PriorityQueue в agent — критичные каналы (logs/diag) доставляются раньше echo
- Frontend JsonView — structured JSON отображение echo

Осталось:
1. Нагрузочное тестирование (несколько клиентов × несколько топиков)
2. Рассмотреть разделение на несколько WS-соединений (control vs data) — опционально

## Будущие работы

**v0.8 — Только agent mode: удаление docker exec / SSH режимов**
- Удалить `LocalConnection`, `SSHConnection` — оставить только `AgentConnection`
- Удалить `BaseConnection` абстракцию и `exec_stream`/`exec_command` интерфейс
- Удалить `server/connection/local.py`, `server/connection/ssh.py`, `server/connection/base.py`
- В `config/servers.yaml`, оставить только `agent_url: "ws://localhost:9090"`. Переименовать в `config.yaml`
- Удалить `_json_to_yaml_lines`, `_list_to_yaml_lines` (останутся не нужны)
- Удалить `topic_echo_streamer.py` (заменён на SharedEchoMonitor)
- Убрать SSH-зависимости (`asyncssh`) из `requirements.txt`

**v0.9 — Визуализация графа**
- Граф связей между нодами (как rqt_graph)
- Интерактивный граф (zoom, pan, select)
- Фильтрация по namespace

## Будущие фазы

- **v0.10** — Улучшения управления нодами (lifecycle FSM, групповые операции, param set)
- **v1.0** — Production Ready (Docker образ, CI/CD, auth, HTTPS, тесты)
- **Future** — Fleet Radar интеграция, плагины, rosbag, мобильная версия
