# ROS2 Monitor — Roadmap for Architecture Update

## Обзор этапов

```
┌─────────────────────────────────────────────────────────────────────────┐
│                                                                         │
│  Phase 0        Phase 1        Phase 2        Phase 3        Phase 4   │
│  ─────────      ─────────      ─────────      ─────────      ─────────  │
│  Dev Mode       Production     Multi-Device   VPN + Fleet    Scale     │
│  (текущий)      Build          Deploy         Monitor        (100+)    │
│                                                                         │
│  ● ──────────► ○ ──────────► ○ ──────────► ○ ──────────► ○             │
│                                                                         │
│  1-2 дня        1 день         2-3 дня        3-5 дней       ongoing   │
│                                                                         │
└─────────────────────────────────────────────────────────────────────────┘
```

---

## Phase 0: Текущее состояние (Dev Mode) ✅

### Что есть
- [x] Backend (FastAPI + uvicorn)
- [x] Frontend (React + Vite dev server)
- [x] Работает с docker exec в tram_autoware
- [x] Мониторинг нод, логов, параметров
- [x] Lifecycle управление

### Ограничения
- Требует два терминала (backend + frontend)
- Работает только на dev-машине
- Нет production сборки
- Нет автозапуска

---

## Phase 1: Production Build

**Цель:** Один процесс, готовый к деплою на устройство.

**Срок:** 1 день

### Задачи

#### 1.1 Сборка React в статику
```bash
cd web
npm run build
# Результат: web/dist/
```
- [ ] Проверить что `npm run build` работает без ошибок
- [ ] Проверить что все assets корректно собираются

#### 1.2 FastAPI раздаёт статику
```python
# server/main.py
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

# После всех API роутеров:
if os.path.exists("web/dist"):
    app.mount("/assets", StaticFiles(directory="web/dist/assets"))
    
    @app.get("/{full_path:path}")
    async def serve_react(full_path: str):
        return FileResponse("web/dist/index.html")
```
- [ ] Добавить раздачу статики
- [ ] Проверить что SPA routing работает

#### 1.3 Конфигурация через переменные окружения
```python
# server/config.py
import os

class Settings:
    docker_container = os.getenv("DOCKER_CONTAINER", "tram_autoware")
    ros_setup = os.getenv("ROS_SETUP", "/opt/ros/humble/setup.bash")
    data_dir = os.getenv("DATA_DIR", "./data")
    port = int(os.getenv("PORT", "8080"))
```
- [ ] Переделать config.py на ENV переменные
- [ ] Документировать все переменные

#### 1.4 Docker Service
```python
# server/services/docker_service.py
class DockerService:
    def is_running(self) -> bool
    def get_status(self) -> dict
    def start(self) -> bool
    def stop(self) -> bool
    def restart(self) -> bool
    def logs(self, lines: int) -> str
```
- [ ] Создать DockerService
- [ ] API endpoint: GET /api/autopilot/status
- [ ] API endpoint: POST /api/autopilot/start
- [ ] API endpoint: POST /api/autopilot/stop
- [ ] UI компонент статуса автопилота

#### 1.5 systemd сервис
```ini
# ros2-monitor.service
[Unit]
Description=ROS2 Node Monitor
After=network.target docker.service

[Service]
Type=simple
User=artem
WorkingDirectory=/opt/ros2-monitor
Environment="DOCKER_CONTAINER=tram_autoware"
ExecStart=/usr/bin/python3 -m uvicorn server.main:app --host 0.0.0.0 --port 8080
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```
- [ ] Создать файл сервиса
- [ ] Протестировать на dev-машине

#### 1.6 Тестирование production режима
- [ ] Собрать: `cd web && npm run build`
- [ ] Запустить: `uvicorn server.main:app --port 8080`
- [ ] Открыть: `http://localhost:8080`
- [ ] Проверить все функции

