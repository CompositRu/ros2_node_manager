# E2E тестирование monitoring_agent — дизайн системы

Скрипт `benchmarks/test_agent_e2e.py`, запускаемый аналогично `bench_agent_vs_docker.py`.

## Цели

1. **Проверка корректности** — каждая операция agent возвращает валидные данные
2. **Измерение латентности** — сколько ms на каждую операцию
3. **Проверка потоков** — подписки доставляют сообщения, Hz > 0
4. **Полный цикл через API** — HTTP endpoints корректно работают поверх agent
5. **Отчёт** — человекочитаемая таблица + JSON для автоматизации

## Архитектура скрипта

```
test_agent_e2e.py
├── TestResult (dataclass: name, passed, latency_ms, error, details)
├── TestSuite (группа тестов, агрегация результатов)
│
├── Level 1: Agent RPC (прямой WebSocket к agent:9090)
│   └── test_rpc_* — 13 тестов
│
├── Level 2: HTTP API (запросы к FastAPI localhost:8080)
│   └── test_api_* — 15 тестов
│
├── Level 3: WS Streams (WebSocket к FastAPI ws://localhost:8080/ws/*)
│   └── test_ws_* — 9 тестов
│
├── Level 4: Infrastructure
│   └── test_infra_* — 6 тестов
│
└── Reporter (вывод таблицы + сохранение JSON)
```

## Ключевые идеи

### 1. Два уровня подключения

Скрипт работает на двух уровнях одновременно:

- **Прямой WebSocket к agent** (`ws://host:9090`) — тестирует JSON-RPC протокол
- **HTTP/WS к FastAPI** (`http://host:8080`) — тестирует полный стек через API

Это позволяет отличить проблему в agent от проблемы в backend.

### 2. Каждый тест = функция с единым контрактом

```python
@dataclass
class TestResult:
    name: str           # "rpc.graph.nodes"
    suite: str          # "rpc" | "api" | "ws" | "infra"
    passed: bool
    latency_ms: float   # время выполнения
    error: str = ""     # текст ошибки если failed
    details: dict = {}  # доп. данные (кол-во нод, сообщений и т.д.)
```

Каждый тест — async функция, возвращающая `TestResult`. Тест считается passed, если:
- Нет исключений
- Ответ проходит базовую валидацию (не пустой, правильный тип)

### 3. Валидация ответов (не только "не упало")

В отличие от бенчмарка, e2e тесты **проверяют содержимое**:

| Операция | Валидация |
|----------|-----------|
| `graph.nodes` | Вернул list[str], len > 0, каждый начинается с `/` |
| `graph.topics` | Вернул list[dict], каждый имеет `name` и `type` |
| `graph.node_info` | Результат содержит ключи `subscribers`, `publishers`, `services` |
| `topic.hz` | За 5с получили хотя бы 1 сообщение с `hz > 0` |
| `logs` | За 10с получили хотя бы 1 лог-событие с полями `timestamp`, `level`, `node`, `message` |
| `GET /api/nodes` | HTTP 200, JSON с полями `nodes`, `total`, `active` |
| `WS /ws/logs/all` | Первое сообщение содержит историю (массив), затем live-логи |

### 4. Динамическое обнаружение тестовых данных

Скрипт не хардкодит имена нод/топиков. Вместо этого:

```
1. graph.nodes → выбрать первую ноду → использовать для node_info, params, lifecycle
2. graph.topics → выбрать /rosout (всегда есть) → использовать для hz, echo
3. graph.services → выбрать первый сервис → использовать для interface_show
4. topic_groups из config → выбрать первую группу → hz группы, echo группы
```

Результат обнаружения сохраняется в `TestContext` и переиспользуется:

```python
@dataclass
class TestContext:
    agent_ws: WebSocket         # прямое подключение к agent
    api_base: str               # "http://localhost:8080"
    test_node: str = ""         # первая обнаруженная нода
    test_topic: str = "/rosout" # гарантированно существует
    test_service: str = ""      # первый обнаруженный сервис
    test_group_id: str = ""     # первая группа из topic_groups.yaml
    lifecycle_node: str = ""    # первая lifecycle нода (если есть)
```

### 5. Уровни запуска (--level)

```bash
# Всё
python benchmarks/test_agent_e2e.py

# Только быстрые RPC тесты
python benchmarks/test_agent_e2e.py --level rpc

# RPC + API (без WS потоков — они медленные)
python benchmarks/test_agent_e2e.py --level rpc,api

# Конкретный тест
python benchmarks/test_agent_e2e.py --test rpc.graph.nodes
```

