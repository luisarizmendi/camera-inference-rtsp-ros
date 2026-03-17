#!/bin/bash
set -e

# Source ROS2
source /opt/ros/jazzy/setup.bash

echo "Starting rosbridge on port ${ROSBRIDGE_PORT}"

exec ros2 launch rosbridge_server rosbridge_websocket_launch.xml \
    port:=${ROSBRIDGE_PORT}