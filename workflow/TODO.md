# TODO — Активные задачи

> Обновляется в начале каждой сессии. Содержит только то, что делается сейчас.

## В работе

- [x] Fix: `/health` перехватывается SPA catch-all — переместить выше ✅
- [x] Fix: `/api/health` использует `._connected` вместо `.connected` ✅
- [x] Fix: убран дублированный SPA routing в main.py ✅
- [x] Investigate: `api.GET /api/nodes` 3.3s — first-call issue (200 lifecycle checks), кэш работает ✅
- [x] Review: diagnostics/alerts 10s таймауты — ожидаемо (load_generator не генерирует) ✅
- [x] Перезапустить E2E тесты и подтвердить фиксы — 41/43 passed, 0 failed ✅

## Следующие

- [ ] Проверка reconnect при перезапуске agent
- [ ] Начать v0.8: исследовать библиотеки для визуализации графа (D3, Cytoscape, React Flow)
- [ ] Прототип графа нод с данными из `graph.nodes` + `graph.node_info`

## Блокеры

_Нет активных блокеров_

## Заметки

- При работе над agent — код в `~/tram.autoware/src/system/monitoring_agent/`
- При работе над web UI — код в `web/src/`
- Бенчмарки agent vs docker exec: `docs/benchmarks.md`
