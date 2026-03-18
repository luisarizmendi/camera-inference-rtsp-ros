# Camera Inference Demo

Low-latency camera streaming with YOLOv11 object detection and live bounding-box overlay in the browser.

## Goal

This repository packages a complete, containerised computer-vision pipeline. A USB webcam is captured, encoded and broadcast at very low latency (~150 ms) while a separate AI inference loop runs YOLOv11 frame-by-frame and publishes the detection results. A static web page then composites both streams client-side with no server-side rendering.

Everything runs with **Podman** (rootless or root) on either `x86_64` or `aarch64`. No ROS2 installation is required on the host.

---

## Why ROS2?

**ROS2 (Robot Operating System 2)** is an open-source middleware framework, not an actual OS, that lets processes exchange typed messages over named channels called topics. Any number of publishers and subscribers can connect to a topic without knowing about each other, and the underlying DDS transport handles discovery and delivery automatically across processes and machines.

In this project ROS2 carries only the inference results between the YOLOv11 node and the browser bridge. Video stays completely out of ROS2, travelling from MediaMTX to the browser over WebRTC and to the inference node over RTSP. This keeps the bus load minimal and lets each part be restarted or replaced independently. It also means you can inspect live detections from any machine on the same network with no changes to the running stack:

```bash
source /opt/ros/kilted/setup.bash
ros2 topic echo /detections
```

---

## Architecture

```
USB Camera
    |
    v
camera-gateway-rtsp  (Fedora + FFmpeg + MediaMTX)
    |
    +-- WebRTC  :8889 (WHEP) ----------------------------------------> browser <video>  (~150 ms)
    |
    +-- RTSP    :8554 --> ros2-inference  (Ubuntu + CUDA + YOLOv11)
                               |
                               |  /detections  (vision_msgs/Detection2DArray)
                               |  [ROS2 DDS topic]
                               v
                          ros2-rosbridge :9099 -----------------------> browser canvas overlay
                               |
                               v  (optional)
                          ros2-broker-watch, topic health monitor
```

Video and detections reach the browser on independent paths and are composited client-side. The video path never touches ROS2, only the tiny detection metadata (bounding boxes, labels, scores) travels through the DDS bus.

---

## Repository layout

```
camera-inference-demo/
├── README.md                        <- this file
├── build-all.sh                     <- build every image in one command
|
├── camera-gateway-rtsp/             <- webcam capture + RTSP/WebRTC/HLS broadcast
│   ├── README.md
│   ├── build.sh
│   └── src/
│       ├── Containerfile
│       ├── entrypoint.sh
│       ├── stream.py
│       └── mediamtx.yml
|
├── ros2-inference/                  <- YOLOv11 RTSP pull + /detections publisher
│   ├── README.md
│   ├── build.sh
│   └── src/
│       ├── Containerfile
│       ├── entrypoint.sh
│       └── ros2_pkg/
|
├── ros2-rosbridge/                  <- ROS2 topics to WebSocket bridge
│   ├── README.md
│   ├── build.sh
│   └── src/
│       ├── Containerfile
│       └── entrypoint.sh
|
├── image-inference-viewer/          <- nginx static page with overlay UI
│   ├── README.md
│   ├── build.sh
│   └── src/
│       ├── Containerfile
│       ├── index.html
│       └── nginx.conf
|
├── _helpers_/
│   └── ros2-broker-watch/           <- optional topic health monitor
│       ├── README.md
│       └── src/
|
└── _run_/                           <- ready-to-use runtime files
    ├── README.md
    └── compose/ 
        └── compose.yml                  <- Podman Compose stack
    └── quadlets/                    <- systemd Podman quadlet units
        ├── camera-inference.network
        ├── camera-gateway-rtsp.container
        ├── ros2-inference.container
        ├── ros2-rosbridge.container
        └── image-inference-viewer.container
```

---

## Container images

