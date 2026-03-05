# Plan: ROS2 Monitoring Agent

Замена docker exec на ROS2 ноду внутри контейнера с WebSocket API.

## Статус: IN PROGRESS

---

## Фаза 0: Протокол и инфраструктура

### 0.1 [x] JSON-RPC протокол — спецификация (commit 0c6045f)
- Файл: `docs/agent_protocol.md`
- Команды request/response: graph.nodes, graph.node_info, graph.topics, graph.topic_info, graph.services, graph.services_typed, graph.interface_show, lifecycle.get_state, lifecycle.set_state, params.dump, params.set, service.call, process.kill
- Подписки (subscribe/unsubscribe): topic.echo, topic.hz, logs (rosout), diagnostics
- Форматы сообщений, коды ошибок, heartbeat/ping

### 0.2 [x] Конфигурация серверов — добавить тип "agent" (commit 0c6045f)
- Файл: `config/servers.yaml` — новый тип сервера `type: agent` с полем `agent_url`
- Файл: `server/models.py` — обновить модели если нужно

---

## Фаза 1: Monitoring Agent (ROS2 нода)

### 1.1 [x] Скелет ROS2 пакета (commit db3e643c0 in tram.autoware)
- Путь: `/home/ulitka/tram.autoware/src/system/monitoring_agent/`
- Файлы: `package.xml`, `setup.py`, `setup.cfg`, `resource/monitoring_agent`
- Entry point: `monitoring_agent = monitoring_agent.main:main`
- Зависимости: rclpy, std_msgs, diagnostic_msgs, lifecycle_msgs, rcl_interfaces, websockets (pip)

### 1.2 [x] Core: Нода + WebSocket сервер (commit db3e643c0 in tram.autoware)
- `monitoring_agent/main.py` — точка входа, инициализация rclpy + asyncio event loop
- `monitoring_agent/node.py` — класс MonitoringAgentNode(Node)
- `monitoring_agent/ws_server.py` — WebSocket сервер (asyncio + websockets), JSON-RPC dispatch
- `monitoring_agent/protocol.py` — определения команд, сериализация, валидация
- Порт настраивается через ROS2 параметр `ws_port` (default: 9090)

### 1.3 [x] Модуль Graph Introspection (commit db3e643c0 in tram.autoware)
- `monitoring_agent/handlers/graph.py`
- `graph.nodes` — get_node_names_and_namespaces() + фильтрация технических нод
- `graph.node_info` — get_publishers_info_by_topic/get_subscribers_info_by_topic + get_service_names_and_types
- `graph.topics` — get_topic_names_and_types()
- `graph.topic_info` — publishers/subscribers для конкретного топика
- `graph.services` — get_service_names_and_types()
- `graph.services_typed` — то же с типами
- `graph.interface_show` — rosidl_runtime_py для получения определения интерфейса

### 1.4 [x] Модуль Topic Streaming (echo + hz) (commit db3e643c0 in tram.autoware)
- `monitoring_agent/handlers/topics.py`
- `topic.subscribe` — динамическая подписка, пересылка сообщений через WS
- `topic.unsubscribe` — отписка, удаление подписки если нет клиентов
- `topic.hz` — подсчёт Hz на основе timestamps (кольцевой буфер)
- Мультиплексирование: одна ROS2 подписка → много WS клиентов
- Сериализация ROS2 сообщений в JSON (message_to_ordereddict)
- Ограничение размера сообщений (10KB)

### 1.5 [x] Модуль Lifecycle (commit db3e643c0 in tram.autoware)
- `monitoring_agent/handlers/lifecycle.py`
- `lifecycle.get_state` — service client к /{node}/get_state
- `lifecycle.set_state` — service client к /{node}/change_state
- Кеш сервисов для определения lifecycle нод (is_lifecycle_node)

