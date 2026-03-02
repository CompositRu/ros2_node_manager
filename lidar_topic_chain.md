# Lidar Pipeline: Topic Chain from rslidar_packets to /sensing/lidar/concatenated/pointcloud

## Overview

The lidar pipeline processes raw packet data from RoboSense lidars through a series of
filtering/preprocessing nodes, then concatenates point clouds from all sensors into a single
unified point cloud.

**Launch orchestration:**
- `sensing.launch.py` -> per-sensor `robosense.launch.xml` -> `robosense_filters.launch.py`
- `sensing.launch.py` -> `common.launch.xml` -> `pointcloud_merger.launch.py`

**Namespace structure:** `/sensing/lidar/{sensor_id}/...`

Sensors (example for vehicle 30618): `front`, `front_left`, `front_right`, `top`

---

## Full Topic Chain (per sensor, on example of `front`)

```
                              +-----------------------+
  UDP packets (hardware)      | msg_source: 1 (online)|
  or                     ---> | RSLidarSDKComponent   |
  rslidar_packets (ROS)       | msg_source: 2 (ROS)  |
                              +-----------------------+
                                        |
                                        | publishes
                                        v
                  /sensing/lidar/front/pointcloud_raw_ex
                          [sensor_msgs/PointCloud2]
                                        |
                          +-------------+-------------+
                          |                           |
                   (mr_filter=true)            (mr_filter=false)
                          |                           |
                          v                           |
          +-------------------------------+           |
          | MirrorReflectionFilterComponent|          |
          | name: mirror_reflection_filter|           |
          +-------------------------------+           |
                          |                           |
                          v                           |
   /sensing/lidar/front/mr_filtered/pointcloud_ex     |
                          |                           |
                          +-------------+-------------+
                                        |
                                        v
                  +-------------------------------+
                  | CropBoxFilterComponent        |
                  | name: ego_crop_box_filter     |
                  | (removes ego-vehicle points)  |
                  +-------------------------------+
                                        |
                                        v
              /sensing/lidar/front/ego_cropped/pointcloud_ex
                                        |
                                        v
                  +-------------------------------+
                  | DistortionCorrectorComponent  |
                  | name: distortion_corrector_node|
                  +-------------------------------+
                  | extra inputs:                 |
                  |  ~/input/kinematic_state      |
                  |    <- /localization/           |
                  |       kinematic_state          |
                  |  ~/input/imu                  |
                  |    <- /sensing/imu/central/imu_|
                  +-------------------------------+
                                        |
                                        v
              /sensing/lidar/front/rectified/pointcloud_ex
                                        |
                                        v
                  +--------------------------------------+
                  | ConvertXyzirToXyziradtFilterComponent|
                  | name: convert_filter                 |
                  | (XYZIR -> XYZIRADT format)           |
                  +--------------------------------------+
                                        |
                                        v
              /sensing/lidar/front/converted/pointcloud_ex
                                        |
                                        v
                  +-------------------------------+
                  | RingOutlierFilterComponent    |
                  | name: ring_outlier_filter     |
                  +-------------------------------+
                                        |
                                        v
            /sensing/lidar/front/outlier_filtered/pointcloud
                                        |
                                        |  (same chain runs in parallel
                                        |   for each sensor: front, front_left,
                                        |   front_right, top, ...)
                                        v
       +---------------------------------------------------------+
       | PointCloudConcatenateDataSynchronizerComponent          |
       | name: concatenate_filter                                |
       | namespace: /sensing/lidar/concatenated/                 |
       +---------------------------------------------------------+
       | input_topics:                                           |
       |   - /sensing/lidar/front/outlier_filtered/pointcloud    |
       |   - /sensing/lidar/front_left/outlier_filtered/pointcloud|
       |   - /sensing/lidar/front_right/outlier_filtered/pointcloud|
       |   - /sensing/lidar/top/outlier_filtered/pointcloud      |
       | extra input:                                            |
       |   ~/input/twist <- /sensing/vehicle_velocity_converter/ |
       |                    twist_with_covariance                |
       +---------------------------------------------------------+
                                        |
                                        v
              /sensing/lidar/concatenated/pointcloud
                        [sensor_msgs/PointCloud2]
```

