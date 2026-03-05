# Plan — Текущие фазы работы

## Завершённые фазы

| Версия | Название | Статус |
|--------|----------|--------|
| v0.1 | MVP: Docker, SSH, ноды, параметры, логи, lifecycle | Done |
| v0.2 | Activity Bar + App Stats + Unified Logs | Done |
| v0.3 | Diagnostics dashboard | Done |
| v0.5 | Topics (Groups + Tree, Hz, Echo) | Done |
| v0.6 | Log History + Alert History (SQLite) | Done |
| v0.7 | Services + Actions | Done |

### Monitoring Agent (отдельный трек)
| Фаза | Название | Статус |
|-------|----------|--------|
| 0 | Протокол JSON-RPC + тип сервера "agent" | Done |
| 1 | ROS2 нода monitoring_agent (все 10 модулей) | Done |
| 2 | Backend AgentConnection (WebSocket клиент) | Done |
| 3 | Интеграция и деплой | Partial (launch done, E2E testing remaining) |

## Текущая фаза

**E2E Test Fixes — исправление проблем найденных при E2E тестировании**

Результаты: 39/43 passed, 2 failed, 2 skipped. Файл: `results.json`

Проблемы:
1. `/health` endpoint перехватывается SPA catch-all route — возвращает HTML вместо JSON
2. `/api/health` использует `._connected` вместо `.connected`
3. `api.GET /api/nodes` — 3.3s латентность при 200 нодах (надо профилировать)
4. `rpc.sub.diagnostics` и `ws.WS /ws/alerts` — 10s таймауты (load_generator не генерирует diagnostics/alerts)



## Будущие работы

**v0.8 — Визуализация графа**
- Граф связей между нодами (как rqt_graph)
- Интерактивный граф (zoom, pan, select)
- Фильтрация по namespace

**Monitoring Agent — завершение Phase 3**
- E2E тестирование всех команд через agent
- Сравнение с docker exec режимом
- Проверка reconnect при перезапуске agent

## Будущие фазы

- **v0.9** — Улучшения управления нодами (lifecycle FSM, групповые операции, param set)
- **v1.0** — Production Ready (Docker образ, CI/CD, auth, HTTPS, тесты)
- **Future** — Fleet Radar интеграция, плагины, rosbag, мобильная версия

Полный roadmap: `ideas/ROADMAP.md`
Детали agent плана: `ideas/PLAN_MONITORING_AGENT.md`
