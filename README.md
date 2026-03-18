# Camera Inference Demo

Low-latency camera streaming with YOLOv11 object detection and live bounding-box overlay in the browser.

## Goal

This repository packages a complete, containerised computer-vision pipeline. A USB webcam is captured, encoded and broadcast at very low latency (~150 ms) while a separate AI inference loop runs YOLOv11 frame-by-frame and publishes per-frame object detections. A static web page composites both streams client-side with no server-side rendering.

Everything is designed to run with **Podman** (rootless or root), built and deployed on either `x86_64` or `aarch64`. No ROS2 installation is required on the host.

---

## Architecture

```
USB Camera
    │
    ▼
camera-gateway-rtsp  ── Fedora + FFmpeg + MediaMTX
    │
    ├── WebRTC  :8889 (WHEP) ──────────────────────────────► browser <video>  (~150 ms)
    │
    └── RTSP    :8554 ──► ros2-inference  (ROS + CUDA + YOLOv11)
                               │
                               │  /detections  (vision_msgs/Detection2DArray)
                               ▼
                          ros2-rosbridge :9099 ──────────────► browser canvas overlay
                               │
                               ▼  (optional)
                          ros2-broker-watch  — topic health monitor
```

Video and detections reach the browser on **independent paths** and are composited client-side. The video path never touches ROS2 — only the tiny detection metadata (bounding boxes + labels + scores) travels through the ROS2 DDS bus.

---

## Repository layout

```
camera-inference-demo/
├── README.md                        ← this file
├── build-all.sh                     ← build every image in one command
│
├── camera-gateway-rtsp/             ← webcam capture + RTSP/WebRTC/HLS broadcast
│   ├── README.md
│   ├── build.sh
│   └── src/
│       ├── Containerfile
│       ├── entrypoint.sh
│       ├── stream.py
│       └── mediamtx.yml
│
├── ros2-inference/                  ← YOLOv11 RTSP → /detections publisher
│   ├── README.md
│   ├── build.sh
│   └── src/
│       ├── Containerfile
│       ├── entrypoint.sh
│       └── ros2_pkg/
│
├── ros2-rosbridge/                  ← ROS2 topics → WebSocket bridge
│   ├── README.md
│   ├── build.sh
│   └── src/
│       ├── Containerfile
│       └── entrypoint.sh
│
├── image-inference-viewer/          ← nginx-served single-page overlay UI
│   ├── README.md
│   ├── build.sh
│   └── src/
│       ├── Containerfile
│       ├── index.html
│       └── nginx.conf
│
├── _helpers_/
│   └── ros2-broker-watch/           ← optional: topic health monitor
│       ├── README.md
│       └── src/
│
└── _run_/                           ← ready-to-use runtime files
    ├── README.md
    ├── compose.yml                  ← Podman Compose stack
    └── quadlets/                    ← systemd/Podman quadlet units
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
| `camera-gateway-rtsp` | `quay.io/luisarizmendi/camera-gateway-rtsp` | Fedora latest | USB webcam → MediaMTX → RTSP + WebRTC + HLS |
| `ros2-inference` | `quay.io/luisarizmendi/ros2-inference` | `ros:kilted-ros-base` + NVIDIA CUDA 12.6 | Pulls RTSP → YOLOv11 → publishes `/detections` |
| `ros2-rosbridge` | `quay.io/luisarizmendi/ros2-rosbridge` | `ros:kilted` | ROS2 topics → WebSocket bridge for the browser |
| `image-inference-viewer` | `quay.io/luisarizmendi/image-inference-viewer` | nginx:alpine | Static HTML overlay UI on port 8080 |
| `_helpers_/ros2-broker-watch` | `quay.io/luisarizmendi/ros2-broker-watch` | `ros:kilted-ros-base` | Optional: topic health diagnostics |

All images are multi-arch manifests (`amd64` + `arm64`) published to `quay.io/luisarizmendi`.

---

## Building

### Quick build — all images

```bash
chmod +x build-all.sh
./build-all.sh
```

By default this builds for the **local host architecture** and **pushes to `quay.io/luisarizmendi`**.

#### Build script options

| Flag | Description |
|------|-------------|
| `--no-push` | Build locally only, skip registry push and manifest steps |
| `--cross` | Also build for the opposite architecture (amd64↔arm64) via emulation |
| `--registry <registry>` | Override the default registry (`quay.io/luisarizmendi`) |
| `--force-manifest-reset` | Rebuild the multi-arch manifest from scratch (discard the previously-published opposite-arch image) |

**Examples**

```bash
# Build locally, do not push anything
./build-all.sh --no-push

# Build + push to a custom registry
./build-all.sh --registry ghcr.io/myuser

# Cross-build both amd64 and arm64 from an x86_64 host and push
./build-all.sh --cross

# Build locally without touching any remote manifest
./build-all.sh --no-push --force-manifest-reset
```

The `--force-manifest-reset` flag is useful when you want a clean manifest with only the architectures you are building right now, discarding whatever was previously pushed for the other arch.

### Build a single image

Each component has its own `build.sh` that accepts the same flags:

```bash
cd ros2-inference
./build.sh --no-push

cd camera-gateway-rtsp
./build.sh --registry ghcr.io/myuser --cross
```

The script auto-detects the image name from the directory name, so it always produces `<registry>/<directory-name>:<arch>` arch-specific tags and `:latest` / `:prod` multi-arch manifests.

### Build order

If you are using locally-built images (not pulling from a registry), the only ordering constraint is:

1. `ros2-inference`, `ros2-rosbridge`, and `_helpers_/ros2-broker-watch` depend on the official `ros:kilted` base image — pulled automatically from Docker Hub, no manual step needed.
2. All other images have no inter-dependencies and can be built in any order.

---

## Latency breakdown

| Stage | Latency |
|-------|---------|
| Camera → MediaMTX encoding | ~10 ms |
| MediaMTX → browser (WebRTC) | ~100–150 ms |
| RTSP pull → YOLO (GPU nano) | ~50 ms |
| RTSP pull → YOLO (CPU nano) | ~200–500 ms |
| Detections → browser (WebSocket) | ~10–20 ms |
| **Total video latency** | **~150 ms** |
| **Detection trail behind video** | **~50–500 ms** |

---

## Running

See [`_run_/README.md`](_run_/README.md) for full instructions using either **Podman Compose** or **systemd Quadlets**.

Quick start with Podman Compose:

```bash
# Edit RTSP_URL and MTX_WEBRTCADDITIONALHOSTS to your host LAN IP first
podman compose -f _run_/compose.yml up -d
# Open http://<host-ip>:8080
```

---

## NVIDIA GPU

The `ros2-inference` image is built on top of the official NVIDIA CUDA runtime. To use the GPU:

- In **Compose**: uncomment the `devices: - nvidia.com/gpu=all` section and set `DEVICE=cuda`.
- In **Quadlets**: add `AddDevice=nvidia.com/gpu=all` and `Environment=DEVICE=cuda` in `ros2-inference.container`.
- The container will fall back to CPU automatically if `DEVICE=auto` and no CUDA device is found.
