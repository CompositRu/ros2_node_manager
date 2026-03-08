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

## Текущая фаза

**Оптимизация agent mode — убрать YAML backward-compat слой, улучшить масштабируемость**

### Проблема 1: Echo — бессмысленная JSON→YAML конверсия × N клиентов
При N пользователях backend делает N одинаковых JSON→YAML конверсий каждого
сообщения в `AgentConnection._json_to_yaml_lines()`. YAML нужен только для совместимости
с docker exec режимом. В agent mode данные уже приходят как JSON.

Решение: пробрасывать JSON напрямую до фронтенда, минуя YAML слой.

### Проблема 2: LogCollector — JSON→YAML→regex round-trip
Агент шлёт JSON → `_log_event_to_yaml()` генерирует YAML строки →
LogCollector парсит YAML regex'ом обратно в LogMessage. Три конверсии вместо одной.

Решение: в agent mode LogCollector получает dict напрямую и создаёт LogMessage без YAML.

### Проблема 3: Diagnostics — JSON→YAML→парсинг round-trip
`stream_diagnostics` → `exec_stream("ros2 topic echo /diagnostics")` →
`_diag_event_to_yaml()` → парсинг YAML обратно в структуры. Та же двойная конверсия.

Решение: в agent mode diagnostics сервис получает dict напрямую.

### Проблема 4: Один WebSocket между backend и agent — нет приоритизации
Весь трафик (echo, hz, logs, diagnostics) идёт через один WS. Поток echo от
высокочастотных топиков (30+ Hz) задерживает доставку логов и диагностики.
Это не про CPU, а про latency при большом количестве подписок.

Решение: приоритизация сообщений на стороне агента (критичные каналы — logs,
diagnostics — отправляются первыми), либо разделение на несколько WS-соединений
по типу трафика (control/data).

### Задачи
1. Backend: `exec_stream` для echo — отдавать dict/JSON вместо YAML строк
2. Backend: WebSocket endpoint — отправлять echo как JSON (не текст)
3. Backend: shared echo — fan-out всем подписчикам одного топика
4. Backend: LogCollector — прямой JSON путь (без `_log_event_to_yaml` → regex)
5. Backend: Diagnostics — прямой JSON путь (без `_diag_event_to_yaml` → парсинг)
6. Backend: уведомление клиента при дропе сообщений (QueueFull)
7. Backend/Agent: приоритизация каналов на WS (logs/diag > echo)
8. Frontend: `useTopicEcho` — принимать JSON, structured view
9. Frontend: поддержка уведомлений о дропнутых сообщениях
10. Тестирование под нагрузкой: несколько клиентов × несколько топиков


## Будущие работы

**v0.8 — Только agent mode: удаление docker exec / SSH режимов**
- Удалить `LocalConnection`, `SSHConnection` — оставить только `AgentConnection`
- Удалить `BaseConnection` абстракцию и `exec_stream`/`exec_command` интерфейс
- Удалить `server/connection/local.py`, `server/connection/ssh.py`, `server/connection/base.py`
- В `config/servers.yaml`, оставить только `agent_url: "ws://localhost:9090"`. Переименовать в `config.yaml`
- Удалить YAML backward-compat слой (`_json_to_yaml_lines`, `_log_event_to_yaml`, `_diag_event_to_yaml`)
- Удалить `topic_echo_streamer.py` (YAML-based per-client echo) — заменить на прямой JSON pipeline
- Убрать SSH-зависимости (`asyncssh`) из `requirements.txt`
- Сервисы (LogCollector, diagnostics, echo) работают напрямую с agent API, без трансляции CLI-команд

**v0.9 — Визуализация графа**
- Граф связей между нодами (как rqt_graph)
- Интерактивный граф (zoom, pan, select)
- Фильтрация по namespace

## Будущие фазы

- **v0.10** — Улучшения управления нодами (lifecycle FSM, групповые операции, param set)
- **v1.0** — Production Ready (Docker образ, CI/CD, auth, HTTPS, тесты)
- **Future** — Fleet Radar интеграция, плагины, rosbag, мобильная версия