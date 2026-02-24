# Обзор диагностик проекта TRAM Autoware

---

## 1. GNSS overlay (3D-сцена RViz)

### Файлы
- Плагин RViz: `src/ui/tram_driver_rviz_plugins/src/gnss_plugin.cpp`
- Бэкенд: `src/system/ui_indicators_backend/src/ui_indicators_backend.cpp`
- Сообщение: `src/common/tram_msgs/tram_display_msgs/msg/GnssDisplayStatus.idl`

### Поток данных
```
nav_msgs/Odometry (~/sub/gnss)           ─┐
                                           ├─→ UiIndicatorsBackend ──→ /display/gnss_status ──→ gnss_plugin (RViz overlay)
tram_localization_msgs/NavGnss (~/sub/nav_gnss) ─┘
```

### Подписки бэкенда (`ui_indicators_backend`)

| Топик | Тип сообщения | Какие поля читает |
|---|---|---|
| `~/sub/gnss` | `nav_msgs::msg::Odometry` | `header.stamp` — для определения потери сигнала (таймаут > 0.5 сек) |
| `~/sub/nav_gnss` | `tram_localization_msgs::msg::NavGnss` | `position_type.type` — тип позиционирования (RTK_FIX и др.) |

### Логика определения статуса (бэкенд)

| Условие | Статус |
|---|---|
| Таймаут Odometry > 0.5 сек ИЛИ `nav_gnss_msg_` == nullptr | **NO_SIGNAL** |
| `position_type.type == RTK_FIX` | **RTK** |
| `position_type.type != RTK_FIX` | **AUTONOMOUS** |

### Логика окраски текста "GNSS" (плагин RViz)

| Статус | Цвет | Поведение |
|---|---|---|
| **ERROR** (0) | Красный `#FF0000` | Статичный |
| **NO_SIGNAL** (1) | Мигание красный ↔ оранжевый | Переключение каждые 0.5 сек |
| **AUTONOMOUS** (2) | Оранжевый `#FFA500` | Статичный |
| **RTK** (3) | Зелёный `RGB(144, 238, 144)` | Статичный |

Шрифт: Arial 20pt Bold, alpha 200/255. Позиция: left=5, top=5.

---

## 2. MRM overlay (3D-сцена RViz)

### Файлы
- Плагин RViz: `src/ui/tram_driver_rviz_plugins/src/mrm_plugin.cpp`
- Бэкенд: `src/system/ui_indicators_backend/src/ui_indicators_backend.cpp`
- Сообщение: `src/common/tram_msgs/tram_display_msgs/msg/MrmDisplayStatus.idl`

### Поток данных
```
autoware_adapi_v1_msgs/MrmState (~/sub/mrm_state) ──→ UiIndicatorsBackend ──→ /display/mrm_status ──→ mrm_plugin (RViz overlay)
```

### Подписки бэкенда (`ui_indicators_backend`)

| Топик | Тип сообщения | Какие поля читает |
|---|---|---|
| `~/sub/mrm_state` | `autoware_adapi_v1_msgs::msg::MrmState` | `state` — текущее состояние MRM |

### Логика определения статуса (бэкенд)

| Входное значение `MrmState.state` | Выходной статус `MrmDisplayStatus` |
|---|---|
| `NORMAL` | **NORMAL** |
| `MRM_OPERATING` | **OPERATING** |
| `MRM_SUCCEEDED` | **SUCCEEDED** |
| `MRM_FAILED` | **FAILED** |
| Любое другое | **ERROR** |

### Логика окраски текста "MRM" (плагин RViz)

| Статус | Цвет | Поведение |
|---|---|---|
| **NORMAL** (0) | Зелёный `RGB(144, 238, 144)` | Статичный |
| **ERROR** (1) | Красный `#FF0000` | Статичный |
| **OPERATING** (2) | Оранжевый `#FFA500` | Статичный |
| **SUCCEEDED** (3) | Мигание красный ↔ зелёный | Переключение каждые 0.5 сек |
| **FAILED** (4) | Мигание красный ↔ оранжевый | Переключение каждые 0.5 сек |

Шрифт: Arial 20pt Bold, alpha 200/255. Позиция: left=5, top=30.

---

## 3. CPU Monitor