### Результат Phase 1
```
/opt/ros2-monitor/
├── server/              # Backend
├── web/dist/            # Собранный frontend
├── config/
├── data/
└── VERSION
```
Один процесс: `uvicorn server.main:app --port 8080`

---

## Phase 2: Multi-Device Deploy

**Цель:** Развернуть на 2+ устройствах с помощью скриптов/Ansible.

**Срок:** 2-3 дня

### Задачи

#### 2.1 Простой скрипт деплоя
```bash
#!/bin/bash
# deploy.sh
HOSTS="10.0.1.5 10.0.1.6"

cd web && npm run build && cd ..

for HOST in $HOSTS; do
    rsync -avz --exclude 'node_modules' ./ artem@$HOST:/opt/ros2-monitor/
    ssh artem@$HOST "sudo systemctl restart ros2-monitor"
done
```
- [ ] Создать deploy.sh
- [ ] Протестировать на двух устройствах

#### 2.2 Ansible структура
```
ansible/
├── inventory/
│   └── production.ini
├── roles/
│   └── ros2-monitor/
│       ├── tasks/main.yml
│       └── templates/
│           ├── ros2-monitor.service.j2
│           └── config.yaml.j2
├── deploy.yml
├── status.yml
└── rollback.yml
```
- [ ] Создать Ansible структуру
- [ ] Написать deploy.yml playbook
- [ ] Написать status.yml playbook

#### 2.3 Inventory для устройств
```ini
# inventory/production.ini
[trams]
tram_30639 ansible_host=10.0.1.5
tram_30640 ansible_host=10.0.1.6

[trams:vars]
ansible_user=artem
docker_container=tram_autoware
```
- [ ] Создать inventory файл
- [ ] Настроить SSH ключи для доступа

#### 2.4 Тестирование Ansible
```bash
# Проверка доступности
ansible trams -i inventory/production.ini -m ping

# Деплой
ansible-playbook deploy.yml -i inventory/production.ini

# Статус
ansible-playbook status.yml -i inventory/production.ini
```
- [ ] Протестировать деплой на всех устройствах
- [ ] Протестировать откат

### Результат Phase 2
- Ansible playbooks для деплоя
- Документация по добавлению новых устройств
- Проверенный процесс обновления

---

## Phase 3: VPN + Fleet Monitor

**Цель:** Безопасный доступ и централизованный мониторинг.

**Срок:** 3-5 дней

### 3.1 VPN Setup (Tailscale)

#### Задачи
- [ ] Создать Tailscale аккаунт
- [ ] Установить Tailscale на dev-машину
- [ ] Создать auth key для устройств
- [ ] Ansible task для установки Tailscale на устройства

```yaml
# ansible/roles/tailscale/tasks/main.yml
- name: Install Tailscale
  shell: curl -fsSL https://tailscale.com/install.sh | sh

- name: Connect to Tailscale
  shell: tailscale up --authkey={{ tailscale_authkey }} --hostname={{ inventory_hostname }}
```

- [ ] Обновить inventory с Tailscale IP
- [ ] Протестировать доступ через VPN

### 3.2 Fleet Status API

#### Endpoint на устройстве
```python
# server/routers/fleet.py
@router.get("/api/fleet/status")
async def fleet_status():
    return {
        "device": {"id": config.device_id, "name": config.device_name},
        "monitor": {"version": VERSION, "uptime": get_uptime()},
        "autopilot": docker_service.get_status(),
        "alerts": alert_service.get_summary(),
        "timestamp": datetime.now().isoformat()
    }
```
- [ ] Создать /api/fleet/status endpoint
- [ ] Добавить версию монитора в ответ
- [ ] Добавить версию автопилота (из docker image tag)
- [ ] Добавить сводку алертов

### 3.3 Fleet Monitor (простая версия)

#### Структура
```
fleet-monitor/
├── server/
│   ├── main.py
│   ├── services/
│   │   ├── device_registry.py    # Список устройств
│   │   └── health_checker.py     # Опрос устройств
│   └── routers/
│       └── devices.py
└── web/
    └── src/
        └── components/
            └── DeviceList.jsx
```

