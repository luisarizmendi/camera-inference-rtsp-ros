# ros2-rtsp-bridge

Containerized service that acts as a **bridge between an RTSP stream and a ROS2 topic**.
Captures frames from an IP/RTSP camera and publishes them as `sensor_msgs/Image` messages.

Built on `ros2-fedora-base:latest`. Designed to run **one instance per camera**.

## Structure

```
ros2-rtsp-bridge/
├── README.md
└── src/
    ├── Containerfile
    ├── entrypoint.sh
    └── ros2_pkg/
        ├── package.xml
        ├── setup.cfg
        ├── setup.py
        ├── resource/
        │   └── rtsp_bridge
        └── rtsp_bridge/
            ├── __init__.py
            └── rtsp_bridge_node.py
```

## Environment variables

| Variable            | Required | Default             | Description |
|---------------------|:--------:|---------------------|-------------|
| `RTSP_URL`          | ✅        | —                   | Full RTSP stream URL |
| `ROS_TOPIC`         |          | `/camera/image_raw` | ROS2 topic to publish frames on |
| `CAMERA_NAME`       |          | `rtsp_bridge`       | Logical name; used as `frame_id` and node name |
| `TARGET_FPS`        |          | `10`                | Publishing rate in frames per second |
| `MAX_FRAMES`        |          | `0`                 | Max frames before stopping; `0` = unlimited |
| `IMAGE_WIDTH`       |          | `0`                 | Resize width in pixels; `0` = no resize |
| `IMAGE_HEIGHT`      |          | `0`                 | Resize height in pixels; `0` = no resize |
| `JPEG_QUALITY`      |          | `0`                 | JPEG re-encode quality (1-100); `0` = disabled |
| `RECONNECT_DELAY`   |          | `5`                 | Seconds between reconnection attempts |
| `RECONNECT_RETRIES` |          | `0`                 | Max reconnection attempts; `0` = unlimited |
| `QOS_DEPTH`         |          | `1`                 | Publisher QoS history depth |
| `VERBOSE`           |          | `false`             | Log every published frame: `1`/`true`/`yes` |
| `ROS_DOMAIN_ID`     |          | `0`                 | ROS2 DDS domain ID |

## Build

```bash
cd ros2-fedora-base/src  && podman build -t ros2-fedora-base:latest .
cd ros2-rtsp-bridge/src  && podman build -t ros2-rtsp-bridge:latest .
```

## Run

```bash
podman run --rm --network host \
  -e RTSP_URL="rtsp://admin:1234@192.168.1.100:554/stream1" \
  -e ROS_TOPIC="/camera/front/image_raw" \
  -e CAMERA_NAME="camera_front" \
  -e TARGET_FPS="15" \
  -e IMAGE_WIDTH="1280" \
  -e IMAGE_HEIGHT="720" \
  ros2-rtsp-bridge:latest
```

> Use `--network host` so ROS2 DDS discovery works correctly across containers.

## Notes

### H264 decoder log messages

When using UDP transport (the default, lowest latency), occasional dropped packets
produce FFmpeg warnings like `decode_slice_header error` or `Frame num change`.
These are non-fatal — the decoder recovers automatically. They are suppressed in
the node by setting `OPENCV_FFMPEG_LOGLEVEL=8` (fatal-only) before opening the
capture, so they will not appear in the container logs.

### RPM Fusion

The Containerfile adds RPM Fusion repos and runs `dnf upgrade` to replace Fedora's
restricted ffmpeg stub with the full build including H264 support. This is required
for OpenCV's FFmpeg backend to decode H264 RTSP streams correctly.
