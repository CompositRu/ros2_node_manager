# ROS2 Node Manager — Roadmap

## UI Architecture: Activity Bar (VS Code style)

Тонкая иконочная полоса слева, переключает контекст всего приложения.
Каждая секция — отдельный "view" со своей левой панелью и контентной областью.

```
┌──┬────────────┬─────────────────────────┐
│  │  Header    │  Status / Controls      │
├──┼────────────┼─────────────────────────┤
│▣ │            │                         │
│▢ │ Left Panel │  Content Area           │
│▢ │ (changes   │  (adapts to section)    │
│▢ │  per icon) │                         │
│▢ │            ├─────────────────────────┤
│  │            │  Bottom Panel           │
└──┴────────────┴─────────────────────────┘

Icons:
 ▣ Nodes       — текущее дерево нод + детали
 ▢ Diagnostics — dashboard-сетка диагностик
 ▢ Topics      — список топиков + echo
 ▢ Services    — список сервисов + вызов
 ▢ System      — метрики приложения + все логи
```

---

## ✅ MVP (v0.1) — Текущая версия

### Реализовано:
- [x] Подключение к локальному Docker контейнеру
- [x] Подключение к удалённому серверу через SSH
- [x] Комбобокс выбора сервера
- [x] Дерево нод по namespace
- [x] Счётчики: total | active | inactive
- [x] Счётчики нод в каждом namespace
- [x] Сохранение состояния нод в JSON файл
- [x] Отображение inactive нод (были раньше, сейчас не запущены)
- [x] Определение типа ноды (lifecycle / regular / unknown)
- [x] Просмотр параметров ноды
- [x] Просмотр subscribers / publishers
- [x] Shutdown для lifecycle нод
- [x] Kill для regular нод (с предупреждением)
- [x] Логи ноды в реальном времени (через /rosout)
- [x] WebSocket для real-time обновлений
- [x] Alert-уведомления (node inactive и другие)
- [x] Resource monitoring endpoint (/api/debug/stats)
- [x] Внешний скрипт мониторинга ресурсов (monitor-resources.sh)

---

## ✅ v0.2 — Activity Bar + App Stats + Logs

Внедрён Activity Bar и секции App Stats / Logs.

### Activity Bar (каркас)
- [x] Компонент ActivityBar — вертикальная иконочная полоса (48px ширина)
- [x] Иконки: Nodes, Logs, App Stats
- [x] Routing по секциям (state, не URL)
- [x] Подсветка активной секции
- [x] Tooltip на hover

### App Stats (секция)
- [x] Секция App Stats в Activity Bar
- [x] Числовые счётчики: CPU%, RSS, Exec, Streams, WS, Uptime, Total commands
- [x] Поллинг /api/debug/stats каждые 5 секунд
- [x] Кнопка-подсказка (?) с описанием метрик

### Unified Logs (секция)
- [x] Секция Logs в Activity Bar
- [x] Unified log stream — все логи со всех нод одним потоком
- [x] WebSocket endpoint /ws/logs/all на бэкенде
- [x] Фильтр по уровню (DEBUG/INFO/WARN/ERROR/FATAL)
- [x] Фильтр по имени ноды
- [x] Pause/Resume, Clear, Auto-scroll

```
┌──┬──────────────────────────────────────┐
│  │  System Monitor                      │
│▢ ├──────────────────────────────────────┤
│▢ │  CPU: 2.3%  |  RSS: 87 MB           │
│▢ │  Exec: 3    |  Streams: 1           │
│▣ │  WS: 3      |  Uptime: 2h 14m      │
│  │  Commands total: 1847               │
│  ├──────────────────────────────────────┤
│  │  All Logs (unified stream)           │
│  │  [Level ▼] [Node filter: ____]      │
│  │  12:01 [sins_engine] INFO msg...    │
│  │  12:01 [lidar_node] WARN msg...     │
│  │  12:02 [imu_driver] ERROR msg...    │
└──┴──────────────────────────────────────┘
```

---

## ✅ v0.3 — Diagnostics

Dashboard-сетка диагностик из /diagnostics топика.

