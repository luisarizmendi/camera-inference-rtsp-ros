# ros2-image-streamer

Containerized service that subscribes to a ROS2 image topic and re-publishes
it via MediaMTX as:

- **RTSP**   -> `rtsp://<host>:<RTSP_PORT>/<RTSP_NAME>`
- **HLS**    -> `http://<host>:<RTSP_PORT_HLS>/<RTSP_NAME>`
- **WebRTC** -> `http://<host>:<RTSP_PORT_WEBRTC>/<RTSP_NAME>`

Built on `ros2-fedora-base:latest`.

## Structure

```
ros2-image-streamer/
├── README.md
└── src/
    ├── Containerfile
    ├── entrypoint.sh
    ├── mediamtx.yml
    └── ros2_pkg/
        ├── package.xml
        ├── setup.cfg
        ├── setup.py
        ├── resource/
        │   └── image_streamer
        └── image_streamer/
            ├── __init__.py
            └── image_streamer_node.py
```

## Environment variables

| Variable            | Default             | Description |
|---------------------|---------------------|-------------|
| `ROS_TOPIC`         | `/camera/image_raw` | ROS2 image topic to subscribe to |
| `RTSP_HOST`         | `127.0.0.1`         | Host where MediaMTX is running |
| `RTSP_PORT`         | `8554`              | RTSP port |
| `RTSP_PORT_HLS`     | `8888`              | HLS web player port |
| `RTSP_PORT_WEBRTC`  | `8889`              | WebRTC web player port |
| `RTSP_PORT_ICE_UDP` | `8189`              | WebRTC ICE UDP mux port |
| `RTSP_NAME`         | `stream`            | Stream path name |
| `VIDEO_CODEC`       | `libx264`           | FFmpeg video codec |
| `VIDEO_BITRATE`     | `1000k`             | Output bitrate |
| `VIDEO_PRESET`      | `ultrafast`         | x264 preset |
| `VIDEO_TUNE`        | `zerolatency`       | x264 tune |
| `TARGET_FPS`        | `30`                | Output stream FPS |
| `IMAGE_WIDTH`       | `0`                 | Resize width before encoding; `0` = disabled |
| `IMAGE_HEIGHT`      | `0`                 | Resize height before encoding; `0` = disabled |
| `QOS_DEPTH`         | `1`                 | Subscriber QoS history depth |
| `VERBOSE`           | `false`             | Log every frame |
| `ROS_DOMAIN_ID`     | `0`                 | ROS2 DDS domain ID |

For WebRTC from a browser on the same LAN, also pass:
`-e MTX_WEBRTCADDITIONALHOSTS=<LAN_IP_of_host>`

## Build

```bash
cd ros2-fedora-base/src    && podman build -t ros2-fedora-base:latest .
cd ros2-image-streamer/src && podman build -t ros2-image-streamer:latest .
```

## Run — default ports

```bash
podman run --rm --network host \
  -e ROS_TOPIC="/camera/front/image_raw" \
  -e RTSP_NAME="front" \
  -e MTX_WEBRTCADDITIONALHOSTS="192.168.1.41" \
  ros2-image-streamer:latest
```

Streams will be available at:

| Protocol | URL |
|----------|-----|
| RTSP     | `rtsp://localhost:8554/front` |
| HLS/web  | `http://localhost:8888/front` |
| WebRTC   | `http://localhost:8889/front` |

## Port conflicts — running alongside another MediaMTX service

If another service that embeds MediaMTX (e.g. `camera-gateway-rtsp`) is already
running on the same host and using the default ports, you must assign a different
set of ports to this container.

The `entrypoint.sh` reads the four port variables at startup and rewrites
`mediamtx.yml` before launching MediaMTX, so no config file changes are needed —
just pass different values via environment variables.

Example — `camera-gateway-rtsp` already occupies 8554/8888/8889/8189:

```bash
podman run --rm --network host \
  -e ROS_TOPIC="/camera/front/image_raw" \
  -e RTSP_NAME="front" \
  -e RTSP_PORT=8654 \
  -e RTSP_PORT_HLS=8988 \
  -e RTSP_PORT_WEBRTC=8989 \
  -e RTSP_PORT_ICE_UDP=8289 \
  -e MTX_WEBRTCADDITIONALHOSTS="192.168.1.41" \
  ros2-image-streamer:latest
```

Streams will then be available at:

| Protocol | URL |
|----------|-----|
| RTSP     | `rtsp://localhost:8654/front` |
| HLS/web  | `http://localhost:8988/front` |
| WebRTC   | `http://localhost:8989/front` |

If you run multiple `ros2-image-streamer` instances on the same host,
each one needs its own unique set of four ports.

## Troubleshooting

### No frames received from the topic

See the FastDDS shared memory note in `ros2-fedora-base/README.md`. Make sure
you are using the latest base image which ships `fastdds.xml` with shared memory
disabled.

### FFmpeg codec errors

The Containerfile adds RPM Fusion repos to install the full `ffmpeg` build with
H264/x264 support. If you see codec errors, ensure the image was built with
`--no-cache` after the RPM Fusion step was added.
