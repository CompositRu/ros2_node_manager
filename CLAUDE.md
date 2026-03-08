# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**Tram Monitoring System** — веб-интерфейс для мониторинга ROS2 нод в Docker контейнерах на автономных трамваях. Основной фокус — мониторинг и диагностика, а не управление.

Подключается к Docker контейнеру с ROS2 через **monitoring_agent** (WebSocket JSON-RPC).

Связанный проект: **monitoring_agent** — ROS2 нода внутри Docker, код в `~/tram.autoware/src/system/monitoring_agent/`.

Планируется связка с **Fleet Radar** — обзор всех единиц флота.

## Development Commands

### Backend (FastAPI/Python)
```bash
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
uvicorn server.main:app --reload --port 8080
```

### Frontend (React/Vite)
```bash
cd web
npm install
npm run dev      # Development (port 3000)
npm run build    # Production build to web/dist/
```

Frontend proxies API calls to backend (port 8080).

## Deployment

- `deploy/deploy-simple.sh <host> [user]` — копирует код на целевую машину
- `deploy/start-remote.sh <host> [user]` — запускает сервер через SSH
- `deploy/deploy.sh` — полный деплой с systemd

## Configuration

- `config/config.yaml` — серверы (agent_url для подключения к monitoring_agent)
- `config/topic_groups.yaml` — группы топиков для Hz/echo
- `config/alerts.yaml` — правила алертов
- Первый сервер подключается автоматически. Состояние нод: `data/{server_id}.json`

## ROS2 Environment

- Sources `/opt/ros/humble/setup.bash`
- `ROS_DOMAIN_ID` из `$HOME/tram.autoware/.ros_domain_id`
- `ROS_LOCALHOST_ONLY=1`, `RMW_IMPLEMENTATION=rmw_cyclonedds_cpp`
- Технические ноды (transform_listener, ros2cli, daemon, launch_ros) отфильтрованы

## Workflow Files

Состояние проекта вынесено из чата в файлы (context engineering):

- `workflow/ARCHITECTURE.md` — детальная архитектура backend, frontend, agent
- `workflow/PLAN.md` — фазы работы, что завершено и что в процессе
- `workflow/TODO.md` — активные задачи текущей фазы
- `workflow/DECISIONS.md` — принятые решения и отклонённые варианты
- `workflow/EVIDENCE.md` — результаты бенчмарков, тестов, факты

Полный roadmap: `ideas/ROADMAP.md`
План monitoring agent: `ideas/PLAN_MONITORING_AGENT.md`

## Workflow Rules

- **Перед началом работы**: прочитай `workflow/TODO.md` и `workflow/PLAN.md`
- **После завершения задачи**: обнови `workflow/TODO.md`
- **При принятии решения**: добавь запись в `workflow/DECISIONS.md`
- **При получении результатов тестов/бенчмарков**: обнови `workflow/EVIDENCE.md`
- **Длинные логи и выводы**: сохраняй в файлы, в чат — только краткое резюме
- **Исследование**: выноси в subagent'ы, чтобы не засорять основной контекст
