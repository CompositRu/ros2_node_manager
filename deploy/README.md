# ROS2 Node Manager - Production Deployment

## Структура на целевом устройстве

```
/opt/ros2-monitor/
├── server/                 # Python backend
│   ├── main.py
│   ├── requirements.txt
│   └── ...
├── web/
│   └── dist/               # Собранный React frontend
│       ├── index.html
│       └── assets/
├── config/
│   └── servers.yaml        # Конфигурация
├── data/                   # Персистентные данные
├── deploy/
│   ├── ros2-monitor.service
│   └── *.sh
└── .venv/                  # Python virtual environment
```

## Быстрый старт

### 1. Первоначальный деплой

```bash
# На dev-машине, из директории ros2_node_manager:
./deploy/deploy.sh 192.168.1.10 ubuntu
```

Скрипт автоматически:
- Соберёт React frontend
- Скопирует файлы на сервер
- Создаст Python virtual environment
- Установит systemd service
- Запустит приложение

### 2. Обновление кода

После первоначального деплоя для быстрого обновления:

```bash
./deploy/update.sh 192.168.1.10 ubuntu
```

## Управление сервисом

### На целевом устройстве:

```bash
# Статус
sudo systemctl status ros2-monitor

# Логи (follow)
sudo journalctl -u ros2-monitor -f

# Логи (последние 100 строк)
sudo journalctl -u ros2-monitor -n 100

# Перезапуск
sudo systemctl restart ros2-monitor

# Остановка
sudo systemctl stop ros2-monitor

# Запуск
sudo systemctl start ros2-monitor

# Отключить автозапуск
sudo systemctl disable ros2-monitor

# Включить автозапуск
sudo systemctl enable ros2-monitor
```

### С dev-машины:

```bash
HOST=192.168.1.10
USER=ubuntu

# Статус
ssh $USER@$HOST 'sudo systemctl status ros2-monitor'

# Логи
ssh $USER@$HOST 'sudo journalctl -u ros2-monitor -f'

# Перезапуск
ssh $USER@$HOST 'sudo systemctl restart ros2-monitor'
```

## Конфигурация

### /opt/ros2-monitor/config/servers.yaml

```yaml
servers:
  - id: local
    name: "Autopilot"
    type: local
    container: tram_autoware    # Имя Docker контейнера

alerts:
  enabled: true
  cooldown_seconds: 60
  
  important_topics:
    - /sensing/lidar/concatenated/pointcloud
    - /localization/kinematic_state
  
  error_patterns:
    - pattern: "FATAL"
      severity: critical
```

После изменения конфига перезапустите сервис:
```bash
sudo systemctl restart ros2-monitor
```

## Требования к целевому устройству

- Ubuntu 20.04+ / Debian 11+
- Python 3.10+
- Docker (с контейнером автопилота)
- rsync (для деплоя)

### Установка зависимостей (если нет):

```bash
sudo apt update
sudo apt install -y python3 python3-venv python3-pip rsync
```

## Доступ

После деплоя UI доступен по адресу:
```
http://<device-ip>:8080
```

## Troubleshooting

### Сервис не запускается

```bash
# Проверить логи
sudo journalctl -u ros2-monitor -n 50

# Проверить что venv создан
ls -la /opt/ros2-monitor/.venv/

# Попробовать запустить вручную
cd /opt/ros2-monitor
.venv/bin/python -m uvicorn server.main:app --host 0.0.0.0 --port 8080
```

### Docker контейнер не найден

Проверьте имя контейнера в `config/servers.yaml`:
```bash
docker ps --format '{{.Names}}'
```

### Порт 8080 занят

Изменить порт в `/etc/systemd/system/ros2-monitor.service`:
```ini
ExecStart=... --port 8081
```

И перезагрузить:
```bash
sudo systemctl daemon-reload
sudo systemctl restart ros2-monitor
```

## Обновление на нескольких устройствах

```bash
# Список устройств
HOSTS="192.168.1.10 192.168.1.11 192.168.1.12"

# Обновить все
for HOST in $HOSTS; do
    echo "=== Updating $HOST ==="
    ./deploy/update.sh $HOST ubuntu
done
```

## Версия

Текущая версия отображается в footer UI.

Для изменения версии отредактируйте `web/src/App.jsx`:
```jsx
<span>ROS2 Node Manager v1.0.0</span>
```