### Файлы
- `src/system/system_monitor/src/cpu_monitor/`
- Публикует в `/diagnostics` через `diagnostic_updater`
- Дополнительный топик: `~/cpu_usage`

### Диагностические задачи

#### 3.1 CPU Temperature
**Источник данных:** sysfs thermal zones (платформо-зависимо: Intel coretemp, ARM, Tegra `CPU-therm`)

**Поля диагностики (per-core):**
- Метка ядра: `"%.1f DegC"`

**Статус:** всегда OK (ERROR только если не удалось прочитать файл температуры).

#### 3.2 CPU Usage
**Источник данных:** команда `mpstat -P ALL 1 1 -o JSON`

**Читаемые поля из JSON:**
- `cpu` — имя ядра ("all", "0", "1", ...)
- `usr` — пользовательская нагрузка (%)
- `nice` — nice (%)
- `sys` — системная (%)
- `idle` — простой (%)
- `iowait` — ожидание I/O (%)
- Вычисляемое: `total = 100.0 - iowait - idle`
- Вычисляемое: `usage = total / 100.0`

**Поля диагностики (per-CPU):**
- `CPU {name}: status`, `CPU {name}: total`, `CPU {name}: usr`, `CPU {name}: nice`, `CPU {name}: sys`, `CPU {name}: idle`, `CPU {name}: iowait`

**Параметры и пороги:**

| Параметр | По умолчанию | Описание |
|---|---|---|
| `usage_warn_` | 0.96 (96%) | Порог для WARN |
| `usage_error_` | 0.96 (96%) | Порог для ERROR |
| `usage_warn_count_` | 1 | Подряд превышений для WARN |
| `usage_error_count_` | 2 | Подряд превышений для ERROR |
| `usage_avg_` | true | Использовать "all" или максимум по ядрам |

**Логика статуса:**
- **OK:** `usage < usage_warn_`
- **WARN:** `usage >= usage_warn_` в течение `usage_warn_count_` подряд замеров
- **ERROR:** `usage >= usage_error_` в течение `usage_error_count_` подряд замеров
- Счётчик сбрасывается при падении нагрузки ниже порога

#### 3.3 CPU Load Average
**Источник данных:** `/proc/loadavg`

**Поля диагностики:**
- `1min` — "%.2f%%" (нормализовано на число ядер)
- `5min` — "%.2f%%"
- `15min` — "%.2f%%"

**Статус:** всегда OK.

#### 3.4 CPU Thermal Throttling
**Источник данных:** MSR-регистры CPU (Intel — через сервис на порту 7634)

**Статус:**
- **OK:** нет троттлинга
- **ERROR:** обнаружен троттлинг

#### 3.5 CPU Frequency
**Источник данных:** `/sys/devices/system/cpu/cpu{N}/cpufreq/scaling_cur_freq`

**Поля диагностики:**
- `CPU {index}: clock` — "%d MHz"

**Статус:** всегда OK.

---

## 4. GPU Monitor

### Файлы
- `src/system/system_monitor/src/gpu_monitor/`
- Две реализации: NVML (десктопные GPU) и Tegra (Jetson)

### Общие параметры и пороги

| Параметр | По умолчанию | Описание |
|---|---|---|
| `temp_warn_` | 90.0°C | Порог температуры для WARN |
| `temp_error_` | 95.0°C | Порог температуры для ERROR |
| `gpu_usage_warn_` | 0.90 (90%) | Порог использования GPU для WARN |
| `gpu_usage_error_` | 1.00 (100%) | Порог использования GPU для ERROR |
| `memory_usage_warn_` | 0.95 (95%) | Порог памяти GPU для WARN |
| `memory_usage_error_` | 0.99 (99%) | Порог памяти GPU для ERROR |

### Диагностические задачи (NVML)

#### 4.1 GPU Temperature
**Источник:** NVML API `nvmlDeviceGetTemperature()`

**Статус:**
- **OK:** `temp < 90°C`
- **WARN:** `temp >= 90°C`
- **ERROR:** `temp >= 95°C`

#### 4.2 GPU Usage
**Источник:** NVML API `nvmlDeviceGetUtilizationRates()` → поле `utilization.gpu` (0–100)