### Dashboard Grid
- [x] Подписка на /diagnostics топик (через exec_stream)
- [x] Парсинг DiagnosticArray сообщений
- [x] Карточки-плитки по компонентам
- [x] Статус-индикатор: OK (green) / WARN (yellow) / ERROR (red) / STALE (gray)
- [x] Ключевая метрика на карточке (частота, температура и т.д.)
- [x] Фильтр по статусу и поиск
- [x] Клик по карточке → детальный вид с историей key-value пар
- [x] Специализированная карточка NDT Scan Matcher с пороговой раскраской метрик
- [x] Специализированная карточка Vector Map Poser (front/rear truck distance)
- [x] Специализированная карточка Bag Recorder с русскими статусами
- [x] Виджеты CPU / GPU / RAM с кольцевыми индикаторами
- [x] Фильтрация шумных диагностик (trajectory_follower, blockage_diag и др.)
- [x] Закреплённые карточки локализации над общей сеткой

```
┌──┬──────────────────────────────────────┐
│  │  Diagnostics Overview                │
│▣ │  Filter: [All ▼] Search: [____]     │
│▢ ├──────────────────────────────────────┤
│▢ │ ┌─────────┐ ┌─────────┐ ┌───────┐  │
│▢ │ │● CPU    │ │● Memory │ │○ Disk │  │
│▢ │ │ 72°C    │ │ 84%     │ │ STALE │  │
│  │ └─────────┘ └─────────┘ └───────┘  │
│  │ ┌─────────┐ ┌─────────┐ ┌───────┐  │
│  │ │● Lidar  │ │● IMU    │ │● GPS  │  │
│  │ │ OK 30Hz │ │ OK 100Hz│ │ WARN  │  │
│  │ └─────────┘ └─────────┘ └───────┘  │
└──┴──────────────────────────────────────┘
```

---

## 🚧 v0.5 — Topics

- [ ] Секция Topics в Activity Bar
- [ ] Список топиков по namespace (дерево)
- [ ] Topic Hz (частота сообщений), мониторинг до 5 топиков
- [ ] Topic Echo с Pause/Resume
- [ ] Topic Info (тип сообщения, publishers, subscribers)
- [ ] Фильтрация полей сообщения (показвать только timastemp например)

---

## 🚧 v0.6 — Log History + Alert History

- [ ] Просмотр истории alert-уведомлений
- [ ] Фильтрация алертов по типу, ноде, времени
- [ ] Сохранение логов в файл (экспорт)
- [ ] Поиск по логам

---

## 🚧 v0.7 — Services + Actions

- [ ] Секция Services в Activity Bar
- [ ] Список сервисов
- [ ] Вызов сервисов из UI (формирование request)
- [ ] Список actions
- [ ] Мониторинг выполнения actions

---

## 🚧 v0.8 — Визуализация графа

- [ ] Граф связей между нодами (как rqt_graph)
- [ ] Интерактивный граф (zoom, pan, select)
- [ ] Фильтрация по namespace
- [ ] Highlight активных соединений
- [ ] Возможно отдельная секция в Activity Bar

---

## 🚧 v0.9 — Улучшения управления нодами

- [ ] Полный lifecycle control: configure → activate → deactivate → shutdown
- [ ] Визуализация lifecycle state machine
- [ ] Групповые операции (выключить все ноды в namespace)
- [ ] Подтверждение опасных действий (modal dialog)
- [ ] История действий (кто/когда выключил ноду)
- [ ] Работа с параметрами: изменение (`ros2 param set`)
- [ ] Экспорт параметров в YAML

---

## 🚧 v1.0 — Production Ready

- [ ] Docker образ для деплоя
- [ ] Docker Compose конфигурация
- [ ] Авторизация (опционально)
- [ ] HTTPS поддержка
- [ ] Полная документация
- [ ] Тесты (unit, integration)
- [ ] CI/CD pipeline

---

## 💡 Идеи на будущее

- [ ] Плагинная архитектура
- [ ] Кастомные виджеты для специфичных типов сообщений
- [ ] Запись и воспроизведение (rosbag интеграция)
- [ ] Мобильная версия UI
- [ ] Prometheus метрики
- [ ] Уведомления (email, Slack, Telegram)
- [ ] Запуск нод (требует хранение launch-конфигов)
- [ ] Sparkline-графики в System Monitor (эволюция от простых счётчиков)
- [ ] Sparkline-графики на карточках диагностик

---

## Известные ограничения

1. **Kill regular нод** — ненадёжен без знания executable name
2. **Запуск нод** — требует хранение launch-конфигураций
3. **Параметры** — некоторые ноды не поддерживают динамическое изменение
4. **SSH** — требует настроенный доступ по ключу или паролю
5. **Один пользователь** — не рассчитано на множественный доступ
