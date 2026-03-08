# TODO — Активные задачи

> Обновляется в начале каждой сессии. Содержит только то, что делается сейчас.

## Оптимизация agent mode — ЗАВЕРШЕНО

### Backend — subscribe_json + прямой JSON путь
- [x] `AgentConnection.subscribe_json()` — прямой JSON streaming без YAML round-trip
- [x] LogCollector: `_collect_loop_json()` → `subscribe_json('logs')` → `_parse_json_log(dict)` → LogMessage
- [x] Diagnostics: `stream_diagnostics_json()`, `stream_mrm_status_json()`, `stream_mrm_state_json()`, `stream_bool_topic_json()`
- [x] WebSocket `/ws/diagnostics` — автоматически выбирает JSON/YAML путь по типу соединения
- [x] Удалены `_log_event_to_yaml`, `_diag_event_to_yaml`, ветки exec_stream для logs/diagnostics/echo

### Backend — SharedEchoMonitor
- [x] `SharedEchoMonitor` — один поток на топик, fan-out всем клиентам через ref-counting
- [x] Agent mode: `subscribe_json('topic.echo')` → JSON dict
- [x] Docker mode: `exec_stream` → YAML text (fallback)
- [x] WebSocket `/ws/topics/echo/{group_id}` и `/ws/topics/echo-single/{topic}` — через SharedEchoMonitor
- [x] Truncation: сообщения >10KB обрезаются

### Backend — DroppableQueue + уведомления
- [x] `DroppableQueue` — обёртка asyncio.Queue, считает дропы при QueueFull
- [x] Echo endpoints: `{"type": "dropped", "count": N}` перед следующим сообщением
- [x] Log endpoints: аналогично
- [x] AgentConnection._reader_loop: DroppableQueue вместо asyncio.Queue

### Backend/Agent — приоритизация WebSocket трафика
- [x] Backend: channel-dependent queue sizes (`logs=2000, diagnostics=1000, echo=200, hz=100`)
- [x] Agent: per-client `_ClientWriter` с `PriorityQueue` (logs/diag=0, hz=1, echo=2)
- [x] Документация: секция "Event Priority" в `docs/agent_protocol.md`

### Frontend
- [x] `JsonView` компонент — structured JSON view (ключи синие, числа зелёные, строки оранжевые)
- [x] Topics.jsx EchoPanel — рендерит JsonView для `format=json`, fallback на `<pre>` для YAML
- [x] TopicTree.jsx — JsonView + filterJsonFields для echo одиночных топиков

### Code Review исправления
- [x] `asyncio.get_event_loop()` → `asyncio.get_running_loop()` (Python 3.10+ deprecation)
- [x] DroppableQueue import через TYPE_CHECKING + lazy import в _subscribe
- [x] Diagnostics WS — sentinel task для обнаружения disconnect клиента
- [x] `assert isinstance` → explicit TypeError check в продакшн-коде
- [x] JsonView — убрана дублированная ternary ветка
- [x] Убран излишний asyncio.Lock в diagnostics endpoint

## Остаётся

### Тестирование
- [ ] Нагрузочный тест: несколько клиентов × несколько топиков через agent
- [ ] Рассмотреть разделение на несколько WS-соединений (control vs data) — опционально
