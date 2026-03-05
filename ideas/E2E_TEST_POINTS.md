# E2E тестирование monitoring_agent — точки тестирования

Все точки для e2e системы тестирования в режиме работы с monitoring_agent.
Существующий бенчмарк (`benchmarks/bench_agent_vs_docker.py`) покрывает только 5 из 47.

## 1. RPC-вызовы (request/response через JSON-RPC)

| # | Операция | RPC метод | Что тестируем |
|---|----------|-----------|---------------|
| 1 | Список нод | `graph.nodes` | Получение всех ROS2 нод |
| 2 | Информация о ноде | `graph.node_info` | Subscribers, publishers, services ноды |
| 3 | Список топиков | `graph.topics` | Все топики с типами |
| 4 | Информация о топике | `graph.topic_info` | Тип, publishers, subscribers топика |
| 5 | Список сервисов | `graph.services` | Имена сервисов |
| 6 | Список сервисов с типами | `graph.services_typed` | Имена + типы сервисов |
| 7 | Интерфейс сервиса/сообщения | `graph.interface_show` | Определение msg/srv типа |
| 8 | Параметры ноды | `params.dump` | Все параметры конкретной ноды |
| 9 | Проверка lifecycle ноды | `lifecycle.is_lifecycle` | Является ли нода lifecycle |
| 10 | Состояние lifecycle | `lifecycle.get_state` | Текущее состояние (active/inactive/...) |
| 11 | Переключение lifecycle | `lifecycle.set_state` | configure/activate/deactivate/shutdown/cleanup |
| 12 | Вызов сервиса | `service.call` | Произвольный service call с YAML |
| 13 | Kill процесса | `process.kill` | Завершение процесса по паттерну |

## 2. Подписки (streaming через subscribe/unsubscribe)

| # | Операция | Канал | Что тестируем |
|---|----------|-------|---------------|
| 14 | Echo одного топика | `topic.echo` | Поток сообщений с произвольного топика |
| 15 | Hz одного топика | `topic.hz` | Частота публикации топика |
| 16 | Все логи (/rosout) | `logs` | Поток логов со всех нод |
| 17 | Диагностика | `diagnostics` | Поток /diagnostics событий |

## 3. HTTP API endpoints (через FastAPI, работают поверх agent)

| # | Операция | Endpoint | Что тестируем |
|---|----------|----------|---------------|
| 18 | Список нод (API) | `GET /api/nodes?refresh=true` | Полный цикл: API → AgentConnection → agent |
| 19 | Детали ноды (API) | `GET /api/nodes/{name}?refresh=true` | Информация о ноде через API |
| 20 | Параметры ноды (API) | `GET /api/nodes/{name}/params` | Параметры через API |
| 21 | Список топиков (API) | `GET /api/topics/list` | Топики через API |
| 22 | Info топика (API) | `GET /api/topics/info/{topic}` | Детали топика через API |
| 23 | Группы топиков (API) | `GET /api/topics/groups` | Конфигурация групп + Hz |
| 24 | Toggle Hz группы (API) | `POST /api/topics/groups/{id}/hz` | Включение/выключение мониторинга Hz группы |
| 25 | Список сервисов (API) | `GET /api/services/list` | Сервисы через API |
| 26 | Интерфейс сервиса (API) | `GET /api/services/interface/{type}` | Определение интерфейса |
| 27 | Вызов сервиса (API) | `POST /api/services/call/{name}` | Service call через API |
| 28 | Lifecycle transition (API) | `POST /api/nodes/{name}/lifecycle` | Управление lifecycle через API |
| 29 | История логов | `GET /api/history/logs` | Логи из SQLite с фильтрами |
| 30 | История алертов | `GET /api/history/alerts` | Алерты из SQLite |
| 31 | Экспорт логов | `GET /api/history/logs/export` | Экспорт в json/text |
| 32 | Статистика истории | `GET /api/history/stats` | Счётчики записей |

## 4. WebSocket потоки (через FastAPI WS endpoints)

| # | Операция | WS endpoint | Что тестируем |
|---|----------|-------------|---------------|
| 33 | Статус нод (live) | `WS /ws/nodes/status` | Поток обновлений статуса (каждые 5с) |
| 34 | Все логи + история | `WS /ws/logs/all` | 300с истории при подключении + live |
| 35 | Логи одной ноды | `WS /ws/logs/{node}` | Фильтрованные логи с историей |
| 36 | Hz всех групп | `WS /ws/topics/hz` | Частота по всем включённым группам (2с) |
| 37 | Echo группы | `WS /ws/topics/echo/{group_id}` | Сообщения всех топиков группы |
| 38 | Echo одного топика | `WS /ws/topics/echo-single/{topic}` | Сообщения одного топика |
| 39 | Hz одного топика | `WS /ws/topics/hz-single/{topic}` | Частота одного топика |
| 40 | Диагностика | `WS /ws/diagnostics` | Diagnostics + lidar sync + MRM |
| 41 | Алерты (live) | `WS /ws/alerts` | Уведомления от AlertService |

## 5. Инфраструктурные тесты

| # | Операция | Что тестируем |
|---|----------|---------------|
| 42 | Подключение к серверу | `POST /api/servers/connect` — подключение agent типа |
| 43 | Отключение | `POST /api/servers/disconnect` |
| 44 | Health check | `GET /health` |
| 45 | Debug stats | `GET /api/debug/stats` — метрики подключений |
| 46 | Переподключение WS | Разрыв и автовосстановление WebSocket к agent |
| 47 | Dashboard (partial) | `GET /api/dashboard` — проверка что работает без host commands |

## Рекомендуемые уровни тестирования

- **Уровень 1 — Agent RPC напрямую** (#1–17): WebSocket к agent, латентность/корректность JSON-RPC
- **Уровень 2 — HTTP API** (#18–32): Полный цикл через FastAPI
- **Уровень 3 — WS потоки** (#33–41): Подписки, throughput, корректность фильтрации
- **Уровень 4 — Инфраструктура** (#42–47): Подключение, health, reconnect

## Покрытие существующим бенчмарком

`bench_agent_vs_docker.py` покрывает: #1, #2, #3, #5, #14 (echo /rosout) — **5 из 47**.