**Поля диагностики (per-GPU):**
- `GPU {i}: status`, `GPU {i}: name`, `GPU {i}: usage` — "%d.0%%"
- Попроцессно: `GPU {i}: process {N}: pid`, `name`, `usage`

**Статус:**
- **OK:** `usage < 90%`
- **WARN:** `usage >= 90%`
- **ERROR:** `usage >= 100%`

#### 4.3 GPU Memory Usage
**Источник:** NVML API `nvmlDeviceGetMemoryInfo()` → `memory.total`, `memory.used`, `memory.free`

**Поля диагностики:**
- `GPU {i}: status`, `name`, `usage`, `total`, `used`, `free`

**Статус:**
- **OK:** `usage < 95%`
- **WARN:** `usage >= 95%`
- **ERROR:** `usage >= 99%`

#### 4.4 GPU Thermal Throttling
**Источник:** NVML API `nvmlDeviceGetCurrentClocksThrottleReasons()`

**Статус:**
- **OK:** GpuIdle, ApplicationsClocksSetting, SwPowerCap
- **ERROR:** HwSlowdown, SyncBoost, SwThermalSlowdown, HwThermalSlowdown, HwPowerBrakeSlowdown, DisplayClockSetting

**Поля:** `GPU {i}: status`, `name`, `graphics clock`, `reasons` (список причин через запятую)

#### 4.5 GPU Frequency
**Источник:** NVML API `nvmlDeviceGetClockInfo(NVML_CLOCK_GRAPHICS)`

**Статус:**
- **OK:** текущая частота в списке поддерживаемых
- **WARN:** текущая частота НЕ в списке поддерживаемых

### Tegra-специфика
- Температура: sysfs thermal zone `GPU-therm`; пороги те же (90/95°C)
- Usage: `/sys/devices/gpu.{N}/load` (значение / 1000 = доля); пороги те же
- Memory Usage: отсутствует (CPU/GPU делят память)
- Throttling: отсутствует

---

## 5. Memory Monitor

### Файлы
- `src/system/system_monitor/src/mem_monitor/`

### Диагностические задачи

#### 5.1 Memory Usage
**Источник данных:** команда `free -tb`

**Поля диагностики:**
- `Mem: usage` — "%.2f%%"
- `Mem: total`, `used`, `free`, `shared`, `buff/cache`, `available` — human-readable (B/K/M/G/T)
- `Swap: total`, `used`, `free`
- `Total: total`, `used`, `free`
- `Total: used+` — "{:.1f}G" (Total:used + Mem:shared)

**Параметр:**

| Параметр | По умолчанию | Описание |
|---|---|---|
| `available_size_` | 1024 MB | Минимум свободной памяти |

**Расчёт:** `usage = 1.0 - (available_memory / total_memory)`

**Логика статуса:**
- **OK:** `mem_total > used_plus` — "OK"
- **WARN:** `used_plus >= mem_total` И `mem_available >= 1024 MB` — "high load"
- **ERROR:** `used_plus >= mem_total` И `mem_available < 1024 MB` — "very high load"

#### 5.2 Memory ECC
**Источник:** команда `edac-util --quiet`

**Статус:**
- **OK:** нет вывода
- **WARN:** вывод содержит "Corrected"
- **ERROR:** вывод содержит "Uncorrected"

---

## 6. Localization Diagnostics

### Файлы
- `src/localization/localization_diagnostics/`

### Подписки и публикации

| Направление | Топик | Тип сообщения |
|---|---|---|
| Подписка | `~/sub/sum_diagnostics` | `diagnostic_msgs::msg::DiagnosticArray` |
| Публикация | `~/pub/status` | `tram_common_msgs::msg::ModuleStatus` |

### Параметры

```yaml
publish_rate_hz: 10.0
monitored_modules: ['ndt_scan_matcher', 'vector_map_poser']
module_timeout_sec: 1.0
```

### Мониторинг NDT Scan Matcher

**Читаемые поля из DiagnosticStatus (key-value):**
- `iteration_num` (int) — число итераций сопоставления
- `skipping_publish_num` (int) — число пропущенных публикаций
- `nearest_voxel_transformation_likelihood` (double) — оценка правдоподобия
- `transform_probability` (double) — вероятность трансформации

**Пороги:**

