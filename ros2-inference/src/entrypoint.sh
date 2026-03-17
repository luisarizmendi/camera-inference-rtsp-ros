#!/bin/bash
set -e

export ROS_HOME=/tmp/ros_home

source /usr/lib64/ros2-kilted/setup.bash
source /ros2_ws/install/setup.bash

exec ros2 run inference_node inference_node
