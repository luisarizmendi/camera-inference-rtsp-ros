# ros2-inference

Pulls frames from an RTSP stream, runs object detection (YOLOv11), and publishes results as `vision_msgs/Detection2DArray` on `/detections`.

Video never enters ROS2. The browser gets the video via WebRTC from MediaMTX and detections via rosbridge WebSocket from this node.

## Structure

```
ros2-inference/
├── README.md
├── build.sh
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

The image is built in three stages:

1. **python-builder**, NVIDIA CUDA 12.6 base, installs PyTorch + Ultralytics + ONNX Runtime and downloads `yolo11n.pt` at build time so the container starts without network access.
2. **ros-builder**, official `ros:kilted-ros-base`, builds the `inference_node` ROS2 package with `colcon`.
3. **Final runtime**, CUDA base again, installs the ROS2 runtime from the official apt repo and copies the Python packages and built workspace from the previous stages.

The inference node opens the RTSP stream with OpenCV (`CAP_FFMPEG`, buffer size = 1). On each cycle it drains the capture buffer with `grab()` before calling `retrieve()`, so it always works on the most recent frame regardless of the stream FPS vs `TARGET_FPS` ratio. No frame accumulation, no stale detections.

After each publish, a TTL timer fires every 200 ms. If `DETECTION_TTL` seconds pass without a new result, an empty `Detection2DArray` is sent to clear the browser overlay.

### Model format support

Both PyTorch (`.pt`) and ONNX (`.onnx`) models are supported. The node looks for the model in `MODELS_DIR` using this priority order:

1. `<model_stem>.pt` — PyTorch, runs on CPU or CUDA
2. `<model_stem>.onnx` — ONNX Runtime, provider selected automatically
3. Fall back to `INFERENCE_MODEL` value as-is, letting Ultralytics auto-download it

### Class names

Class names are resolved in this priority order:

1. **`CLASS_NAMES` env var** — comma-separated list, e.g. `"person,bicycle,car"`
2. **`CLASS_NAMES_FILE`** — path to a plain-text file with one name per line (line 0 = class 0)
3. **Names embedded in the model** — works automatically for `.pt` models and for ONNX models exported via Ultralytics
4. If none of the above, detections fall back to numeric class IDs

This matters especially for ONNX models not exported through Ultralytics, which typically carry no class metadata.

## Build

```bash
cd ros2-inference
./build.sh
```

| Flag | Description |
|------|-------------|
| `--no-push` | Build locally, skip push |
| `--cross` | Also cross-build for the opposite arch |
| `--registry <reg>` | Override default registry (`quay.io/luisarizmendi`) |
| `--force-manifest-reset` | Recreate the remote multi-arch manifest from scratch |

```bash
# Local-only build
./build.sh --no-push

# Cross-build both architectures
./build.sh --cross

# Push to a different registry
./build.sh --registry ghcr.io/myuser
```

> The build downloads `yolo11n.pt` from GitHub, so internet access is required.

## Environment variables

| Variable               | Default                        | Description |
|------------------------|--------------------------------|-------------|
| `RTSP_URL`             | `rtsp://127.0.0.1:8554/stream` | RTSP stream to pull frames from |
| `DETECTION_TOPIC`      | `/detections`                  | ROS2 topic to publish on |
| `INFERENCE_MODEL`      | `yolo11n.pt`                   | Model filename (`.pt` or `.onnx`) |
| `MODELS_DIR`           | `/opt/models`                  | Directory to search for model files |
| `CONFIDENCE_THRESHOLD` | `0.4`                          | Minimum detection confidence (0-1) |
| `INFERENCE_WIDTH`      | `640`                          | Frame width fed to the model |
| `INFERENCE_HEIGHT`     | `640`                          | Frame height fed to the model |
| `TARGET_FPS`           | `30`                           | Max inference rate, frames between cycles are dropped |
| `DETECTION_TTL`        | `1.0`                          | Seconds after last detection before publishing empty array |
| `DEVICE`               | `auto`                         | `auto`, `cpu`, `cuda`, `cuda:0` — ignored for ONNX models |
| `CLASS_NAMES`          | _(unset)_                      | Comma-separated class names in ID order. Overrides model metadata and `CLASS_NAMES_FILE` |
| `CLASS_NAMES_FILE`     | _(unset)_                      | Path to a file with one class name per line (line 0 = class 0). Ignored if `CLASS_NAMES` is set |
| `VERBOSE`              | `false`                        | Log every detection |
| `ROS_DOMAIN_ID`        | `0`                            | ROS2 DDS domain ID |

### Model sizes

| Model        | GPU latency | CPU latency | Notes |
|--------------|-------------|-------------|-------|
| `yolo11n.pt` | ~5 ms       | ~100-200 ms | Pre-downloaded at build time |
| `yolo11s.pt` | ~8 ms       | ~200-400 ms | Download or mount at runtime |
| `yolo11m.pt` | ~15 ms      | ~500 ms     | Download or mount at runtime |
| `yolo11l.pt` | ~25 ms      | ~1 s        | Download or mount at runtime |
| `yolo11x.pt` | ~40 ms      | ~2 s        | Download or mount at runtime |