| Параметр | Значение |
|---|---|
| `iteration_num_warn_threshold` | 10 |
| `iteration_num_err_threshold` | 15 |
| `skipping_publish_num_warn_threshold` | 7 |
| `transform_probability_err_threshold` | 8.0 |
| `transformation_likelihood_err_threshold` | 4.5 |

**Логика статуса:**
- **STALE:** нет обновлений > `module_timeout_sec` (1 сек)
- **ERROR:** `iteration_num > 15` И (`transform_probability < 8.0` ИЛИ `likelihood < 4.5`)
- **WARN:** `iteration_num > 10`, ИЛИ `skipping_publish_num > 7`, ИЛИ (`iteration_num <= 15` И низкая вероятность/правдоподобие)
- **OK:** во всех остальных случаях

### Мониторинг Vector Map Poser

**Читаемые поля из DiagnosticStatus:**
- `state` (string) — состояние
- `timestamp_solution` (double) — метка времени решения
- `front_truck_distance` (double) — расстояние до переднего края (м)
- `rear_truck_distance` (double) — расстояние до заднего края (м)

**Пороги:**

| Параметр | Значение |
|---|---|
| `front_truck_distance_warn_threshold` | 0.5 м |
| `front_truck_distance_err_threshold` | 1.0 м |

**Логика статуса:**
- **STALE:** нет обновлений > 1 сек ИЛИ устаревший `timestamp_solution`
- **ERROR:** `front_truck_distance > 1.0 м`
- **WARN:** `front_truck_distance > 0.5 м`
- **OK:** во всех остальных случаях

### Агрегированный статус модуля
- Все модули OK → **OK**
- Все модули ERROR → **ERROR**
- Хотя бы один WARN или ERROR → **WARN**
- Хотя бы один STALE (без ошибок) → **STALE**

---

## 7. Localization Error Monitor

### Файлы
- `src/localization/localization_error_monitor/`

### Подписки и публикации

| Направление | Топик | Тип сообщения |
|---|---|---|
| Подписка | `input/odom` | `nav_msgs::msg::Odometry` |
| Публикация | `debug/ellipse_marker` | `visualization_msgs::msg::Marker` (durable QoS) |
| Диагностика | `/diagnostics` | через `diagnostic_updater` |

### Читаемые поля из Odometry
- `pose.covariance` — матрица ковариации 6x6; используется подматрица XY 2x2
- Вычисляются собственные значения → радиусы эллипса ошибки
- `scale` (параметр, default: 3.0) × √(максимальное собственное значение) = `long_radius`
- Проекция ковариации на body frame → `size_lateral_direction`

### Диагностические метрики и пороги

#### `localization_accuracy` (по `long_radius`)

| Статус | Условие |
|---|---|
| **OK** | `long_radius < 0.8 м` |
| **WARN** | `0.8 м <= long_radius < 1.0 м` |
| **ERROR** | `long_radius >= 1.0 м` |

#### `localization_accuracy_lateral_direction` (по `size_lateral_direction`)

| Статус | Условие |
|---|---|
| **OK** | `size_lateral < 0.2 м` |
| **WARN** | `0.2 м <= size_lateral < 0.3 м` |
| **ERROR** | `size_lateral >= 0.3 м` |

### Параметры

| Параметр | По умолчанию |
|---|---|
| `scale` | 3.0 |
| `warn_ellipse_size` | 0.8 м |
| `error_ellipse_size` | 1.0 м |
| `warn_ellipse_size_lateral_direction` | 0.2 м |
| `error_ellipse_size_lateral_direction` | 0.3 м |

Частота обновления: 10 Гц (таймер 100 мс).

---

## 8. System Error Monitor

### Файлы
- `src/system/system_error_monitor/`
- Конфиги required_modules: `src/system/system_error_monitor/config/diagnostic_aggregator/*.param.yaml`

### Подписки и публикации