### 6. Таймауты для потоковых тестов

RPC тесты мгновенные (< 1с). Потоковые тесты (hz, echo, logs) требуют ожидания:

| Тест | Таймаут | Критерий успеха |
|------|---------|-----------------|
| `topic.hz` | 5с | Получили >= 1 сообщение с hz > 0 |
| `topic.echo` | 5с | Получили >= 1 сообщение с data |
| `logs` (подписка) | 10с | Получили >= 1 лог |
| `diagnostics` | 10с | Получили >= 1 событие |
| `WS /ws/nodes/status` | 7с | Получили >= 1 обновление |
| `WS /ws/logs/all` | 10с | Получили историю + >= 1 live |
| `WS /ws/topics/hz` | 5с | Получили hz_update |

### 7. Вывод результатов

Терминальный вывод:

```
=== E2E Test: monitoring_agent ===
Agent: ws://localhost:9090, API: http://localhost:8080

--- RPC Tests (13) ---
  ✓ graph.nodes            12ms  (47 nodes)
  ✓ graph.topics           8ms   (156 topics)
  ✓ graph.node_info        5ms
  ✗ lifecycle.get_state    --    Error: not a lifecycle node
  ○ lifecycle.set_state    --    Skipped: no lifecycle node found
  ...

--- API Tests (15) ---
  ✓ GET /api/nodes         45ms  (47 nodes, 45 active)
  ...

--- WS Stream Tests (9) ---
  ✓ /ws/logs/all           1203ms  (history: 84 msgs, live: 3 msgs)
  ✓ /ws/topics/hz          2104ms  (5 groups reported)
  ...

--- Infrastructure (6) ---
  ✓ health check           2ms
  ✓ connect/disconnect     156ms
  ...

=== Summary ===
Passed: 41/47, Failed: 2, Skipped: 4
Total time: 52.3s
```

Статусы: `✓` passed, `✗` failed, `○` skipped (нет тестовых данных, напр. нет lifecycle нод).

### 8. JSON отчёт

Сохраняется в `benchmarks/e2e_results.json`:

```json
{
  "timestamp": "2026-03-05 14:30:00",
  "agent_url": "ws://localhost:9090",
  "api_base": "http://localhost:8080",
  "summary": {"total": 47, "passed": 41, "failed": 2, "skipped": 4},
  "context": {"test_node": "/node_a", "test_topic": "/rosout", ...},
  "results": [
    {"name": "rpc.graph.nodes", "suite": "rpc", "passed": true, "latency_ms": 12.3,
     "details": {"count": 47}},
    ...
  ]
}
```

### 9. CLI аргументы

```
--agent-url       WebSocket URL agent'а (default: ws://localhost:9090)
--api-base        URL FastAPI backend'а (default: http://localhost:8080)
--level           Какие уровни запускать: rpc,api,ws,infra (default: all)
--test            Запустить конкретный тест по имени
--timeout         Глобальный множитель таймаутов (default: 1.0)
--output          Путь для JSON отчёта (default: benchmarks/e2e_results.json)
--verbose         Подробный вывод (тела ответов, сырые данные)
--no-destructive  Пропустить тесты с side-effects (lifecycle.set_state, process.kill)
```

### 10. Деструктивные тесты — отдельная категория

Тесты `lifecycle.set_state`, `process.kill`, `POST /api/nodes/{name}/lifecycle` могут менять состояние системы. По умолчанию они **пропускаются** (`--no-destructive` по умолчанию включён). Для запуска:

```bash
python benchmarks/test_agent_e2e.py --destructive
```

## Порядок выполнения

```
1. Подключение к agent (WebSocket)
2. Discovery: получить ноды, топики, сервисы → заполнить TestContext
3. Level 1: RPC тесты (параллельно где можно)
4. Level 2: HTTP API тесты (последовательно, т.к. один backend)
5. Level 3: WS потоки (последовательно, каждый с таймаутом)
6. Level 4: Инфраструктурные (connect/disconnect, health)
7. Отчёт
```

## Зависимости

- `websockets` — уже есть в проекте
- `aiohttp` — для HTTP запросов к API (или `httpx`)
- Стандартная библиотека: `asyncio`, `json`, `argparse`, `dataclasses`, `time`
