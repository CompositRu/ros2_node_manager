# TODO — Активные задачи

> Обновляется в начале каждой сессии. Содержит только то, что делается сейчас.

## Масштабируемость при множестве клиентов — DONE

Детальный план: `workflow/PLAN_SCALABILITY.md`

### Фаза 1: Shared Diagnostics — DONE
- [x] 1.1 Создать `SharedDiagnosticsCollector` (по аналогии с SharedEchoMonitor)
- [x] 1.2 Рефакторинг endpoint `/ws/diagnostics` — через shared queue
- [x] 1.3 Инициализация в `app_state` (start/stop)

### Фаза 2: Shared Node Status — DONE
- [x] 2.1 Создать `SharedNodeStatusBroadcaster`
- [x] 2.2 Рефакторинг endpoint `/ws/nodes/status`
- [x] 2.3 Обработка disconnect-а сервера в broadcaster

### Фаза 3: Shared Hz-Single — DONE
- [x] 3.1 Расширить `TopicHzMonitor` для single-topic subscribe
- [x] 3.2 Рефакторинг endpoint `/ws/topics/hz-single/{topic}`

### Фаза 4: Agent Reconnect — быстрое восстановление — DONE
- [x] 4.1 Sentinel-значение в очереди при разрыве
- [x] 4.2 `_disconnect_event` для мгновенного уведомления `subscribe_json()`

### Фаза 5: Оптимизация broadcast-путей — DONE
- [x] 5.1 Убрать лишний `json.dumps` в `_maybe_truncate`
- [x] 5.2 O(1) lookup в `LogCollector._dispatch`

### Фаза 6: Frontend reconnect — DONE
- [x] 6.1 Утилита `createReconnectingSocket` с exp backoff + jitter
- [x] 6.2 Применить ко всем WS-хукам

### Code Review фиксы
- [x] Deadlock в SharedNodeStatusBroadcaster (fire-and-forget disconnect_callback)
- [x] Sentinel None во всех stop() методах (LogCollector, SharedEchoMonitor, SharedDiagnostics, TopicHzMonitor)
- [x] Sentinel check (`if msg is None: break`) во всех WS endpoint loops
- [x] `list(subscribers)` в _broadcast для защиты от RuntimeError
- [x] Исправлена эвристика truncate (str() вместо sys.getsizeof)
- [x] None-safe cleanup в finally блоках
- [x] Голые `except:` → `except Exception:`
