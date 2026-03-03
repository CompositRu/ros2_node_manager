# Benchmarks: monitoring_agent vs docker exec

## Обзор

Сравнение двух режимов работы ros2_node_manager:

| | **docker exec** (текущий) | **monitoring_agent** (новый) |
|---|---|---|
| Как работает | Каждый запрос → `docker exec bash -c 'source ... && ros2 ...'` | Один ROS2 node внутри Docker с WebSocket API |
| Процессы | 10-20 параллельных docker exec | 1 процесс monitoring_agent |
| Стриминг | Долгоживущие docker exec (echo, hz) | ROS2 подписки + WebSocket push |
| Латентность | ~200-500ms (spawn + source + CLI) | ~1-20ms (JSON-RPC через WS) |

## Запуск бенчмарков

### Предварительные требования

1. Docker контейнер `tram_autoware` запущен
2. ROS2 окружение сконфигурировано (env cache)
3. Для agent-бенчмарков: monitoring_agent запущен внутри контейнера

### Шаг 1: Запуск имитации нагрузки

Внутри Docker контейнера запустить генератор нагрузки:

```bash
# Минимальная нагрузка (50 нод, 150 топиков)
docker exec tram_autoware bash -c \
  'source /tmp/.ros2nm_env_cache && \
   ros2 run monitoring_agent load_generator'

# Высокая нагрузка (200 нод, 600 топиков, 30 Hz)
docker exec tram_autoware bash -c \
  'source /tmp/.ros2nm_env_cache && \
   ros2 run monitoring_agent load_generator --ros-args \
     -p node_count:=200 \
     -p topics_per_node:=3 \
     -p publish_hz:=30.0 \
     -p lifecycle_ratio:=0.3 \
     -p diagnostics_ratio:=0.2'

# Стресс-тест (500 нод, 1500 топиков)
docker exec tram_autoware bash -c \
  'source /tmp/.ros2nm_env_cache && \
   ros2 run monitoring_agent load_generator --ros-args \
     -p node_count:=500 \
     -p topics_per_node:=3 \
     -p publish_hz:=10.0'
```

Параметры load_generator:

| Параметр | Default | Описание |
|----------|---------|----------|
| `node_count` | 50 | Количество фейковых нод |
| `topics_per_node` | 3 | Топиков на ноду |
| `publish_hz` | 30.0 | Частота публикации |
| `lifecycle_ratio` | 0.3 | Доля lifecycle нод (30%) |
| `diagnostics_ratio` | 0.2 | Доля нод с диагностикой (20%) |

Что генерируется:
- Ноды в реалистичных namespace (`/sensing/lidar`, `/planning/mission`, etc.)
- Каждая нода публикует `topics_per_node` топиков (String, Float64, Bool, Int32)
- 30% нод — lifecycle (с get_state/change_state сервисами)
- 20% нод публикуют DiagnosticArray в `/diagnostics`
- Каждая 5-я нода пишет в `/rosout` (INFO/DEBUG/WARN)

### Шаг 2: Запуск monitoring_agent

```bash
docker exec tram_autoware bash -c \
  'source /tmp/.ros2nm_env_cache && \
   ros2 run monitoring_agent monitoring_agent'
```

Или через launch:
```bash
docker exec tram_autoware bash -c \
  'source /tmp/.ros2nm_env_cache && \
   ros2 launch monitoring_agent monitoring_agent.launch.py'
```

### Шаг 3: Запуск бенчмарка

```bash
# Сравнение обоих режимов (20 итераций)
python benchmarks/bench_agent_vs_docker.py

# Только docker exec
python benchmarks/bench_agent_vs_docker.py --mode docker --iterations 50

# Только agent
python benchmarks/bench_agent_vs_docker.py --mode agent --iterations 50

# Больше итераций для точности
python benchmarks/bench_agent_vs_docker.py --iterations 100

# Сохранить результаты в файл
python benchmarks/bench_agent_vs_docker.py --output benchmarks/results_200nodes.json
```

## Метрики

### Что замеряется

| Метрика | Описание | Как измеряется |
|---------|----------|----------------|
| **Latency** | Время от запроса до ответа | `time.perf_counter()` вокруг операции |
| **Avg / Median / P95** | Статистики по N итерациям | `statistics.mean/median` |
| **Throughput** | Сообщений/сек для подписок | Счётчик за 5 секунд |
| **Process count** | Кол-во процессов на хосте | `ps aux | wc -l` |
| **Docker exec count** | Активные docker exec | `pgrep -c docker exec` |
| **RSS** | Потребление памяти | `resource.getrusage` |
| **Errors** | Количество ошибок | Счётчик ненулевых returncode |

### Операции для сравнения

| Операция | docker exec команда | agent метод |
|----------|---------------------|-------------|
| node_list | `ros2 node list` | `graph.nodes` |
| topic_list | `ros2 topic list -t` | `graph.topics` |
| service_list | `ros2 service list` | `graph.services` |
| node_info | `ros2 node info /node` | `graph.node_info` |
| topic_echo | `ros2 topic echo /topic` (stream) | `subscribe topic.echo` |
| topic_hz | `ros2 topic hz /topic` (stream) | `subscribe topic.hz` |

### Ожидаемые результаты

На основе архитектурного анализа:

| Операция | docker exec | agent (ожидание) | Speedup |
|----------|-------------|-------------------|---------|
| node_list | 200-500ms | 1-5ms | 40-100x |
| topic_list | 200-500ms | 1-5ms | 40-100x |
| node_info | 300-800ms | 2-10ms | 30-80x |
| service_list | 200-500ms | 1-5ms | 40-100x |
| Процессы | 10-20 | 1 | 10-20x меньше |
| CPU idle | ~5-15% | ~1-3% | 3-5x меньше |

Основные источники ускорения:
1. **Нет spawn процесса** — docker exec создаёт новый bash каждый раз
2. **Нет sourcing** — даже с кешем, sourcing env файла занимает ~50ms
3. **Нет CLI парсинга** — `ros2 node list` сам инициализирует rclpy, что дорого
4. **Прямой API** — rclpy `get_node_names_and_namespaces()` это один вызов DDS

## Формат результатов

Результаты сохраняются в JSON:

```json
{
  "timestamp": "2026-03-03 15:30:00",
  "system": {
    "process_count": 250,
    "docker_exec_count": 0,
    "rss_mb": 45.2
  },
  "docker_results": [
    {
      "operation": "node_list",
      "mode": "docker",
      "count": 20,
      "avg_ms": 350.5,
      "median_ms": 340.2,
      "p95_ms": 480.1,
      "min_ms": 280.3,
      "max_ms": 520.7,
      "errors": 0
    }
  ],
  "agent_results": [
    {
      "operation": "node_list",
      "mode": "agent",
      "count": 20,
      "avg_ms": 3.2,
      "median_ms": 2.8,
      "p95_ms": 5.1,
      "min_ms": 1.9,
      "max_ms": 8.3,
      "errors": 0
    }
  ]
}
```

## Профили нагрузки

### Реальный трамвай (production)
- ~150-200 нод
- ~400-600 топиков
- 1 пользователь ros2_node_manager

### Разработка (dev)
- ~50-100 нод (подмножество)
- ~150-300 топиков
- 1-2 пользователя

### Стресс-тест
- 500 нод, 1500 топиков
- 3-5 одновременных пользователей ros2_node_manager
- Все секции UI активны (nodes + diagnostics + topics + logs)
