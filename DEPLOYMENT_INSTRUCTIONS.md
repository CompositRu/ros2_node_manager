# Production Deployment - Изменения в коде

## Обзор

При деплое на целевое устройство:
- Вебсервер работает **ВНЕ Docker** на хост-машине
- Использует `docker exec` для общения с ROS2 внутри контейнера
- FastAPI раздаёт собранный React (один порт 8080)
- systemd обеспечивает автозапуск

## Изменения в существующих файлах

### 1. server/main.py

Добавить раздачу статики в конец файла:

```python
# === Static files and SPA routing (Production) ===

from pathlib import Path
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse

# Path to React build
STATIC_DIR = Path(__file__).parent.parent / "web" / "dist"
ASSETS_DIR = STATIC_DIR / "assets"


@app.get("/api/health")
async def health_check():
    """Health check endpoint."""
    return {
        "status": "ok",
        "connected": app_state.connection is not None and app_state.connection._connected,
        "server": app_state.current_server_id,
    }


# Serve static assets if build exists
if ASSETS_DIR.exists():
    app.mount("/assets", StaticFiles(directory=str(ASSETS_DIR)), name="assets")


@app.get("/{full_path:path}")
async def serve_spa(request: Request, full_path: str):
    """Serve React SPA for all non-API routes."""
    # Don't serve SPA for API routes
    if full_path.startswith("api/") or full_path.startswith("ws/"):
        raise HTTPException(status_code=404, detail="Not found")
    
    # Check if static build exists
    index_file = STATIC_DIR / "index.html"
    if not index_file.exists():
        return JSONResponse(
            status_code=200,
            content={"message": "ROS2 Node Manager API", "docs": "/docs", "mode": "development"}
        )
    
    # Try to serve the exact file first
    file_path = STATIC_DIR / full_path
    if file_path.is_file():
        return FileResponse(file_path)
    
    # Otherwise serve index.html (SPA routing)
    return FileResponse(index_file)
```

Добавить импорты в начало:
```python
from fastapi.responses import FileResponse, JSONResponse
```

### 2. Ничего больше менять не нужно!

Текущий код уже работает с локальным Docker через `docker exec`.

## Новые файлы

### deploy/deploy.sh
Основной скрипт деплоя (см. файл)

### deploy/update.sh  
Быстрое обновление кода (см. файл)

### deploy/ros2-monitor.service
systemd unit файл (см. файл)

### deploy/README.md
Документация по деплою (см. файл)

## Структура директории deploy/

Скопируй папку `deploy/` в корень проекта:

```
ros2_node_manager/
├── server/
├── web/
├── config/
├── deploy/           # <-- Новая папка
│   ├── deploy.sh
│   ├── update.sh
│   ├── ros2-monitor.service
│   └── README.md
└── ...
```

## Использование

### Первый деплой:
```bash
cd ros2_node_manager
./deploy/deploy.sh 192.168.1.10 ubuntu
```

### Обновление:
```bash
./deploy/update.sh 192.168.1.10 ubuntu
```

### После деплоя:
- UI доступен: http://192.168.1.10:8080
- Логи: `ssh ubuntu@192.168.1.10 'journalctl -u ros2-monitor -f'`
