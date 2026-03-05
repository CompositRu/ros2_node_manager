# Evidence — Подтверждённые факты

> Результаты тестов, бенчмарков, найденные баги. Ссылки на источники.

---

### E1: Бенчмарк Agent vs Docker Exec

**Источник:** `docs/benchmarks.md`, `benchmarks/bench_agent_vs_docker.py`

**Результаты:**
- docker exec: 200-500ms latency per request
- monitoring_agent: 1-20ms latency per request
- Разница: 10-50x быстрее через agent

**Нагрузочный генератор:** `monitoring_agent/load_generator.py`
- Поддерживает 50-500+ fake нод
- Настраиваемые параметры: topics per node, publish frequency, lifecycle ratio

---

### E2: Monitoring Agent — все модули работают

**Дата:** Март 2025
**Коммиты:** db3e643c0 (tram.autoware), 4798c10 (ros2_node_manager)

Реализовано и проверено:
- graph.nodes, graph.node_info, graph.topics, graph.topic_info ✅
- lifecycle.get_state, lifecycle.set_state ✅
- params.dump ✅
- topic.echo, topic.hz (стриминг) ✅
- logs (rosout стриминг) ✅
- diagnostics (стриминг) ✅
- service.call ✅
- process.kill ✅

**Не проверено:** E2E тестирование полного цикла, reconnect сценарии.

---

### E3: Известные ограничения

- Kill regular нод ненадёжен без знания executable name
- Некоторые ноды не поддерживают динамическое изменение параметров
- Система рассчитана на одного пользователя
