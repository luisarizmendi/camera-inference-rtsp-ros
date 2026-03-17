#!/bin/bash
set -e

export ROS_HOME=/tmp/ros_home

source /usr/lib64/ros2-kilted/setup.bash
source /ros2_ws/install/setup.bash

ROSBRIDGE_PORT="${ROSBRIDGE_PORT:-9090}"

echo "[rosbridge] Starting rosbridge WebSocket server on port ${ROSBRIDGE_PORT} ..."
exec ros2 launch rosbridge_server rosbridge_websocket_launch.xml \
    port:=${ROSBRIDGE_PORT}