---

## Step-by-Step Details

### Step 1: RSLidarSDK Driver

| | |
|---|---|
| **Package** | `rslidar_sdk` |
| **Plugin** | `robosense::lidar::RSLidarSDKComponent` |
| **Node name** | `rslidar_node` |
| **Config** | per-sensor YAML (e.g. `tram_param/config/tram/30618/sensing/lidar_robosense_front_config.yaml`) |
| **Launch file** | `robosense_filters.launch.py` (lines 87-96) |

**Modes:**
- `msg_source: 1` (online) -- driver receives raw UDP packets directly from lidar hardware
- `msg_source: 2` (from ROS) -- driver subscribes to `rslidar_packets` topic (e.g. from rosbag)

**Input topic** (mode 2): `rslidar_packets` (relative, resolves to `/sensing/lidar/{sensor_id}/rslidar_packets`)
- Config key: `ros.ros_recv_packet_topic`
- Message type: `rslidar_msg/msg/RslidarPacket`

**Output topic**: `pointcloud_raw_ex` (relative, resolves to `/sensing/lidar/{sensor_id}/pointcloud_raw_ex`)
- Config key: `ros.ros_send_point_cloud_topic`
- Message type: `sensor_msgs/msg/PointCloud2`
- Fields: x, y, z, intensity, ring, timestamp

---

### Step 2: Mirror Reflection Filter (optional)

| | |
|---|---|
| **Package** | `pointcloud_preprocessor` |
| **Plugin** | `pointcloud_preprocessor::MirrorReflectionFilterComponent` |
| **Node name** | `mirror_reflection_filter` |
| **Condition** | `launch_mr_filter` parameter (per-sensor, from `sensing.yaml`) |
| **Launch file** | `robosense_filters.launch.py` (lines 67-85) |

**Input**: `pointcloud_raw_ex`
**Output**: `mr_filtered/pointcloud_ex`

Removes mirror reflections based on vehicle geometry masks configured in
`mirror_reflection_filter_param.yaml`.

---

### Step 3: CropBox Filter (Ego Vehicle Removal)

| | |
|---|---|
| **Package** | `pointcloud_preprocessor` |
| **Plugin** | `pointcloud_preprocessor::CropBoxFilterComponent` |
| **Node name** | `ego_crop_box_filter` |
| **Launch file** | `robosense_filters.launch.py` (lines 111-121) |

**Input**: `mr_filtered/pointcloud_ex` (if MR filter enabled) OR `pointcloud_raw_ex` (if disabled)
**Output**: `ego_cropped/pointcloud_ex`

Removes points inside the vehicle bounding box. Parameters computed from vehicle geometry:
`min/max_longitudinal_offset`, `min/max_lateral_offset`, `min/max_height_offset`.

---

### Step 4: Distortion Corrector

| | |
|---|---|
| **Package** | `pointcloud_preprocessor` |
| **Plugin** | `pointcloud_preprocessor::DistortionCorrectorComponent` |
| **Node name** | `distortion_corrector_node` |
| **Launch file** | `robosense_filters.launch.py` (lines 123-140) |

**Input**: `ego_cropped/pointcloud_ex` (via `~/input/pointcloud`)
**Output**: `rectified/pointcloud_ex` (via `~/output/pointcloud`)

**Additional inputs:**
- `~/input/kinematic_state` <- `/localization/kinematic_state`
- `~/input/imu` <- `/sensing/imu/central/imu_`

Corrects motion distortion in the point cloud using vehicle kinematics. Uses `timestamp`
field for per-point correction. IMU correction disabled (`use_imu: false`).

---

### Step 5: Format Converter

| | |
|---|---|
| **Package** | `pointcloud_preprocessor` |
| **Plugin** | `pointcloud_preprocessor::ConvertXyzirToXyziradtFilterComponent` |
| **Node name** | `convert_filter` |
| **Launch file** | `robosense_filters.launch.py` (lines 162-173) |

**Input**: `rectified/pointcloud_ex`
**Output**: `converted/pointcloud_ex`

Converts point cloud format from XYZIR (x, y, z, intensity, ring) to XYZIRADT
(x, y, z, intensity, ring, azimuth, distance, timestamp) -- required for downstream processing.

