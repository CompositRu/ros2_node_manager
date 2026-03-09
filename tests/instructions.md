### Шаг 1: Запуск имитации нагрузки

Внутри Docker контейнера запустить генератор нагрузки:

```bash
# Минимальная нагрузка (50 нод, 150 топиков)
   ros2 run monitoring_agent load_generator

# Высокая нагрузка (200 нод, 600 топиков, 30 Hz)
   ros2 run monitoring_agent load_generator --ros-args \
     -p node_count:=200 \
     -p topics_per_node:=3 \
     -p publish_hz:=30.0 \
     -p lifecycle_ratio:=0.3 \
     -p diagnostics_ratio:=0.2

# Стресс-тест (500 нод, 1500 топиков)
   ros2 run monitoring_agent load_generator --ros-args \
     -p node_count:=500 \
     -p topics_per_node:=3 \
     -p publish_hz:=10.0
```



### Шаг 2: Запуск monitoring_agent

```bash
   ros2 run monitoring_agent monitoring_agent
```

Или через launch:
```bash
   ros2 launch monitoring_agent monitoring_agent.launch.py
```


### Шаг 3: Запуск приложения мониторинга

```
clear && ./start.sh 
```




### Шаг 4: Запуск тестов

```
clear && python3 tests/soak_test.py --duration 1200 --clients 10 --echo-topics 10 --json-report soak_results.json
```

```
clear && python3 tests/e2e_agent.py --json-report results.json
```