#### Функционал MVP
- [ ] Список устройств (из конфига)
- [ ] Периодический опрос /api/fleet/status
- [ ] Dashboard со статусами
- [ ] Кнопка "Open" → переход на UI устройства

### Результат Phase 3
- VPN доступ ко всем устройствам
- Fleet Monitor для просмотра статуса флота
- Переход на устройство для детального управления

---

## Phase 4: Scale (100+ устройств)

**Цель:** Масштабирование на большой флот.

**Срок:** Ongoing

### 4.1 Pull-based обновления

```bash
# /opt/ros2-monitor/update.sh (на каждом устройстве)
#!/bin/bash
CURRENT=$(cat /opt/ros2-monitor/VERSION)
LATEST=$(curl -s http://update-server/VERSION)

if [ "$CURRENT" != "$LATEST" ]; then
    # Скачать и установить обновление
fi
```
- [ ] Создать update server
- [ ] Создать update.sh скрипт
- [ ] Добавить в cron на устройствах

### 4.2 Fleet Monitor с управлением деплоем

- [ ] Deployment Plans (какие устройства, какая версия)
- [ ] Canary deployment (обновить 1, потом остальные)
- [ ] Автоматический rollback при ошибках
- [ ] История деплоев

### 4.3 WireGuard вместо Tailscale

- [ ] Развернуть WireGuard сервер
- [ ] Генератор конфигов для устройств
- [ ] Миграция с Tailscale

### 4.4 Алертинг

- [ ] Telegram бот для алертов
- [ ] Slack интеграция
- [ ] Email уведомления
- [ ] Escalation policies

### 4.5 Метрики и аналитика

- [ ] Prometheus метрики на устройствах
- [ ] Grafana dashboard
- [ ] Долгосрочное хранение истории

---

## Чеклист перед каждым Phase

### Phase 1 → Phase 2
- [ ] Production build работает локально
- [ ] systemd сервис запускается
- [ ] Все функции работают через http://localhost:8080

### Phase 2 → Phase 3
- [ ] Ansible деплой работает на 2+ устройствах
- [ ] Документация по добавлению устройств
- [ ] Процедура отката протестирована

### Phase 3 → Phase 4
- [ ] VPN работает стабильно
- [ ] Fleet Monitor показывает все устройства
- [ ] Алерты приходят корректно

---

## Оценка времени

| Phase | Описание | Срок | Трудозатраты |
|-------|----------|------|--------------|
| 1 | Production Build | 1 день | 6-8 часов |
| 2 | Multi-Device Deploy | 2-3 дня | 12-16 часов |
| 3 | VPN + Fleet Monitor | 3-5 дней | 20-30 часов |
| 4 | Scale | ongoing | — |

**Итого до работающей системы на 10 устройствах:** ~2 недели

---

## Приоритеты

### Must Have (Phase 1-2)
- Production build
- Деплой на несколько устройств
- Базовый мониторинг

### Should Have (Phase 3)
- VPN
- Fleet Monitor (просмотр)
- Ansible автоматизация

### Nice to Have (Phase 4)
- Управление деплоем из UI
- Alerting в Telegram
- Метрики Prometheus

---

## Риски и митигация

| Риск | Вероятность | Митигация |
|------|-------------|-----------|
| VPN нестабилен | Средняя | Fallback на прямой SSH |
| Обновление ломает устройство | Средняя | Canary deployment, быстрый rollback |
| Нет доступа к устройству | Низкая | Pull-based обновления |
| 100+ устройств нагружают Fleet Monitor | Низкая | Кэширование, увеличение интервала опроса |

---

## Следующие шаги

1. **Сейчас:** Закончить Phase 0 (текущая разработка)
2. **На этой неделе:** Phase 1 (production build)
3. **На следующей неделе:** Phase 2 (деплой на 2 устройства)
4. **Через 2 недели:** Phase 3 (VPN + Fleet Monitor)
