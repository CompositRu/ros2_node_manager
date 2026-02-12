Отличные вопросы! Давай разберём.

## 1. Производительность docker exec

### Текущая проблема

```
User 1: GET /api/nodes/node_a      → docker exec ros2 node info /node_a (2-5 сек)
User 2: GET /api/nodes/node_b      → docker exec ros2 node info /node_b (2-5 сек)
User 3: GET /api/nodes             → docker exec ros2 node list (1-2 сек)
                                      ↓
                              Всё последовательно!
                              Каждый ждёт своей очереди
```

### Реальные замеры

```bash
# Замерим время выполнения команд
time docker exec tram_autoware bash -c 'source /opt/ros/humble/setup.bash && ros2 node list'
time docker exec tram_autoware bash -c 'source /opt/ros/humble/setup.bash && ros2 node info /sensing/lidar/top/rslidar_node'
time docker exec tram_autoware bash -c 'source /opt/ros/humble/setup.bash && ros2 param dump /sensing/lidar/top/rslidar_node'
```

**Типичные результаты:**
| Команда | Время |
|---------|-------|
| ros2 node list | 1-2 сек |
| ros2 node info | 2-4 сек |
| ros2 param dump | 2-5 сек |
| ros2 service list | 3-5 сек |

### Решение: Кэширование + Background refresh

```
┌─────────────────────────────────────────────────────────────────────────┐
│  Backend                                                                │
│                                                                         │
│  ┌─────────────────────────────────────────────────────────────────┐    │
│  │  Cache Layer (in-memory)                                        │    │
│  │                                                                 │    │
│  │  nodes_list:        обновляется каждые 5 сек (background)       │    │
│  │  services_list:     обновляется каждые 30 сек (background)      │    │
│  │  node_info[name]:   TTL 10 сек, обновляется при запросе         │    │
│  │  node_params[name]: TTL 30 сек, обновляется при запросе         │    │
│  └─────────────────────────────────────────────────────────────────┘    │
│                                                                         │
│  User 1 ─► GET /nodes ─► Cache hit ─► Instant response                  │
│  User 2 ─► GET /nodes ─► Cache hit ─► Instant response                  │
│  User 3 ─► GET /nodes ─► Cache hit ─► Instant response                  │
│                                                                         │
│  Background task: ros2 node list ─► Update cache                        │
└─────────────────────────────────────────────────────────────────────────┘
```

**Результат:** Все пользователи получают данные мгновенно из кэша.

---

## 2. Производительность логов

### Текущая проблема

```
Сейчас: ros2 topic echo /rosout → ВСЕ логи ВСЕХ нод

User 1: хочет логи /sensing/lidar/*
User 2: хочет логи /planning/*
User 3: хочет логи /control/*

Каждый получает ВСЁ и фильтрует на клиенте → Лишний трафик
```

### Решение: Один поток логов, серверная фильтрация

```
┌─────────────────────────────────────────────────────────────────────────┐
│  Backend                                                                │
│                                                                         │
│  ┌─────────────────────────────────────────────────────────────────┐    │
│  │  LogCollector (один процесс)                                    │    │
│  │                                                                 │    │
│  │  ros2 topic echo /rosout ─► Ring Buffer (1000 сообщений)       │    │
│  └───────────────────────────────┬─────────────────────────────────┘    │
│                                  │                                      │
│                    ┌─────────────┼─────────────┐                       │
│                    ▼             ▼             ▼                       │
│              ┌──────────┐ ┌──────────┐ ┌──────────┐                    │
│              │ User 1   │ │ User 2   │ │ User 3   │                    │
│              │ WS conn  │ │ WS conn  │ │ WS conn  │                    │
│              │          │ │          │ │          │                    │
│              │ filter:  │ │ filter:  │ │ filter:  │                    │
│              │ /sensing │ │ /planning│ │ /control │                    │
│              └──────────┘ └──────────┘ └──────────┘                    │
│                                                                         │
│  Сервер фильтрует и отправляет только нужные логи каждому             │
└─────────────────────────────────────────────────────────────────────────┘
```

**Ключевые моменты:**
- Один `ros2 topic echo /rosout` на весь сервер
- Каждое WebSocket соединение имеет свой фильтр
- Фильтрация на сервере, а не на клиенте
- Ring buffer для истории (можно показать последние N сообщений при подключении)

---

## 3. Изоляция UI между пользователями

### Проблема

```
User 1: выбрал ноду /sensing/lidar/top/rslidar_node
User 2: выбрал ноду /planning/mission_planner

Если состояние на сервере — они будут видеть одно и то же!
```