| Направление | Топик | Тип сообщения |
|---|---|---|
| Подписка | `input/diag_array` | `diagnostic_msgs::msg::DiagnosticArray` |
| Подписка | `~/input/autoware_state` | `autoware_auto_system_msgs::msg::AutowareState` |
| Подписка | `~/input/control_mode` | `autoware_auto_vehicle_msgs::msg::ControlModeReport` |
| Публикация | `~/output/hazard_status` | `autoware_auto_system_msgs::msg::HazardStatusStamped` |
| Публикация | `~/output/diagnostics_err` | `diagnostic_msgs::msg::DiagnosticArray` |
| Публикация | `~/output/error_buffer_status` | `autoware_auto_system_msgs::msg::ErrorBufferStatus` |
| Сервис | `service/clear_emergency` | `std_srvs::srv::Trigger` |

### Уровни диагностик (вход)
```
DiagnosticStatus.level:  0=OK, 1=WARN, 2=ERROR, 3=STALE
```

### Уровни hazard (выход)
```
HazardStatus.level:  0=NO_FAULT, 1=SAFE_FAULT, 2=LATENT_FAULT, 4=SINGLE_POINT_FAULT
```

### Конфигурация модулей

Каждый required module задаёт пороги маппинга:
```yaml
/module/name:
  sf_at: "error"       # Safe Fault при ERROR
  lf_at: "warn"        # Latent Fault при WARN
  spf_at: "error"      # Single Point Fault при ERROR
  auto_recovery: true   # Может ли автовосстановиться
```

### Логика классификации `getHazardLevel()`

Для каждого модуля, при заданном `diag_level`:
1. `diag_level >= spf_at` → **SINGLE_POINT_FAULT**
2. `diag_level >= lf_at` → **LATENT_FAULT**
3. `diag_level >= sf_at` → **SAFE_FAULT**
4. Иначе → **NO_FAULT**

### Error Buffer

Каждая диагностика хранит дек (по умолчанию 10 записей). Буферная классификация:

| Сумма ошибок | Уровень |
|---|---|
| `error_sum >= 30.0` | SINGLE_POINT_FAULT |
| `error_sum >= 20.0` | LATENT_FAULT |
| `(error_sum + safe_fault_sum) >= 10.0` | SAFE_FAULT |
| Иначе | NO_FAULT |

### Общий Hazard Status (`judgeHazardStatus()`)

1. Для каждого required module: получить последнюю диагностику → определить hazard level → распределить по категориям (`diag_no_fault`, `diag_safe_fault`, `diag_latent_fault`, `diag_single_point_fault`)
2. Проверить таймаут диагностики (> `diag_timeout_sec` = 1 сек) → при таймауте → STALE
3. Фильтр по состоянию: если AutowareState ∈ {INITIALIZING, WAITING_FOR_ROUTE, PLANNING, FINALIZING} → override level = NO_FAULT
4. Учесть error buffer: `level = max(current_level, buffer_level)`

### Emergency-логика

- **Активация:** `emergency = (level >= emergency_hazard_level)` (по умолчанию >= LATENT_FAULT)
- **Автовосстановление:** возможно если `duration < hazard_recovery_timeout` (5 сек) И все ошибочные модули имеют `auto_recovery: true`
- **Emergency holding:** `emergency_holding = NOT can_auto_recover` (удерживает аварийное состояние)
- **Ручной сброс:** сервис `clear_emergency`

### Таймаут данных

Если данные не поступают > `data_ready_timeout` (30 сек) или heartbeat > `data_heartbeat_timeout` (1 сек):
- `level = SINGLE_POINT_FAULT`, `emergency = true`
- Создаётся синтетическая диагностика `system_error_monitor/input_data_timeout`

### Ключевые параметры

| Параметр | По умолчанию | Описание |
|---|---|---|
| `update_rate` | 10 Гц | Частота обновления |
| `ignore_missing_diagnostics` | false | Игнорировать отсутствующие диагностики |
| `add_leaf_diagnostics` | true | Включать leaf-диагностики в выход |
| `data_ready_timeout` | 30.0 сек | Таймаут готовности данных |
| `data_heartbeat_timeout` | 1.0 сек | Таймаут heartbeat |
| `diag_timeout_sec` | 1.0 сек | Таймаут отдельной диагностики |
| `hazard_recovery_timeout` | 5.0 сек | Окно автовосстановления |
| `emergency_hazard_level` | LATENT_FAULT | Порог для emergency |
| `error_buffer_capacity` | 10 | Размер буфера ошибок |

