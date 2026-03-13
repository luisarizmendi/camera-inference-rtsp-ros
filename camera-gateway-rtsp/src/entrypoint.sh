#!/bin/bash
# entrypoint.sh — starts MediaMTX, waits for it to be ready, then runs the streamer

set -e

RTSP_PORT="${RTSP_PORT:-8554}"

echo "[entrypoint] Starting MediaMTX on port ${RTSP_PORT} …"
mediamtx /etc/mediamtx/mediamtx.yml &
MEDIAMTX_PID=$!

# Wait until the RTSP port is open (up to 15 s)
echo "[entrypoint] Waiting for MediaMTX to be ready …"
for i in $(seq 1 15); do
    if bash -c "echo > /dev/tcp/127.0.0.1/${RTSP_PORT}" 2>/dev/null; then
        echo "[entrypoint] MediaMTX is ready."
        break
    fi
    sleep 1
done

echo "[entrypoint] Starting RTSP streamer …"
exec python3 /app/stream.py
