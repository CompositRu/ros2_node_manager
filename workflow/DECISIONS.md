# Decisions — Архитектурные решения

> Каждое решение: что выбрали, почему, что отклонили.

---

### D1: Monitoring Agent вместо docker exec

**Решение:** Создать ROS2 ноду (monitoring_agent) с WebSocket API внутри контейнера.

**Почему:** docker exec + ROS2 CLI даёт 200-500ms latency на каждый запрос (spawn процесса + source setup.bash + CLI парсинг). Agent через прямой ROS2 API — 1-20ms.

**Отклонено:**
- REST API внутри контейнера — нет нативной поддержки стриминга (логи, hz, echo)
- gRPC — избыточная сложность, не нужна schema-валидация для внутреннего протокола
- rosbridge_suite — слишком тяжёлый, много лишнего

**Доказательства:** `docs/benchmarks.md`

---

### D2: JSON-RPC 2.0 как протокол agent

**Решение:** WebSocket + JSON-RPC 2.0 с расширениями для подписок.

**Почему:** Стандартный протокол, поддержка request/response и подписок через один канал, простая реализация на Python (websockets).

**Отклонено:**
- Кастомный бинарный протокол — сложнее отлаживать
- MQTT — лишний брокер, усложнение деплоя

---

### D3: docker exec как fallback

**Решение:** Сохранить LocalDockerConnection и SSHDockerConnection наряду с AgentConnection.

**Почему:** Agent может быть недоступен (старая версия контейнера, ещё не задеплоен). docker exec работает везде где есть Docker.

---

### D4: VS Code-style Activity Bar UI

**Решение:** Вертикальная иконочная полоса слева, каждая секция — отдельный view.

**Почему:** Привычный паттерн для разработчиков, эффективное использование пространства, масштабируется на новые секции.

**Отклонено:**
- Табы сверху — не масштабируются при 6+ секциях
- Sidebar с деревом — занимает слишком много места

---

### D5: SQLite для истории логов/алертов

**Решение:** aiosqlite, файл `data/history_{server_id}.db`.

**Почему:** Zero-config, работает на любой машине, достаточно для одного трамвая. Retention: 50k логов / 10k алертов.

**Отклонено:**
- PostgreSQL — требует отдельный сервис, избыточно для одного инстанса
- Файловые логи — нет индексов, медленный поиск

---

### D7: subscribe_json() вместо exec_stream для agent mode

**Решение:** Добавить `AgentConnection.subscribe_json()` — прямой JSON streaming. Сервисы (LogCollector, DiagnosticsCollector, SharedEchoMonitor) используют его напрямую, минуя exec_stream и YAML round-trip.

**Почему:** exec_stream конвертировал JSON от агента в YAML строки для совместимости с docker exec парсерами. В agent mode это бессмысленная тройная конверсия: JSON→YAML→parse→struct. subscribe_json() отдаёт dict напрямую.

**Отклонено:**
- Модифицировать exec_stream для возврата JSON — ломает BaseConnection интерфейс
- Добавить флаг format="json" в exec_stream — усложняет абстракцию, не даёт type safety

---

### D8: SharedEchoMonitor вместо per-client echo

**Решение:** Один поток на топик с fan-out всем подписчикам через ref-counting. Аналогично TopicHzMonitor.

**Почему:** Per-client echo (topic_echo_streamer) создавал N×M подписок (N клиентов × M топиков). SharedEchoMonitor — M подписок независимо от N клиентов.

**Отклонено:**
- Оставить per-client — не масштабируется
- Полный кеш как в TopicHzMonitor — echo это поток данных, не snapshot

---

### D9: DroppableQueue для отслеживания потерь

**Решение:** Обёртка asyncio.Queue, считающая дропнутые сообщения. При следующей успешной доставке клиент получает `{"type": "dropped", "count": N}`.

**Почему:** Молчаливые дропы при QueueFull не дают клиенту информации о потерях. DroppableQueue делает потери видимыми без усложнения протокола.

---

### D10: Приоритизация каналов на WebSocket агента

**Решение:** PriorityQueue в _ClientWriter агента. Уровни: logs/diagnostics=0, hz=1, echo=2. Backend: разные размеры очередей по каналам.

**Почему:** Один WebSocket — bottleneck. Высокочастотный echo (30+ Hz) задерживает критичные logs/diagnostics. Приоритизация гарантирует доставку критичных данных первыми.

**Отклонено:**
- Несколько WS-соединений — усложнение, можно рассмотреть позже
- Rate limiting echo — теряем данные без выбора

---

### D6: Два проекта вместо монорепо

**Решение:** ros2_node_manager (веб-интерфейс) отдельно от tram.autoware (ROS2 стек).

**Почему:** Разные lifecycle: веб-интерфейс обновляется независимо от ROS2 стека. Разные инструменты сборки (pip/npm vs colcon). Monitoring agent — часть ROS2 стека, потому что ему нужен прямой доступ к rclpy.

---

### D11: Shared-сервисы для всех streaming endpoints

**Решение:** Единый shared-сервис для каждого типа данных (diagnostics, node status, hz, echo, logs). Один фоновый процесс на канал, per-client DroppableQueue с sentinel-based cleanup.

**Почему:** Per-client подписки не масштабируются: 10 клиентов `/ws/diagnostics` создавали 40 подписок на агент + 50 tasks. Аналогично для node status (N polling loops) и hz-single (N подписок на один топик).

**Паттерн:** SharedEchoMonitor (уже был) → применён к diagnostics, node status, hz-single.

**Ключевые детали:**
- Все stop() методы рассылают sentinel (None) в subscriber-очереди
- Все WS endpoint loops проверяют `if msg is None: break`
- _broadcast итерирует по `list(subscribers)` для защиты от RuntimeError
- SharedNodeStatusBroadcaster: disconnect_callback через `asyncio.create_task` (fire-and-forget) чтобы избежать deadlock

**Отклонено:**
- Мультиплексирование в один WS — слишком сложно, не нужно при <100 клиентах

---

### D12: Disconnect event + sentinel для быстрого восстановления agent connection

**Решение:** `asyncio.Event` (`_disconnect_event`) + sentinel None в очередях при обрыве WebSocket к агенту. `subscribe_json()` и `exec_stream()` используют `asyncio.wait()` с disconnect_task для мгновенного выхода.

**Почему:** При обрыве все итераторы `subscribe_json()` ждали 60 секунд до timeout. Теперь — мгновенное уведомление через event, retry через 1-5 секунд.

**Отклонено:**
- Polling `self._connected` чаще — лишние wake-ups, не решает проблему полностью

---

### D13: Frontend WebSocket reconnect с exponential backoff + jitter

**Решение:** Утилита `createReconnectingSocket` — обёртка над WebSocket с auto-reconnect. Backoff: 1s → 2s → 4s → 8s → 16s (max), jitter ±30%. Max 20 retries. Применена ко всем 8 WebSocket-фабрикам.

**Почему:** Раньше reconnect был только в useAlerts (фиксированный 5s), остальные хуки не переподключались. При массовом обрыве — thundering herd (все клиенты в один момент).

**Отклонено:**
- Фиксированный delay — thundering herd
- Без reconnect — плохой UX, пользователь должен перезагружать страницу
