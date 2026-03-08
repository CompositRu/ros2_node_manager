# MRM State — /api/fail_safe/mrm_state

## Топик

- **Путь**: `/api/fail_safe/mrm_state`
- **Тип**: `autoware_adapi_v1_msgs::msg::MrmState`
- **Источник**: emergency handler (система аварийного управления Autoware)
- **Частота**: редкие сообщения, публикуется при изменении состояния

## Поля сообщения

### state (uint8)
| Значение | Константа | Описание |
|----------|-----------|----------|
| 1 | NORMAL | Штатная работа |
| 2 | MRM_OPERATING | MRM активирован, выполняется экстренная остановка |
| 3 | MRM_SUCCEEDED | Остановка завершена успешно |
| 4 | MRM_FAILED | Остановка не удалась (критическая ситуация) |

### behavior (uint8)
| Значение | Константа | Описание |
|----------|-----------|----------|
| 1 | NONE | Нет активного поведения |
| 2 | EMERGENCY_STOP | Экстренная остановка |
| 3 | COMFORTABLE_STOP | Плавная остановка |

## Архитектура

### Monitoring Agent (внутри Docker)

**Файл**: `~/tram.autoware/src/system/monitoring_agent/monitoring_agent/handlers/mrm.py`

`MrmManager` — always-on подписка на топик с буферизацией:
- Подписывается на `/api/fail_safe/mrm_state` при старте агента
- Хранит `_last_message` — последнее полученное сообщение
- При новой WebSocket-подписке (канал `mrm_state`) сразу отдаёт закэшированное значение
- Продолжает стримить обновления через fan-out

Зарегистрирован в `main.py`: роутинг канала `mrm_state` → `mrm_manager.on_subscribe/on_unsubscribe`.

### Backend (ros2_node_manager)

#### Потоковая подписка (WebSocket /ws/diagnostics)

**Файл**: `server/services/diagnostics_collector.py` → `stream_mrm_state()`

- Подписывается через `connection.exec_stream("ros2 topic echo /api/fail_safe/mrm_state")`
- Парсит YAML-вывод: извлекает `state` и `behavior`
- Маппинг state → diagnostic level: NORMAL=OK(0), MRM_OPERATING=WARN(1), MRM_SUCCEEDED=OK(0), MRM_FAILED=ERROR(2)
- Behavior передаётся как key-value pair в DiagnosticItem
- Yield'ит `DiagnosticItem(name="mrm_state", ...)`

Добавлена как задача `run_with_retry("mrm_state", ...)` в `server/routers/websocket.py` → `diagnostics_websocket`.

#### Одноразовое чтение (REST /api/dashboard)

**Файл**: `server/routers/dashboard.py` → `_get_mrm_state()`

- `ros2 topic echo /api/fail_safe/mrm_state --once` (timeout 3s)
- Возвращает `{state, behavior, state_label, behavior_label}`
- Включён в `asyncio.gather` параллельно с другими dashboard-запросами

#### AgentConnection маршрутизация

**Файл**: `server/connection/agent.py`

- `_parse_stream_command`: `/api/fail_safe/mrm_state` → канал `mrm_state` (вместо generic `topic.echo`)
- `exec_command` (--once): аналогичная маршрутизация для одноразового чтения
- `exec_stream`: формат `mrm_state` → JSON-to-YAML конвертация (как `topic.echo`)

### Frontend

#### Dashboard (`web/src/components/Dashboard.jsx`)

`MrmStateCard` — плашка справа от скорости:
- Данные из `/api/dashboard` REST (поле `mrm_state`), polling 5s
- Цвета: NORMAL — зелёный, все остальные — красный
- При не-NORMAL состоянии точка пульсирует
- Показывает behavior когда он не NONE

#### Diagnostics (`web/src/components/Diagnostics.jsx`)

`MrmStateCard` — карточка закреплена в самом верху списка (перед localization и другими pinned):
- Данные из WebSocket `/ws/diagnostics` (real-time)
- Занимает 2 колонки (col-span-2)
- Показывает: "Маневр минимального риска: {состояние}" + behaviour

## Отличие от /display/mrm_status

Существует также старый топик `/display/mrm_status` с другим форматом (значения 0-4, без behaviour).
Он обрабатывается отдельно через `stream_mrm_status()` и отображается как `MrmCard` в pinned-секции diagnostics.