### 1.6 [x] Модуль Parameters (commit db3e643c0 in tram.autoware)
- `monitoring_agent/handlers/params.py`
- `params.dump` — list_parameters + get_parameters через стандартные сервисы
- `params.set` — set_parameters (будущее, но заложить интерфейс)

### 1.7 [x] Модуль Service Caller (commit db3e643c0 in tram.autoware)
- `monitoring_agent/handlers/services.py`
- `service.call` — динамическое создание клиента, вызов, возврат результата
- Требует динамический импорт типов сообщений

### 1.8 [x] Модуль Process Management (commit db3e643c0 in tram.autoware)
- `monitoring_agent/handlers/process.py`
- `process.kill` — os.kill или subprocess для управления процессами
- Только внутри контейнера, без docker exec

### 1.9 [x] Модуль Logs (rosout) (commit db3e643c0 in tram.autoware)
- `monitoring_agent/handlers/logs.py`
- Постоянная подписка на /rosout
- Кольцевой буфер последних N сообщений
- subscribe/unsubscribe для клиентов с фильтрацией по ноде/уровню

### 1.10 [x] Модуль Diagnostics (commit db3e643c0 in tram.autoware)
- `monitoring_agent/handlers/diagnostics.py`
- Подписка на /diagnostics, /display/mrm_status и др.
- Парсинг DiagnosticArray в JSON

---

## Фаза 2: Backend Adapter (ros2_node_manager)

### 2.1 [x] AgentConnection — WebSocket клиент (commit 4798c10)
- `server/connection/agent.py` — класс AgentConnection(BaseConnection)
- WebSocket клиент (websockets библиотека)
- Реализация всех методов BaseConnection через agent protocol
- Auto-reconnect при потере соединения

### 2.2 [x] Обновление Connection Factory (commit 4798c10)
- `server/connection/__init__.py` — добавить AgentConnection в экспорт
- `server/main.py` — создание AgentConnection при type="agent"
- `config/servers.yaml` — пример конфигурации agent

### 2.3 [x] Адаптация сервисов под agent streaming (commit 4798c10)
- exec_stream переводит ros2 CLI команды в agent subscriptions
- Конвертирует JSON events обратно в YAML для обратной совместимости
- Все сервисы работают без изменений и через docker exec, и через agent

---

## Фаза 3: Интеграция и деплой

### 3.1 [x] Launch file для monitoring_agent (commit db3e643c0 in tram.autoware)
- `monitoring_agent/launch/monitoring_agent.launch.py`
- Интеграция в autoware launch: tram_autoware.launch.xml (commit 228cc1a4f in tram.autoware)
- Запускается в обоих launch: tram_autoware и standalone_localization
- Аргумент `launch_monitoring_agent` (default=true)

### 3.2 [x] Docker port exposure
- Docker использует `--network host` — проброс не нужен
- Порт 9090 доступен напрямую на хосте

### 3.3 [x] Бенчмарки и нагрузочное тестирование
- `monitoring_agent/load_generator.py` — генератор фейковых нод/топиков
- `benchmarks/bench_agent_vs_docker.py` — сравнение latency/throughput/CPU/memory
- `docs/benchmarks.md` — документация бенчмарков

### 3.4 [ ] End-to-end тестирование
- Проверка всех команд через agent
- Сравнение с docker exec режимом
- Проверка reconnect при перезапуске agent

---

## Порядок выполнения

1. ~~Фаза 0 (протокол) — блокирует всё остальное~~ DONE
2. ~~Фаза 1.1-1.2 (скелет + core) — фундамент agent~~ DONE
3. ~~Фаза 1.3 (graph) + Фаза 2.1 (AgentConnection) — параллельно~~ DONE
4. ~~Фаза 1.4-1.10 (остальные модули agent) — последовательно~~ DONE
5. ~~Фаза 2.2-2.3 (интеграция backend) — после agent модулей~~ DONE
6. Фаза 3 (деплой) — финальная фаза — PARTIAL (launch file done, port & e2e remaining)
