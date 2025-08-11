from launch import LaunchDescription
from launch_ros.actions import Node


def generate_launch_description():
    return LaunchDescription([
        Node(
            package='ydlidar_ros2_driver',
            executable='ydlidar_node',
            name='ydlidar',
            parameters=[{'port': '/dev/ttyUSB0', 'frame_id': 'laser_frame'}]
        )
    ])
