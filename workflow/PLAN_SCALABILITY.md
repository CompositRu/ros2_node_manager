# План: Масштабируемость при множестве клиентов

> Детальный план работ по устранению узких мест, выявленных при анализе кода.
> Приоритет: от самых критичных (дублирование подписок) к оптимизациям.

---

## Фаза 1: Shared Diagnostics (устранение дублирования подписок)

**Проблема:** Каждый клиент `/ws/diagnostics` создаёт 4 независимые `subscribe_json()` подписки на агент. 10 клиентов = 40 подписок + 50 asyncio tasks. Logs и Echo уже решили эту проблему через shared-слой — diagnostics нет.

**Файлы:**
- `server/services/diagnostics_collector.py` — текущие `stream_*_json()` функции (per-client)
- `server/routers/websocket.py:97-201` — `/ws/diagnostics` endpoint
- `server/services/shared_echo_monitor.py` — образец для реализации

**Задачи:**

### 1.1 Создать SharedDiagnosticsCollector
- Новый класс по аналогии с `SharedEchoMonitor`
- Один фоновый поток на каждый канал: `diagnostics`, `topic.echo` (mrm_status, lidar_sync_flag), `mrm_state`
- `subscribe(queue)` / `unsubscribe(queue)` с ref-counting
- Broadcast через `DroppableQueue` per-client (maxsize=500)
- Парсинг `DiagnosticItem` происходит один раз в shared-задаче, а не per-client
- Retry-логика внутри shared-задачи (текущая `run_with_retry` из websocket.py)

### 1.2 Рефакторинг endpoint `/ws/diagnostics`
- Убрать создание 4 tasks per-client
- Вместо этого: `queue = DroppableQueue(500)` → `shared_diag.subscribe(queue)` → read loop → `unsubscribe`
- Sentinel task для disconnect-детекции оставить (1 task вместо 5)
- Cleanup в `finally`: `shared_diag.unsubscribe(queue)`

### 1.3 Инициализация
- Создавать `SharedDiagnosticsCollector` в `app_state` при подключении к серверу (рядом с `SharedEchoMonitor`)
- `start()` при connect, `stop()` при disconnect

**Результат:** 10 клиентов = 4 подписки на агент (вместо 40) + 4 shared tasks (вместо 50).

---

## Фаза 2: Shared Node Status (устранение per-client polling)

**Проблема:** Каждый клиент `/ws/nodes/status` запускает свой цикл, который каждые 5 секунд вызывает `refresh_nodes()`, строит dict, сериализует JSON и отправляет. Rate-limit в `NodeService` спасает от дублирования RPC, но JSON-сериализация и send — per-client.

**Файлы:**
- `server/routers/websocket.py:25-95` — `/ws/nodes/status` endpoint
- `server/services/node_service.py` — `refresh_nodes()` с rate-limiting

**Задачи:**

### 2.1 Создать SharedNodeStatusBroadcaster
- Один фоновый таск: каждые 5 секунд вызывает `refresh_nodes()`
- Готовит JSON-сообщение один раз
- Broadcast в per-client `DroppableQueue(maxsize=5)` (маленькая очередь — status обновляется редко)
- `subscribe(queue)` / `unsubscribe(queue)`

### 2.2 Рефакторинг endpoint `/ws/nodes/status`
- `queue = DroppableQueue(5)` → `shared_status.subscribe(queue)` → read loop → send → `unsubscribe`
- Обработку container_stopped/disconnect перенести в shared broadcaster (одна проверка вместо N)

### 2.3 Обработка disconnect-а сервера
- SharedNodeStatusBroadcaster должен отправить `{"type": "disconnected"}` всем подписчикам при потере соединения
- После этого — либо продолжать попытки, либо остановиться

**Результат:** 1 refresh + 1 JSON сериализация каждые 5 сек (вместо N). N send'ов остаются, но это неизбежно.

---

## Фаза 3: Shared Hz-Single (устранение per-client подписок)

