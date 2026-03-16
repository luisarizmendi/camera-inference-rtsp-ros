#!/bin/bash
# entrypoint.sh — arranca MediaMTX, espera a que esté listo y lanza el nodo ROS2

set -e

RTSP_PORT="${RTSP_PORT:-8554}"

echo "[entrypoint] Sourcing ROS2 environment …"
source /opt/ros/kilted/setup.bash
source /ros2_ws/install/setup.bash

echo "[entrypoint] Starting MediaMTX on port ${RTSP_PORT} …"
mediamtx /etc/mediamtx/mediamtx.yml &
MEDIAMTX_PID=$!

# Esperar hasta que el puerto RTSP esté abierto (máx. 15 s)
echo "[entrypoint] Waiting for MediaMTX to be ready …"
for i in $(seq 1 15); do
    if bash -c "echo > /dev/tcp/127.0.0.1/${RTSP_PORT}" 2>/dev/null; then
        echo "[entrypoint] MediaMTX ready."
        break
    fi
    sleep 1
done

echo "[entrypoint] Starting ROS2 image streamer node …"
exec ros2 run image_streamer image_streamer_node
