# YDLidar ROS 2 Driver

This package contains a minimal ROS 2 Humble node that publishes `sensor_msgs/LaserScan` messages from a YDLidar device.

## Usage

```bash
ros2 launch ydlidar_ros2_driver ydlidar_launch.py
```

Parameters:
- `port`: serial port of the sensor (default `/dev/ydlidar`).
- `frame_id`: frame name for the published scans (default `laser_frame`).