**Проблема:** `/ws/topics/hz-single/{topic}` — каждый клиент вызывает `exec_stream()`, создающий отдельную `topic.hz` подписку на агенте. 5 клиентов на одном топике = 5 подписок.

**Файлы:**
- `server/routers/websocket.py:514-566` — `/ws/topics/hz-single/{topic}` endpoint
- `server/services/topic_hz_monitor.py` — уже имеет shared-кеш для групп

**Задачи:**

### 3.1 Расширить TopicHzMonitor для single-topic
- Добавить `subscribe_topic(topic, queue)` / `unsubscribe_topic(topic, queue)` с ref-counting
- Если топик уже мониторится (в составе группы) — переиспользовать значение
- Если нет — создать фоновую задачу (как `_monitor_topic`)
- Ref-counting: остановка при уходе последнего подписчика

### 3.2 Рефакторинг endpoint `/ws/topics/hz-single/{topic}`
- Вместо `exec_stream()` → `topic_hz_monitor.subscribe_topic(topic, queue)` → read loop → `unsubscribe_topic`
- Или проще: push-модель — TopicHzMonitor хранит per-topic subscribers и broadcast'ит Hz-значения

### 3.3 Альтернатива: polling из кеша
- Endpoint может просто поллить `topic_hz_monitor.get_hz(topic)` каждые 2 сек
- Проще в реализации, но добавляет задержку до 2 сек

**Результат:** 1 подписка на топик независимо от числа клиентов.

---

## Фаза 4: Agent Reconnect — быстрое восстановление

**Проблема:** При обрыве WebSocket к агенту `_subscription_queues.clear()` уничтожает все очереди. Все `subscribe_json()` итераторы ждут данных из мёртвых очередей до 60-секундного timeout. В течение этих 60 секунд все клиенты в тишине.

**Файлы:**
- `server/connection/agent.py:158-221` — `_reader_loop()` с reconnect
- `server/connection/agent.py:224-249` — `subscribe_json()` iterator

**Задачи:**

### 4.1 Sentinel-значение для уведомления о разрыве
- Перед `_subscription_queues.clear()` — поставить sentinel (например `None` или специальный объект `_DISCONNECTED`) в каждую очередь
- `subscribe_json()` проверяет sentinel → выбрасывает `ConnectionError` → сервис делает retry

### 4.2 asyncio.Event для глобального уведомления
- Добавить `self._disconnect_event = asyncio.Event()`
- При разрыве — `_disconnect_event.set()`
- `subscribe_json()` ждёт `asyncio.wait([queue.get(), disconnect_event.wait()], return_when=FIRST_COMPLETED)`
- При reconnect'е — `_disconnect_event.clear()`

### 4.3 Автоматический re-subscribe
- После reconnect'а shared-сервисы (LogCollector, SharedEchoMonitor, SharedDiagnosticsCollector) автоматически переподписываются
- Это уже частично работает через retry-loop в каждом сервисе, но 60-секундная задержка — проблема

**Результат:** Восстановление за 1-5 секунд (reconnect delay) вместо 60 секунд.

---

## Фаза 5: Оптимизация broadcast-путей

### 5.1 SharedEchoMonitor — убрать лишний json.dumps в truncate

**Проблема:** `_maybe_truncate()` вызывает `json.dumps()` на каждом сообщении для проверки размера. При 30 Hz топике — 30 лишних сериализаций в секунду.

**Файл:** `server/services/shared_echo_monitor.py:119-137`

**Решение:**
- Использовать `len(str(data))` как быструю эвристику (не точно, но достаточно для отсечки)
- Или: `json.dumps` только если `sys.getsizeof(data) > threshold / 2` (грубая оценка)
- Или: агент уже знает размер сообщения — передавать `_size` в event data

### 5.2 LogCollector._dispatch — оптимизация node matching

**Проблема:** Для каждого лога итерация по всем per-node подписчикам с `rsplit("/", 1)[-1]` на каждом сообщении.

