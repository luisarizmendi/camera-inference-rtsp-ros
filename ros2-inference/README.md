# ros2-inference

Pulls frames directly from an RTSP stream, runs YOLOv11 object detection,
and publishes results as `vision_msgs/Detection2DArray` on `/detections`.

Video never enters ROS2 — only the tiny detection metadata is transported
through the ROS2 graph. The browser receives video via WebRTC directly from
MediaMTX and detections via rosbridge WebSocket from this node.

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

## How it works

The node opens an RTSP stream with OpenCV (`CAP_FFMPEG`, buffer size = 1).
On each inference cycle it **drains the capture buffer** using `grab()` before
calling `retrieve()` — this ensures it always operates on the most recent
frame regardless of how much faster the stream FPS is than `TARGET_FPS`.
No frame accumulation, no stale detections.

After each inference result is published, a TTL timer fires every 200ms.
If `DETECTION_TTL` seconds pass without a new publish, an empty
`Detection2DArray` is sent to clear the browser overlay automatically.

YOLOv11 weights are downloaded at **build time** into `/opt/yolo_models/`
so the container starts immediately without network access. A custom model
can be mounted at runtime (see below).

## Environment variables

| Variable                | Default                           | Description |
|-------------------------|-----------------------------------|-------------|
| `RTSP_URL`              | `rtsp://127.0.0.1:8554/stream`    | RTSP stream to pull frames from |
| `DETECTION_TOPIC`       | `/detections`                     | ROS2 topic to publish on |
| `YOLO_MODEL`            | `yolo11n.pt`                      | Model weights filename |
| `CONFIDENCE_THRESHOLD`  | `0.4`                             | Minimum detection confidence (0–1) |
| `INFERENCE_WIDTH`       | `640`                             | Frame width fed to YOLO |
| `INFERENCE_HEIGHT`      | `640`                             | Frame height fed to YOLO |
| `TARGET_FPS`            | `30`                              | Max inference rate. Frames between cycles are dropped — always uses the latest frame |
| `DETECTION_TTL`         | `1.0`                             | Seconds after last detection before publishing empty array to clear overlay |
| `DEVICE`                | `auto`                            | `auto`, `cpu`, `cuda`, `cuda:0` — auto detects CUDA at startup |
| `VERBOSE`               | `false`                           | Log every detection |
| `ROS_DOMAIN_ID`         | `0`                               | ROS2 DDS domain ID |

### YOLO model sizes

| Model        | GPU latency | CPU latency | Notes |
|--------------|-------------|-------------|-------|
| `yolo11n.pt` | ~5ms        | ~100–200ms  | Pre-downloaded at build time |
| `yolo11s.pt` | ~8ms        | ~200–400ms  | Download or mount at runtime |
| `yolo11m.pt` | ~15ms       | ~500ms      | Download or mount at runtime |
| `yolo11l.pt` | ~25ms       | ~1000ms     | Download or mount at runtime |
| `yolo11x.pt` | ~40ms       | ~2000ms     | Download or mount at runtime |

## Build

```bash
cd ros2-fedora-base/src && podman build -t ros2-fedora-base:latest .
cd ros2-inference/src   && podman build -t ros2-inference:latest .
```

> The build downloads `yolo11n.pt` from GitHub — requires internet access.

## Run

```bash
podman run --rm --network host \
  -e RTSP_URL="rtsp://192.168.1.41:8554/stream" \
  -e DEVICE="auto" \
  ros2-inference:latest
```

### With NVIDIA GPU

```bash
podman run --rm --network host \
  --security-opt=label=disable --device nvidia.com/gpu=all \
  -e RTSP_URL="rtsp://192.168.1.41:8554/stream" \
  -e DEVICE="cuda" \
  ros2-inference:latest
```

### Using a custom model

```bash
podman run --rm --network host \
  -v /path/to/my_model.pt:/opt/yolo_models/my_model.pt:ro \
  -e YOLO_MODEL="my_model.pt" \
  ros2-inference:latest
```

## Detection message format

Topic: `/detections`
Type: `vision_msgs/msg/Detection2DArray`

Each `Detection2D` contains:
- `bbox.center.position.x/y` — bounding box centre in original frame pixels
- `bbox.size_x/size_y` — bounding box width and height in pixels
- `results[0].hypothesis.class_id` — class label string (e.g. `"person"`)
- `results[0].hypothesis.score` — confidence 0–1
