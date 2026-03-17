#!/bin/bash
set -e

source /usr/lib64/ros2-kilted/setup.bash
source /ros2_ws/install/setup.bash

exec ros2 run image_broker image_broker_node
