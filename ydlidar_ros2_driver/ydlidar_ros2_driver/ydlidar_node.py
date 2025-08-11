import math
import serial

import rclpy
from rclpy.node import Node
from sensor_msgs.msg import LaserScan


class YDLidarNode(Node):
    """Simple ROS 2 node publishing LaserScan data from a YDLidar device."""

    def __init__(self) -> None:
        super().__init__('ydlidar_node')
        self.declare_parameter('port', '/dev/ydlidar')
        self.declare_parameter('frame_id', 'laser_frame')
        self.port = self.get_parameter('port').get_parameter_value().string_value
        self.frame_id = self.get_parameter('frame_id').get_parameter_value().string_value
        self.publisher = self.create_publisher(LaserScan, 'scan', 10)
        try:
            self.serial = serial.Serial(self.port, 230400, timeout=1)
            self.get_logger().info(f'Connected to YDLidar on {self.port}')
        except serial.SerialException as exc:
            self.get_logger().error(f'Failed to connect to YDLidar: {exc}')
            self.serial = None
        self.timer = self.create_timer(0.1, self.publish_scan)

    def publish_scan(self) -> None:
        if not self.serial:
            return
        data = self.serial.read(360)
        if not data:
            return
        scan = LaserScan()
        scan.header.stamp = self.get_clock().now().to_msg()
        scan.header.frame_id = self.frame_id
        scan.angle_min = 0.0
        scan.angle_max = 2 * math.pi
        scan.angle_increment = 2 * math.pi / 360.0
        scan.time_increment = 0.0
        scan.scan_time = 0.1
        scan.range_min = 0.12
        scan.range_max = 12.0
        scan.ranges = [float(b) for b in data]
        self.publisher.publish(scan)


def main(args=None) -> None:
    rclpy.init(args=args)
    node = YDLidarNode()
    try:
        rclpy.spin(node)
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == '__main__':
    main()
