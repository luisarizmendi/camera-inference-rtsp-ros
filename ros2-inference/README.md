# ros2-inference

Pulls frames directly from an RTSP stream, runs YOLOv11 detection, and
publishes results as `vision_msgs/Detection2DArray` on `/detections`.

This service intentionally does NOT use ROS2 image transport. Video stays
out of ROS2 entirely — the browser receives video via WebRTC directly from
MediaMTX, and only the tiny detection metadata travels through ROS2.

## Architecture

```
MediaMTX:8554 ──RTSP──► inference_node ──► /detections topic
                                                    │
                                             rosbridge:9099
                                                    │
                                             browser overlay
```

## Structure

```
ros2-inference/
├── README.md
└── src/
    ├── Containerfile
    ├── entrypoint.sh
    └── ros2_pkg/
        ├── package.xml
        ├── setup.cfg
        ├── setup.py
        ├── resource/
        │   └── inference_node
        └── inference_node/
            ├── __init__.py
            └── inference_node.py
```

## Environment variables

| Variable                | Default                            | Description |
|-------------------------|------------------------------------|-------------|
| `RTSP_URL`              | `rtsp://127.0.0.1:8554/stream`     | RTSP stream to pull frames from |
| `DETECTION_TOPIC`       | `/detections`                      | ROS2 topic to publish on |
| `YOLO_MODEL`            | `yolo11n.pt`                       | Model weights (auto-downloaded on first run) |
| `CONFIDENCE_THRESHOLD`  | `0.4`                              | Minimum detection confidence |
| `INFERENCE_WIDTH`       | `640`                              | Frame width fed to YOLO |
| `INFERENCE_HEIGHT`      | `640`                              | Frame height fed to YOLO |
| `TARGET_FPS`            | `10`                               | Max inference rate |
| `DEVICE`                | `auto`                             | `auto`, `cpu`, `cuda`, `cuda:0` |
| `VERBOSE`               | `false`                            | Log every detection |
| `ROS_DOMAIN_ID`         | `0`                                | ROS2 DDS domain ID |

### YOLO model sizes

| Model       | Speed (GPU) | Speed (CPU) | Accuracy |
|-------------|-------------|-------------|----------|
| `yolo11n.pt`| ~5ms        | ~100ms      | lowest   |
| `yolo11s.pt`| ~8ms        | ~200ms      | low      |
| `yolo11m.pt`| ~15ms       | ~500ms      | medium   |
| `yolo11l.pt`| ~25ms       | ~1000ms     | high     |
| `yolo11x.pt`| ~40ms       | ~2000ms     | highest  |

## Build

```bash
cd ros2-fedora-base/src && podman build -t ros2-fedora-base:latest .
cd ros2-inference/src   && podman build -t ros2-inference:latest .
```

## Run

```bash
podman run --rm --network host \
  -e RTSP_URL="rtsp://192.168.1.41:8554/stream" \
  -e YOLO_MODEL="yolo11n.pt" \
  -e TARGET_FPS="15" \
  -e DEVICE="auto" \
  ros2-inference:latest
```

With NVIDIA GPU:

```bash
podman run --rm --network host \
  --security-opt=label=disable --device nvidia.com/gpu=all \
  -e RTSP_URL="rtsp://192.168.1.41:8554/stream" \
  -e DEVICE="cuda" \
  -e TARGET_FPS="30" \
  ros2-inference:latest
```


With NVIDIA GPU and custom model from file:

```bash
podman run --rm --network host \
  --security-opt=label=disable --device nvidia.com/gpu=all \
  -e RTSP_URL="rtsp://192.168.1.41:8554/stream" \
  -e DEVICE="cuda" \
  -e TARGET_FPS="30" \
  -e YOLO_MODEL=hardhat.pt \
  -v /home/luis/models:/opt/yolo_models:Z \
  ros2-inference:latest
```