**Файл:** `server/services/log_collector.py:229-240`

**Решение:**
- При `subscribe(node_name, queue)` — построить lookup dict:
  ```python
  self._short_name_map[short_name].add(queue)
  self._full_name_map[full_name].add(queue)
  ```
- В `_dispatch()`: два dict lookup O(1) вместо O(N) итерации

### 5.3 Batching сообщений перед WebSocket send

**Проблема:** Каждое сообщение — отдельный `websocket.send_json()`. При высокочастотных топиках это overhead на framing.

**Решение (опционально):**
- Буферизация: собирать сообщения за 50-100ms окно, отправлять массивом
- Применимо для echo и logs
- Требует поддержки на фронтенде (распаковка массивов)

**Приоритет:** Низкий. Делать только если I/O станет bottleneck по результатам нагрузочного теста.

---

## Фаза 6: Frontend — reconnect и connection management

### 6.1 Exponential backoff с jitter для reconnect

**Проблема:** `useAlerts.js` — единственный хук с reconnect, и тот с фиксированным 5s delay. Остальные хуки вообще не переподключаются. При массовом обрыве — thundering herd.

**Файлы:**
- `web/src/hooks/useAlerts.js` — фиксированный `WS_RECONNECT_DELAY = 5000`
- `web/src/hooks/useNodes.js`, `useDiagnostics.js`, `useTopicGroups.js` и др. — нет reconnect

**Решение:**
- Создать утилиту `createReconnectingSocket(url, handlers, options)`:
  ```javascript
  // Exponential backoff: 1s → 2s → 4s → 8s → 16s (max)
  // + random jitter ±30%
  const delay = Math.min(baseDelay * 2 ** attempt, maxDelay);
  const jitter = delay * (0.7 + Math.random() * 0.6);
  ```
- Применить ко всем WebSocket-хукам
- Max reconnect attempts (например 20), после чего показать ошибку

### 6.2 Мультиплексирование WebSocket (опционально, v1.0+)

**Проблема:** До 8 WebSocket на клиента. При 50 клиентах — 400 соединений.

**Решение (если потребуется):**
- Один WebSocket на клиента с мультиплексированием каналов
- Клиент отправляет: `{"subscribe": ["nodes", "logs", "diagnostics"]}`
- Сервер мультиплексирует: `{"channel": "logs", "data": {...}}`
- Требует переработки и frontend и backend

**Приоритет:** Низкий. 400 соединений для uvicorn — не проблема. Делать только при выходе на 100+ клиентов.

---

## Порядок реализации

| Порядок | Фаза | Эффект | Сложность | Оценка |
|---------|-------|--------|-----------|--------|
| 1 | Фаза 1: Shared Diagnostics | Высокий — убирает 10x подписок | Средняя | Есть образец (SharedEchoMonitor) |
| 2 | Фаза 2: Shared Node Status | Высокий — убирает N polling loops | Средняя | Простой broadcast |
| 3 | Фаза 4: Agent Reconnect | Высокий — 60s→5s восстановление | Средняя | Sentinel + event |
| 4 | Фаза 3: Shared Hz-Single | Средний — редко используется | Низкая | Расширение TopicHzMonitor |
| 5 | Фаза 5: Оптимизации broadcast | Низкий — микрооптимизации | Низкая | Точечные правки |
| 6 | Фаза 6: Frontend reconnect | Средний — UX при обрывах | Низкая | Утилита + применение |

---

## Метрики для проверки

После каждой фазы проверять через `/api/debug/stats`:
- Количество активных asyncio tasks
- Количество подписок в `_subscription_queues` агента
- Количество WebSocket-соединений по типам
- Использование памяти (RSS)
- CPU usage при N клиентах

Нагрузочный тест: открыть N вкладок браузера (5, 10, 20), каждая с diagnostics + logs + echo. Смотреть на:
- Задержку доставки сообщений
- Количество dropped-уведомлений
- CPU/RSS growth линейный vs сублинейный