---

### Step 6: Ring Outlier Filter

| | |
|---|---|
| **Package** | `pointcloud_preprocessor` |
| **Plugin** | `pointcloud_preprocessor::RingOutlierFilterComponent` |
| **Node name** | `ring_outlier_filter` |
| **Launch file** | `robosense_filters.launch.py` (lines 175-191) |

**Input**: `converted/pointcloud_ex`
**Output**: `outlier_filtered/pointcloud`

Removes outlier points based on ring structure analysis. Configured with
`use_radians_for_azimuth: true`, `publish_outlier_pointcloud: true`.

This is the **final per-sensor output** topic.
Full path: `/sensing/lidar/{sensor_id}/outlier_filtered/pointcloud`

---

### Step 7: Point Cloud Concatenation

| | |
|---|---|
| **Package** | `pointcloud_preprocessor` |
| **Plugin** | `pointcloud_preprocessor::PointCloudConcatenateDataSynchronizerComponent` |
| **Node name** | `concatenate_filter` |
| **Namespace** | `/sensing/lidar/concatenated/` |
| **Launch file** | `pointcloud_merger.launch.py` (lines 14-31) via `common.launch.xml` |

**Input topics** (collected from all enabled sensors in `sensing.launch.py`, line 111-114):
```yaml
- /sensing/lidar/front/outlier_filtered/pointcloud
- /sensing/lidar/front_left/outlier_filtered/pointcloud
- /sensing/lidar/front_right/outlier_filtered/pointcloud
- /sensing/lidar/top/outlier_filtered/pointcloud
```

**Additional input:**
- `~/input/twist` <- `/sensing/vehicle_velocity_converter/twist_with_covariance`

**Output topic**: `/sensing/lidar/concatenated/pointcloud`
- Configurable via: `sensing.lidar.merger.output_topic` (default in `common.launch.xml:11`)
- Parameters: `output_frame: base_link`, `use_sync_clouds: true`

A companion `LidarSyncCheckerComponent` monitors synchronization between sensors
(`synchronization_limit_sec: 0.05`, `timeout_sec: 0.15`).

---

## Summary Table

| Step | Node | Input Topic | Output Topic |
|------|------|-------------|--------------|
| 1 | `rslidar_node` | `rslidar_packets` (or UDP) | `pointcloud_raw_ex` |
| 2 | `mirror_reflection_filter` | `pointcloud_raw_ex` | `mr_filtered/pointcloud_ex` |
| 3 | `ego_crop_box_filter` | `mr_filtered/pointcloud_ex` or `pointcloud_raw_ex` | `ego_cropped/pointcloud_ex` |
| 4 | `distortion_corrector_node` | `ego_cropped/pointcloud_ex` | `rectified/pointcloud_ex` |
| 5 | `convert_filter` | `rectified/pointcloud_ex` | `converted/pointcloud_ex` |
| 6 | `ring_outlier_filter` | `converted/pointcloud_ex` | `outlier_filtered/pointcloud` |
| 7 | `concatenate_filter` | N x `outlier_filtered/pointcloud` | `/sensing/lidar/concatenated/pointcloud` |

All intermediate topics are relative and resolve within the sensor namespace
`/sensing/lidar/{sensor_id}/`.

---

## Key Source Files

| File | Purpose |
|------|---------|
| `sensing/sensing/launch/sensing.launch.py` | Main sensing orchestration, namespace/topic collection |
| `sensing/sensing/launch/lidar/robosense.launch.xml` | Per-sensor launch wrapper |
| `sensing/sensing/launch/lidar/robosense_filters.launch.py` | Driver + filter chain definition |
| `sensing/sensing/launch/lidar/common.launch.xml` | Merger entry point |
| `sensing/sensing/launch/lidar/pointcloud_merger.launch.py` | Concatenation node |
| `sensing/lidar/rslidar_sdk/` | RoboSense driver package |
| `configuration/tram_param/config/tram/{vehicle_id}/sensing/lidar_robosense_*_config.yaml` | Per-sensor driver configs |
| `configuration/tram_param/config/tram/{vehicle_id}/sensing.yaml` | Sensor enable/disable, per-sensor parameters |
