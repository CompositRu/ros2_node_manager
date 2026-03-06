# TODO — Активные задачи

> Обновляется в начале каждой сессии. Содержит только то, что делается сейчас.

## Оптимизация agent mode — убрать YAML слой, улучшить масштабируемость

### Backend — echo
- [ ] `AgentConnection.exec_stream` для `topic.echo` — отдавать dict/JSON вместо YAML строк
- [ ] Новый WebSocket режим в `websocket.py` — отправлять echo как JSON (не текст)
- [ ] Shared echo: один поток на топик с fan-out всем подписчикам (по аналогии с `TopicHzMonitor`)
- [ ] Уведомление клиента при дропе сообщений (`QueueFull` → послать `{"type": "dropped", "count": N}`)

### Backend — убрать JSON→YAML→parse round-trip (agent mode)
- [ ] LogCollector: прямой JSON путь — агент шлёт dict, LogCollector создаёт LogMessage напрямую (без `_log_event_to_yaml` → regex)
- [ ] Diagnostics: прямой JSON путь — агент шлёт dict, парсим напрямую (без `_diag_event_to_yaml` → YAML парсинг)

### Frontend
- [ ] `useTopicEcho` — принимать JSON объекты вместо YAML текста
- [ ] Компонент отображения echo — structured JSON view вместо plain text
- [ ] Поддержка уведомлений о дропнутых сообщениях в UI

### Backend/Agent — приоритизация WebSocket трафика
- [ ] Приоритизация каналов: logs/diagnostics отправляются первыми, echo — после (один WS = bottleneck при высокочастотных echo)
- [ ] Рассмотреть разделение на несколько WS-соединений по типу трафика (control vs data)

### Тестирование
- [ ] Нагрузочный тест: несколько клиентов × несколько топиков через agent
