# Plan: ROS2 Monitoring Agent

Замена docker exec на ROS2 ноду внутри контейнера с WebSocket API.

## Статус: IN PROGRESS

---

## Фаза 0: Протокол и инфраструктура

### 0.1 [x] JSON-RPC протокол — спецификация
- Файл: `docs/agent_protocol.md`
- Команды request/response: graph.nodes, graph.node_info, graph.topics, graph.topic_info, graph.services, graph.services_typed, graph.interface_show, lifecycle.get_state, lifecycle.set_state, params.dump, params.set, service.call, process.kill
- Подписки (subscribe/unsubscribe): topic.echo, topic.hz, logs (rosout), diagnostics
- Форматы сообщений, коды ошибок, heartbeat/ping

### 0.2 [x] Конфигурация серверов — добавить тип "agent"
- Файл: `config/servers.yaml` — новый тип сервера `type: agent` с полем `agent_url`
- Файл: `server/models.py` — обновить модели если нужно

---

## Фаза 1: Monitoring Agent (ROS2 нода)

### 1.1 [ ] Скелет ROS2 пакета
- Путь: `/home/ulitka/tram.autoware/src/system/monitoring_agent/`
- Файлы: `package.xml`, `setup.py`, `setup.cfg`, `resource/monitoring_agent`
- Entry point: `monitoring_agent = monitoring_agent.main:main`
- Зависимости: rclpy, std_msgs, diagnostic_msgs, lifecycle_msgs, rcl_interfaces, websockets (pip)

### 1.2 [ ] Core: Нода + WebSocket сервер
- `monitoring_agent/main.py` — точка входа, инициализация rclpy + asyncio event loop
- `monitoring_agent/node.py` — класс MonitoringAgentNode(Node)
- `monitoring_agent/ws_server.py` — WebSocket сервер (asyncio + websockets), JSON-RPC dispatch
- `monitoring_agent/protocol.py` — определения команд, сериализация, валидация
- Порт настраивается через ROS2 параметр `ws_port` (default: 9090)

### 1.3 [ ] Модуль Graph Introspection
- `monitoring_agent/handlers/graph.py`
- `graph.nodes` — get_node_names_and_namespaces() + фильтрация технических нод
- `graph.node_info` — get_publishers_info_by_topic/get_subscribers_info_by_topic + get_service_names_and_types
- `graph.topics` — get_topic_names_and_types()
- `graph.topic_info` — publishers/subscribers для конкретного топика
- `graph.services` — get_service_names_and_types()
- `graph.services_typed` — то же с типами
- `graph.interface_show` — rosidl_runtime_py для получения определения интерфейса

### 1.4 [ ] Модуль Topic Streaming (echo + hz)
- `monitoring_agent/handlers/topics.py`
- `topic.subscribe` — динамическая подписка, пересылка сообщений через WS
- `topic.unsubscribe` — отписка, удаление подписки если нет клиентов
- `topic.hz` — подсчёт Hz на основе timestamps (кольцевой буфер)
- Мультиплексирование: одна ROS2 подписка → много WS клиентов
- Сериализация ROS2 сообщений в JSON (message_to_ordereddict)
- Ограничение размера сообщений (10KB)

### 1.5 [ ] Модуль Lifecycle
- `monitoring_agent/handlers/lifecycle.py`
- `lifecycle.get_state` — service client к /{node}/get_state
- `lifecycle.set_state` — service client к /{node}/change_state
- Кеш сервисов для определения lifecycle нод (is_lifecycle_node)

### 1.6 [ ] Модуль Parameters
- `monitoring_agent/handlers/params.py`
- `params.dump` — list_parameters + get_parameters через стандартные сервисы
- `params.set` — set_parameters (будущее, но заложить интерфейс)

### 1.7 [ ] Модуль Service Caller
- `monitoring_agent/handlers/services.py`
- `service.call` — динамическое создание клиента, вызов, возврат результата
- Требует динамический импорт типов сообщений

### 1.8 [ ] Модуль Process Management
- `monitoring_agent/handlers/process.py`
- `process.kill` — os.kill или subprocess для управления процессами
- Только внутри контейнера, без docker exec

### 1.9 [ ] Модуль Logs (rosout)
- `monitoring_agent/handlers/logs.py`
- Постоянная подписка на /rosout
- Кольцевой буфер последних N сообщений
- subscribe/unsubscribe для клиентов с фильтрацией по ноде/уровню

### 1.10 [ ] Модуль Diagnostics
- `monitoring_agent/handlers/diagnostics.py`
- Подписка на /diagnostics, /display/mrm_status и др.
- Парсинг DiagnosticArray в JSON

---

## Фаза 2: Backend Adapter (ros2_node_manager)

### 2.1 [ ] AgentConnection — WebSocket клиент
- `server/connection/agent.py` — класс AgentConnection(BaseConnection)
- WebSocket клиент (websockets библиотека)
- Реализация всех методов BaseConnection через agent protocol
- Auto-reconnect при потере соединения

### 2.2 [ ] Обновление Connection Factory
- `server/connection/__init__.py` — добавить AgentConnection в экспорт
- `server/routers/servers.py` — создание AgentConnection при type="agent"
- `config/servers.yaml` — пример конфигурации agent

### 2.3 [ ] Адаптация сервисов под agent streaming
- Обновить LogCollector для работы через agent subscriptions
- Обновить DiagnosticsCollector
- Обновить TopicHzMonitor
- Обновить topic_echo_streamer
- Все должны работать и через docker exec, и через agent

---

## Фаза 3: Интеграция и деплой

### 3.1 [ ] Launch file для monitoring_agent
- `monitoring_agent/launch/monitoring_agent.launch.py`
- Интеграция в autoware launch (опционально)

### 3.2 [ ] Docker port exposure
- Документация по пробросу порта 9090
- Обновление deploy скриптов если нужно

### 3.3 [ ] End-to-end тестирование
- Проверка всех команд через agent
- Сравнение с docker exec режимом
- Проверка reconnect при перезапуске agent

---

## Порядок выполнения

1. Фаза 0 (протокол) — блокирует всё остальное
2. Фаза 1.1-1.2 (скелет + core) — фундамент agent
3. Фаза 1.3 (graph) + Фаза 2.1 (AgentConnection) — параллельно
4. Фаза 1.4-1.10 (остальные модули agent) — последовательно
5. Фаза 2.2-2.3 (интеграция backend) — после agent модулей
6. Фаза 3 (деплой) — финальная фаза