### Выходная структура HazardStatusStamped
```
HazardStatusStamped:
  stamp: timestamp
  status:
    level: NO_FAULT | SAFE_FAULT | LATENT_FAULT | SINGLE_POINT_FAULT
    emergency: bool
    emergency_holding: bool
    diag_no_fault: DiagnosticStatus[]
    diag_safe_fault: DiagnosticStatus[]
    diag_latent_fault: DiagnosticStatus[]
    diag_single_point_fault: DiagnosticStatus[]
```

---

## Краткий обзор остальных диагностик

### Мониторинг сенсоров

| Нода | Пакет | Что проверяет |
|---|---|---|
| **velodyne_monitor** | `src/sensing/lidar/velodyne/velodyne_monitor/` | Подключение LiDAR, температура плат, напряжение, RPM мотора |
| **blockage_diag** | `src/sensing/lidar/pointcloud_preprocessor/src/blockage_diag/` | Блокировка/засорение лидара (по облаку точек) |
| **image_diagnostics** | `src/sensing/camera/image_diagnostics/` | Качество камеры: NORMAL, DARK, BLOCKAGE, LOW_VISIBILITY, BACKLIGHT |
| **imu_diagnostics** | `src/system/imu_diagnostics/` | Устаревание данных IMU, угловая скорость |

### Мониторинг нод и топиков

| Нода | Пакет | Что проверяет |
|---|---|---|
| **topic_state_monitor** | `src/system/topic_state_monitor/` | Частота публикации топиков, таймауты (stale data) |
| **node_alive_monitoring** | `src/system/node_alive_monitoring/` | Запущен ли процесс ROS-ноды (проверка /proc) |

### Системный мониторинг (прочее)

| Нода | Пакет | Что проверяет |
|---|---|---|
| **Network Monitor** | `src/system/system_monitor/` | Использование сети, трафик, CRC-ошибки, IP Reassembly |
| **Storage/HDD Monitor** | `src/system/system_monitor/` | Температура, ошибки, скорость I/O, наработка |
| **Process Monitor** | `src/system/system_monitor/` | Процессы с высокой нагрузкой и потреблением памяти |
| **NTP Monitor** | `src/system/system_monitor/` | Смещение NTP (синхронизация часов) |
| **Voltage Monitor** | `src/system/system_monitor/` | Состояние CMOS-батареи |

### TRAM-специфичный мониторинг

| Нода | Пакет | Что проверяет |
|---|---|---|
| **tram_elr_monitoring** | `src/system/tram_elr_monitoring/` | Температура за бортом, уровень песка, тяговые инверторы, статические преобразователи, тормозной резистор |
| **bluetooth_monitor** | `src/system/bluetooth_monitor/` | Bluetooth-устройства (RTT, статус соединения) |

### Обработка и агрегация

| Нода | Пакет | Что делает |
|---|---|---|
| **diagnostic_aggregator** | Конфиги в `src/system/system_error_monitor/config/diagnostic_aggregator/` | Агрегация по модулям: system, vehicle, sensing, perception, localization, planning, control, map, tram_monitoring |
| **diagnostic_converter** | `src/metrics/evaluation/diagnostic_converter/` | Конвертация DiagnosticArray → UserDefinedValue для метрик |
| **dummy_diag_publisher** | `src/system/dummy_diag_publisher/` | Фиктивные диагностики (для тестирования) |

### Отображение в RViz / GUI

| Компонент | Что отображает |
|---|---|
| **DriverResourcePanel** (`src/ui/tram_rviz/src/driver_resource_panel.cpp`) | RViz-панель: CPU/GPU/Nvidia статус ECU0/ECU1, Network RX/TX |
| **diagnostic_tram_app** (`src/system/diagnostic_tram_app/`) | Qt-приложение: дерево диагностик по уровням отказов, логирование в JSON |

---

## Общая архитектура

```
[Ноды диагностик] ──→ /diagnostics (DiagnosticArray)
        ↓
[diagnostic_aggregator] ──→ группировка по модулям
        ↓
[system_error_monitor] ──→ HazardStatus (классификация по уровням опасности)
        ↓
[ui_indicators_backend] ──→ /display/* (упрощённые статусы для UI)
        ↓
[RViz плагины / diagnostic_tram_app] ──→ визуальное отображение
```
