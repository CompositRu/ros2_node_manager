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

### E3: E2E тестирование через agent (2026-03-05)

**Источник:** `results.json`, `tests/e2e_agent.py`
**Конфигурация:** agent ws://localhost:9090, load_generator 200 нод, 3 topics/node, 30 Hz

**Результат до фикса:** 39/43 passed, 2 failed, 2 skipped
**Результат после фикса:** 41/43 passed, 0 failed, 2 skipped (destructive)

**Найденные баги (исправлены):**
- `/health` перехватывался SPA catch-all route → возвращал HTML вместо JSON
- `/api/health` использовал `._connected` вместо `.connected`
- Дублированный код SPA routing в main.py (два catch-all)

**Ожидаемые таймауты (не баги):**
- `rpc.sub.diagnostics` 10s — load_generator не публикует `/diagnostics`
- `ws.WS /ws/alerts` 10s — нет условий для срабатывания алертов в тестовом окружении

**Латентность /api/nodes: 3.3s** — первый вызов: 200 новых нод × `is_lifecycle_node` RPC. Последующие вызовы кэшируются (rate limiter 3s). Оптимизация: batch RPC `lifecycle.is_lifecycle_batch`.

---

### E4: Известные ограничения

- Kill regular нод ненадёжен без знания executable name
- Некоторые ноды не поддерживают динамическое изменение параметров
- Система рассчитана на одного пользователя