### Решение: Состояние на клиенте

```
┌─────────────────────────────────────────────────────────────────────────┐
│  Архитектура состояния                                                  │
│                                                                         │
│  Server State (общее для всех):         Client State (у каждого своё): │
│  ├── nodes_cache                        ├── selectedNode               │
│  ├── services_cache                     ├── expandedNamespaces         │
│  ├── logs_buffer                        ├── logFilter                  │
│  └── alerts                             ├── panelSizes                 │
│                                         └── viewSettings               │
│                                                                         │
│  API: stateless                         UI: stateful per browser       │
│  GET /api/nodes → всегда одинаково      React state → у каждого своё  │
└─────────────────────────────────────────────────────────────────────────┘
```

**Текущая реализация уже правильная:**
- Выбранная нода — в React state
- Раскрытые namespace — в React state
- Размеры панелей — в React state
- Фильтр логов — в React state

**Что нужно добавить:**
- Фильтр логов передаётся на сервер при WebSocket подключении
- Сервер фильтрует и отправляет только релевантные логи

---

## 4. Реализация многопользовательского режима

### 4.1 WebSocket с фильтром

```python
# server/routers/logs.py
@router.websocket("/ws/logs")
async def logs_websocket(
    websocket: WebSocket,
    nodes: Optional[str] = Query(None),  # /sensing/lidar/*,/planning/*
    level: Optional[str] = Query(None),  # error,warn
):
    await websocket.accept()
    
    # Парсим фильтры
    node_patterns = nodes.split(",") if nodes else None
    log_levels = level.split(",") if level else None
    
    # Подписываемся на логи с фильтром
    subscription_id = log_service.subscribe(
        callback=lambda msg: send_if_matches(websocket, msg, node_patterns, log_levels)
    )
    
    try:
        while True:
            # Клиент может обновить фильтр
            data = await websocket.receive_json()
            if data.get("action") == "update_filter":
                node_patterns = data.get("nodes")
                log_levels = data.get("levels")
    finally:
        log_service.unsubscribe(subscription_id)
```

### 4.2 Улучшенный LogService

```python
# server/services/log_service.py
class LogService:
    def __init__(self):
        self.buffer = deque(maxlen=1000)  # Ring buffer
        self.subscribers: Dict[str, Callable] = {}
        self._collector_task = None
    
    async def start(self):
        """Запускается один раз при старте сервера."""
        self._collector_task = asyncio.create_task(self._collect_logs())
    
    async def _collect_logs(self):
        """Один процесс собирает все логи."""
        async for log_entry in self.conn.ros2_topic_echo_stream("/rosout"):
            # Добавляем в буфер
            self.buffer.append(log_entry)
            
            # Рассылаем подписчикам
            for callback in self.subscribers.values():
                try:
                    await callback(log_entry)
                except:
                    pass
    
    def subscribe(self, callback: Callable) -> str:
        sub_id = str(uuid.uuid4())
        self.subscribers[sub_id] = callback
        return sub_id
    
    def unsubscribe(self, sub_id: str):
        self.subscribers.pop(sub_id, None)
    
    def get_recent(self, count: int = 100) -> List[dict]:
        """Получить последние N логов (для новых подключений)."""
        return list(self.buffer)[-count:]
```

### 4.3 Кэширование с TTL

```python
# server/services/cache_service.py
from datetime import datetime, timedelta
from typing import Optional, Any
import asyncio

class CacheService:
    def __init__(self):
        self._cache: Dict[str, tuple[Any, datetime]] = {}
        self._locks: Dict[str, asyncio.Lock] = {}
    
    async def get_or_fetch(
        self,
        key: str,
        fetch_fn: Callable,
        ttl_seconds: int = 10
    ) -> Any:
        """Получить из кэша или выполнить fetch_fn."""
        
        # Проверяем кэш
        if key in self._cache:
            value, expires_at = self._cache[key]
            if datetime.now() < expires_at:
                return value
        
        # Получаем lock для этого ключа
        if key not in self._locks:
            self._locks[key] = asyncio.Lock()
        
        async with self._locks[key]:
            # Повторная проверка после получения lock
            if key in self._cache:
                value, expires_at = self._cache[key]
                if datetime.now() < expires_at:
                    return value
            
            # Fetch и сохранение
            value = await fetch_fn()
            self._cache[key] = (value, datetime.now() + timedelta(seconds=ttl_seconds))
            return value
    
    def invalidate(self, key: str):
        self._cache.pop(key, None)
    
    def invalidate_prefix(self, prefix: str):
        keys_to_remove = [k for k in self._cache if k.startswith(prefix)]
        for key in keys_to_remove:
            self._cache.pop(key, None)

# Использование
cache = CacheService()

async def get_node_detail(node_name: str):
    return await cache.get_or_fetch(
        key=f"node_info:{node_name}",
        fetch_fn=lambda: conn.ros2_node_info(node_name),
        ttl_seconds=10
    )
```

