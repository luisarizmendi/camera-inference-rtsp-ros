# Camera Inference + Overlay Stack

Low-latency camera streaming with YOLOv11 object detection and browser overlay.

## Architecture

```
USB Camera
    │
    ▼
camera-gateway-rtsp (MediaMTX + FFmpeg)
    │
    ├── WebRTC :8889 ─────────────────────────────────► browser <video>  (~150ms)
    │
    └── RTSP :8554 ──► ros2-inference (YOLOv11)
                            │ /detections (tiny JSON)
                            ▼
                       ros2-rosbridge :9099 ────────────► browser overlay (~50ms)
                                                               │
                                                      canvas bounding boxes
```

Video and detections reach the browser independently. The viewer composites
them in real-time using a canvas overlay. Total end-to-end latency is
~150-250ms (WebRTC) with detection boxes trailing by one inference cycle.

## Services

| Service               | Description |
|-----------------------|-------------|
| `camera-gateway-rtsp` | USB webcam → MediaMTX → RTSP + WebRTC + HLS |
| `ros2-inference`      | Pulls RTSP → YOLOv11 → publishes `/detections` |
| `ros2-rosbridge`      | Bridges ROS2 topics → browser WebSocket |
| `ros2-broker-watch`         | Optional: topic health monitoring |
| `viewer`              | Static HTML — open in browser |

## Quick start

### 1. Build images

```bash
podman build -t ros2-fedora-base:latest    ros2-fedora-base/src/
podman build -t ros2-inference:latest      ros2-inference/src/
podman build -t ros2-rosbridge:latest      ros2-rosbridge/src/
podman build -t camera-gateway-rtsp:latest camera-gateway-rtsp/src/
```

### 2. Configure

Edit `compose.yml`:
- Set `MTX_WEBRTCADDITIONALHOSTS` to your host LAN IP
- Set the correct camera device under `devices`
- Adjust `YOLO_MODEL` and `TARGET_FPS` to your hardware

### 3. Start

```bash
podman compose up -d
```

### 4. Open the viewer

Open `viewer/src/index.html` in your browser, then:
1. Set **MediaMTX host** to your host IP (e.g. `192.168.1.41`)
2. Set **rosbridge WebSocket** to `ws://192.168.1.41:9099`
3. Click **Connect**

## Latency notes

| Stage                        | Latency   |
|------------------------------|-----------|
| Camera → MediaMTX            | ~10ms     |
| MediaMTX → browser (WebRTC)  | ~100-150ms|
| RTSP pull → YOLO inference   | ~50-300ms (GPU/CPU) |
| Detections → browser (WS)    | ~10-20ms  |
| **Total video latency**      | **~150ms**|
| **Detection trail**          | **~100-500ms** |

## NVIDIA GPU

Uncomment the `deploy` section in `compose.yml` and set `DEVICE=cuda`.
The inference node auto-detects CUDA at startup if `DEVICE=auto`.

## Serving the viewer over the network

```bash
cd viewer/src
python3 -m http.server 8080
# open http://192.168.1.41:8080 on any device on the LAN
```
