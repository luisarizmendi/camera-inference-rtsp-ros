# Camera Inference + Overlay Stack

Low-latency camera streaming with YOLOv11 object detection and live bounding
box overlay in the browser.

## Architecture

```
USB Camera
    │
    ▼
camera-gateway-rtsp  (MediaMTX + FFmpeg)
    │
    ├── WebRTC :8889 ──────────────────────────────────► browser <video>  (~150ms)
    │
    └── RTSP :8554 ──► ros2-inference  (YOLOv11)
                            │
                            │  /detections  (vision_msgs/Detection2DArray)
                            ▼
                       ros2-rosbridge :9099 ─────────────► browser canvas overlay
```

Video and detections reach the browser independently and are composited
client-side. Total video latency is ~150ms (WebRTC). Detection boxes trail
by one inference cycle (~50ms GPU / ~200-500ms CPU).

## Services

| Service               | Image                  | Description |
|-----------------------|------------------------|-------------|
| `camera-gateway-rtsp` | `camera-gateway-rtsp`  | USB webcam → MediaMTX → RTSP + WebRTC + HLS |
| `ros2-inference`      | `ros2-inference`       | Pulls RTSP → YOLOv11 → publishes `/detections` |
| `ros2-rosbridge`      | `ros2-rosbridge`       | ROS2 topics → WebSocket bridge for the browser |
| `viewer`              | `viewer`               | nginx serving the HTML overlay UI on :8080 |
| `ros2-broker`         | `ros2-broker`          | Optional topic health monitor |
| `ros2-fedora-base`    | `ros2-fedora-base`     | Base image — not run directly |

## Quick start

### 1. Build images (in order)

```bash
podman build -t ros2-fedora-base:latest    ros2-fedora-base/src/
podman build -t ros2-inference:latest      ros2-inference/src/
podman build -t ros2-rosbridge:latest      ros2-rosbridge/src/
podman build -t camera-gateway-rtsp:latest camera-gateway-rtsp/src/
podman build -t viewer:latest              viewer/src/
```

### 2. Configure

Edit `docker-compose.yml`:
- Set `MTX_WEBRTCADDITIONALHOSTS` to your host LAN IP
- Set the correct camera device under `devices` (default: `/dev/video0`)
- Adjust `YOLO_MODEL` and `TARGET_FPS` to match your hardware

### 3. Start

```bash
docker compose up -d
```

### 4. Open the viewer

Navigate to `http://<host-ip>:8080` in any browser on the network.
The connection fields are pre-filled from the page hostname. Click **Connect**.

## Latency breakdown

| Stage                          | Latency           |
|--------------------------------|-------------------|
| Camera → MediaMTX encoding     | ~10ms             |
| MediaMTX → browser (WebRTC)    | ~100–150ms        |
| RTSP pull → YOLO (GPU nano)    | ~50ms             |
| RTSP pull → YOLO (CPU nano)    | ~200–500ms        |
| Detections → browser (WS)      | ~10–20ms          |
| **Total video latency**        | **~150ms**        |
| **Detection trail**            | **~50–500ms**     |

## NVIDIA GPU

Uncomment the `deploy` section in `docker-compose.yml` and set
`DEVICE=cuda` or leave it as `auto`.