## NVIDIA GPU setup (CDI)

To pass the GPU into the container with `--device nvidia.com/gpu=all` you need a CDI specification generated on the host. Without it Podman will fail with `unresolvable CDI devices nvidia.com/gpu=all`.

**1. Install the NVIDIA Container Toolkit** (if not already installed):

```bash
# RHEL/Fedora
sudo dnf install -y nvidia-container-toolkit

# Ubuntu/Debian
curl -fsSL https://nvidia.github.io/libnvidia-container/gpgkey \
  | sudo gpg --dearmor -o /usr/share/keyrings/nvidia-container-toolkit-keyring.gpg
curl -sL https://nvidia.github.io/libnvidia-container/stable/deb/nvidia-container-toolkit.list \
  | sudo tee /etc/apt/sources.list.d/nvidia-container-toolkit.list
sudo apt-get update && sudo apt-get install -y nvidia-container-toolkit
```

**2. Generate the CDI specification:**

```bash
sudo nvidia-ctk cdi generate --output=/etc/cdi/nvidia.yaml
```

Verify the available CDI devices with:

```bash
nvidia-ctk cdi list
```

Which should show something like:

```
nvidia.com/gpu=all
nvidia.com/gpu=0
```

> Re-run `nvidia-ctk cdi generate` after any driver upgrade or GPU configuration change. If you store the spec under `/var/run/cdi/` instead of `/etc/cdi/`, note that `/var/run/` is cleared on reboot.

## Run (standalone)

```bash
podman run --rm --network host \
  -e RTSP_URL="rtsp://192.168.1.41:8554/stream" \
  -e DEVICE="auto" \
  -v /dev/shm:/dev/shm \
  quay.io/luisarizmendi/ros2-inference:latest
```

### With NVIDIA GPU

```bash
podman run --rm --network host \
  --security-opt=label=disable \
  --device nvidia.com/gpu=all \
  -e RTSP_URL="rtsp://192.168.1.41:8554/stream" \
  -e DEVICE="cuda" \
  -v /dev/shm:/dev/shm \
  quay.io/luisarizmendi/ros2-inference:latest
```

> `--security-opt=label=disable` is required on SELinux-enforcing systems (RHEL, Fedora) to allow the container access to the GPU device.

### Using a custom model

Mount the model file into `MODELS_DIR` (`/opt/models` by default) and set `INFERENCE_MODEL` to its filename. Both `.pt` and `.onnx` are supported:

```bash
# PyTorch model
podman run --rm --network host \
  -v /dev/shm:/dev/shm \
  -v /path/to/my_model.pt:/opt/models/my_model.pt:ro \
  -e INFERENCE_MODEL="my_model.pt" \
  quay.io/luisarizmendi/ros2-inference:latest

# ONNX model
podman run --rm --network host \
  -v /dev/shm:/dev/shm \
  -v /path/to/my_model.onnx:/opt/models/my_model.onnx:ro \
  -e INFERENCE_MODEL="my_model.onnx" \
  quay.io/luisarizmendi/ros2-inference:latest
```

### Providing class names

If the model does not embed class names (common with third-party ONNX models), pass them via env var or file:

```bash
# Inline — comma-separated, in class ID order
podman run --rm --network host \
  -v /dev/shm:/dev/shm \
  -v /path/to/my_model.onnx:/opt/models/my_model.onnx:ro \
  -e INFERENCE_MODEL="my_model.onnx" \
  -e CLASS_NAMES="person,bicycle,car,motorcycle,bus,truck" \
  quay.io/luisarizmendi/ros2-inference:latest

# File — one name per line, line 0 = class 0
podman run --rm --network host \
  -v /dev/shm:/dev/shm \
  -v /path/to/my_model.onnx:/opt/models/my_model.onnx:ro \
  -v /path/to/classes.txt:/opt/models/classes.txt:ro \
  -e INFERENCE_MODEL="my_model.onnx" \
  -e CLASS_NAMES_FILE="/opt/models/classes.txt" \
  quay.io/luisarizmendi/ros2-inference:latest
```

Example `classes.txt`:
```
person
bicycle
car
motorcycle
bus
truck
```

> `CLASS_NAMES` and `CLASS_NAMES_FILE` also work with `.pt` models if you want to override the names embedded in the weights.

## Detection message format

Topic: `/detections`
Type: `vision_msgs/msg/Detection2DArray`

Each `Detection2D` contains:
- `bbox.center.position.x/y` — bounding-box centre in original-frame pixels
- `bbox.size_x/size_y` — bounding-box width and height in pixels
- `results[0].hypothesis.class_id` — class label string (e.g. `"person"`) or numeric ID if no names are available
- `results[0].hypothesis.score` — confidence 0-1