### 4.4 Background refresh для критичных данных

```python
# server/services/node_service.py
class NodeService:
    def __init__(self):
        self._refresh_task = None
    
    async def start_background_refresh(self):
        """Запускается при старте сервера."""
        self._refresh_task = asyncio.create_task(self._refresh_loop())
    
    async def _refresh_loop(self):
        while True:
            try:
                # Обновляем список нод каждые 5 секунд
                await self.refresh_nodes()
                
                # Обновляем список сервисов каждые 30 секунд
                if int(time.time()) % 30 == 0:
                    await self.conn._refresh_services_cache()
                    
            except Exception as e:
                print(f"Background refresh error: {e}")
            
            await asyncio.sleep(5)
```

---

## 5. Итоговая архитектура для многопользовательского режима

```
┌─────────────────────────────────────────────────────────────────────────┐
│  Server                                                                 │
│                                                                         │
│  ┌─────────────────────────────────────────────────────────────────┐    │
│  │  Background Tasks (запускаются один раз)                        │    │
│  │  ├── NodeRefreshTask: ros2 node list (каждые 5 сек)            │    │
│  │  ├── ServiceRefreshTask: ros2 service list (каждые 30 сек)     │    │
│  │  └── LogCollectorTask: ros2 topic echo /rosout (постоянно)     │    │
│  └─────────────────────────────────────────────────────────────────┘    │
│                                                                         │
│  ┌─────────────────────────────────────────────────────────────────┐    │
│  │  Cache Layer                                                    │    │
│  │  ├── nodes_list (TTL: 5s, auto-refresh)                        │    │
│  │  ├── services_list (TTL: 30s, auto-refresh)                    │    │
│  │  ├── node_info[name] (TTL: 10s, on-demand)                     │    │
│  │  └── node_params[name] (TTL: 30s, on-demand)                   │    │
│  └─────────────────────────────────────────────────────────────────┘    │
│                                                                         │
│  ┌─────────────────────────────────────────────────────────────────┐    │
│  │  Log Buffer (Ring Buffer, 1000 messages)                        │    │
│  │  └── Subscribers: [User1, User2, User3, ...]                   │    │
│  └─────────────────────────────────────────────────────────────────┘    │
│                                                                         │
│  API Endpoints (stateless):                                            │
│  ├── GET /api/nodes         → Cache hit (instant)                     │
│  ├── GET /api/nodes/{name}  → Cache or fetch (0-10s)                  │
│  └── WS /ws/logs?nodes=...  → Filtered stream                         │
│                                                                         │
└─────────────────────────────────────────────────────────────────────────┘
         │              │              │
         ▼              ▼              ▼
    ┌─────────┐   ┌─────────┐   ┌─────────┐
    │ User 1  │   │ User 2  │   │ User 3  │
    │         │   │         │   │         │
    │ Browser │   │ Browser │   │ Browser │
    │ State:  │   │ State:  │   │ State:  │
    │ -select │   │ -select │   │ -select │
    │ -filter │   │ -filter │   │ -filter │
    └─────────┘   └─────────┘   └─────────┘
    
    Каждый видит своё, данные общие из кэша
```

---

## 6. Нагрузочные характеристики

| Параметр | Без оптимизации | С оптимизацией |
|----------|-----------------|----------------|
| GET /api/nodes | 1-2 сек | <10 мс (кэш) |
| GET /api/nodes/{name} | 2-5 сек | <10 мс (кэш) или 2-5 сек (miss) |
| WebSocket /ws/logs | N процессов ros2 | 1 процесс ros2 |
| Макс. одновременных пользователей | ~5 | ~50 |
| docker exec в секунду | ~1 | ~0.2 (background) |

---

## 7. Что нужно сделать

### Приоритет 1: Кэширование (Phase 1)
- [ ] CacheService с TTL
- [ ] Background refresh для nodes и services
- [ ] Кэширование node_info и params

### Приоритет 2: Улучшение логов (Phase 1)
- [ ] Один LogCollector процесс
- [ ] Ring buffer
- [ ] Серверная фильтрация по WebSocket параметрам

### Приоритет 3: UI фильтры (Phase 2)
- [ ] Выбор нод для логов в UI
- [ ] Выбор уровня логов (error/warn/info)
- [ ] Передача фильтра на сервер

---