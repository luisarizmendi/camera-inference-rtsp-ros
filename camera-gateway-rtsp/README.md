# camera-gateway-rtsp

USB webcam (or video file fallback) → MediaMTX → RTSP + WebRTC + HLS.

This service is the entry point for the entire pipeline:
- The browser receives the video stream directly via WebRTC (~150ms latency)
- The inference service pulls the same stream via RTSP

## Structure

```
camera-gateway-rtsp/
├── README.md
└── src/
    ├── Containerfile
    ├── entrypoint.sh
    ├── mediamtx.yml
    └── stream.py
```

## How it works

`entrypoint.sh` starts MediaMTX, waits for the RTSP port to be ready,
then runs `stream.py`. The Python script probes `/dev/video*` devices,
picks the first working webcam, and streams it to MediaMTX via FFmpeg.
If no camera is found it falls back to looping video files from `VID_DIR`.

## Environment variables

### Stream output
| Variable    | Default       | Description |
|-------------|---------------|-------------|
| `RTSP_HOST` | `127.0.0.1`   | MediaMTX host for FFmpeg to push to |
| `RTSP_PORT` | `8554`        | RTSP port |
| `RTSP_NAME` | `stream`      | Stream path (`rtsp://host:8554/stream`) |

### Webcam options
| Variable            | Default     | Description |
|---------------------|-------------|-------------|
| `CAM_FRAMERATE`     | `30`        | Capture framerate |
| `CAM_RESOLUTION`    | _(auto)_    | Resolution e.g. `1280x720`; empty = camera default |
| `CAM_VIDEO_CODEC`   | `libx264`   | FFmpeg video codec |
| `CAM_VIDEO_BITRATE` | `600k`      | Video bitrate |
| `CAM_AUDIO_CODEC`   | `libopus`   | Audio codec |
| `CAM_AUDIO_BITRATE` | `64k`       | Audio bitrate |
| `CAM_PRESET`        | `ultrafast` | x264 preset |
| `CAM_TUNE`          | `zerolatency` | x264 tune |
| `CAM_RTBUFSIZE`     | `100M`      | FFmpeg input ring buffer size |

### Video file fallback
| Variable            | Default     | Description |
|---------------------|-------------|-------------|
| `VID_DIR`           | `/videos`   | Directory to scan for video files |
| `VID_VIDEO_CODEC`   | `libx264`   | Video codec for file streaming |
| `VID_VIDEO_BITRATE` | `600k`      | Bitrate for file streaming |
| `VID_PRESET`        | `fast`      | x264 preset for file streaming |

### Misc
| Variable               | Default | Description |
|------------------------|---------|-------------|
| `DEVICE_PROBE_TIMEOUT` | `5`     | Seconds to wait when probing a camera device |

## Ports

| Port      | Protocol | Description |
|-----------|----------|-------------|
| 8554      | RTSP     | Camera stream (pulled by ros2-inference) |
| 8888      | HLS      | Web player |
| 8889      | WebRTC   | Browser viewer (WHEP endpoint) |
| 8189/udp  | ICE      | WebRTC media transport |

## Build

```bash
cd camera-gateway-rtsp/src
podman build -t camera-gateway-rtsp:latest .
```

## Run

```bash
podman run --rm \
  --device /dev/video0 \
  --security-opt label=disable \
  --group-add $(getent group video | cut -d: -f3) \
  -p 8554:8554 -p 8888:8888 -p 8889:8889 -p 8189:8189/udp \
  -e MTX_WEBRTCADDITIONALHOSTS=192.168.1.41 \
  -e CAM_FRAMERATE=30 \
  -e CAM_RESOLUTION=1280x720 \
  camera-gateway-rtsp:latest
```