| Directory | Image | Base | Description |
|-----------|-------|------|-------------|
| `camera-gateway-rtsp` | `quay.io/luisarizmendi/camera-gateway-rtsp` | Fedora latest | USB webcam to MediaMTX, RTSP + WebRTC + HLS |
| `ros2-inference` | `quay.io/luisarizmendi/ros2-inference` | `ros:kilted-ros-base` + NVIDIA CUDA 12.6 | RTSP pull, YOLOv11, publishes `/detections` |
| `ros2-rosbridge` | `quay.io/luisarizmendi/ros2-rosbridge` | `ros:kilted` | ROS2 topics to WebSocket bridge for the browser |
| `image-inference-viewer` | `quay.io/luisarizmendi/image-inference-viewer` | nginx:alpine | Static HTML overlay UI on port 8080 |
| `_helpers_/ros2-broker-watch` | `quay.io/luisarizmendi/ros2-broker-watch` | `ros:kilted-ros-base` | Optional topic health diagnostics |

All images are multi-arch manifests (`amd64` + `arm64`) published to `quay.io/luisarizmendi`.

---

## Building

### Quick build, all images

```bash
chmod +x build-all.sh
./build-all.sh
```

By default this builds for the local host architecture and pushes to `quay.io/luisarizmendi`.

#### Build script options

| Flag | Description |
|------|-------------|
| `--no-push` | Build locally, skip registry push and manifest steps |
| `--cross` | Also build for the opposite architecture (amd64 to arm64 or vice versa) via emulation |
| `--registry <registry>` | Override the default registry (`quay.io/luisarizmendi`) |
| `--force-manifest-reset` | Rebuild the multi-arch manifest from scratch, discarding the previously published opposite-arch image |

```bash
# Build locally, do not push anything
./build-all.sh --no-push

# Build and push to a custom registry
./build-all.sh --registry ghcr.io/myuser

# Cross-build both amd64 and arm64 from an x86_64 host and push
./build-all.sh --cross

# Build locally without touching any remote manifest
./build-all.sh --no-push --force-manifest-reset
```

Use `--force-manifest-reset` when you want a clean manifest with only the architectures you are building right now.

### Build a single image

Each component has its own `build.sh` with the same flags:

```bash
cd ros2-inference
./build.sh --no-push

cd camera-gateway-rtsp
./build.sh --registry ghcr.io/myuser --cross
```

The script picks the image name from the directory name and produces `<registry>/<directory-name>:<arch>` arch-specific tags plus `:latest` and `:prod` multi-arch manifests.

### Build order

There are no hard ordering constraints. All images pull the official `ros:kilted` or Fedora base automatically. If you are building locally without a registry, just make sure not to run the stack before the builds finish.

---

## Latency breakdown

| Stage | Latency |
|-------|---------|
| Camera to MediaMTX encoding | ~10 ms |
| MediaMTX to browser (WebRTC) | ~100-150 ms |
| RTSP pull to YOLO (GPU nano) | ~50 ms |
| RTSP pull to YOLO (CPU nano) | ~200-500 ms |
| Detections to browser (WebSocket) | ~10-20 ms |
| **Total video latency** | **~150 ms** |
| **Detection trail behind video** | **~50-500 ms** |

---

## Running

See [`_run_/README.md`](_run_/README.md) for full instructions using either Podman Compose or systemd Quadlets.

Quick start with Podman Compose:

```bash
# Edit RTSP_URL and MTX_WEBRTCADDITIONALHOSTS to your host LAN IP first
podman compose -f _run_/compose/compose.yml up -d
# Open http://<host-ip>:8080
```

---

## NVIDIA GPU

The `ros2-inference` image is built on top of the official NVIDIA CUDA runtime. To enable GPU inference:

- In **Compose**: uncomment the `devices: - nvidia.com/gpu=all` line and set `DEVICE=cuda`.
- In **Quadlets**: add `AddDevice=nvidia.com/gpu=all` and `Environment=DEVICE=cuda` in `ros2-inference.container`.
- With `DEVICE=auto` the container falls back to CPU if no CUDA device is found.
