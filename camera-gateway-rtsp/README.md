# camera-gateway-rtsp

A self-contained container that turns a USB webcam (or a folder of video files) into a live stream accessible over multiple protocols — RTSP, HLS, and WebRTC — all from a single `podman run` command.

## What it does

When the container starts it runs two processes:

1. **MediaMTX** — a lightweight media server that acts as the RTSP/HLS/WebRTC broker.
2. **stream.py** — a Python script that detects a working USB webcam and streams it to MediaMTX using FFmpeg. If no camera is found (or none produces a valid image), it falls back to looping all video files found in the `/videos` directory, sorted by filename, restarting from the beginning when the playlist ends.

```
┌─────────────────────────────────────────┐
│              Container                  │
│                                         │
│  ┌──────────┐    RTSP    ┌───────────┐  │
│  │ stream.py│ ─────────► │  MediaMTX │  │
│  │ (ffmpeg) │            │           │  │
│  └──────────┘            └─────┬─────┘  │
│       ▲                        │        │
│       │                   ┌────┴─────┐  │
│  /dev/video*          RTSP │HLS│WebRTC│  │
│  /videos/             └────┴──┴──────┘  │
└─────────────────────────────────────────┘
         │                  │
    VLC/ffplay          Browser
```

The stream is encoded as **H.264 + Opus**, which is compatible with RTSP players (VLC, ffplay) and all modern browsers via WebRTC.

## Requirements

- Podman (or Docker)
- A V4L2-compatible USB webcam exposed as `/dev/video*`, OR a directory of video files (mp4, mkv, avi, mov, ts, flv, webm)
- Linux host (tested on Fedora)

## Quick start

### Camera mode

```bash
podman run -it --rm \
  --device /dev/video0 \
  -p 8554:8554 -p 8888:8888 -p 8889:8889 -p 8189:8189/udp \
  --group-add video \
  -e MTX_WEBRTCADDITIONALHOSTS=<your-host-ip> \
  quay.io/luisarizmendi/camera-gateway-rtsp:latest
```

### Video file fallback mode (no camera)

```bash
podman run -it --rm \
  -p 8554:8554 -p 8888:8888 -p 8889:8889 -p 8189:8189/udp \
  -v /path/to/videos:/videos:ro,z \
  -e MTX_WEBRTCADDITIONALHOSTS=<your-host-ip> \
  quay.io/luisarizmendi/camera-gateway-rtsp:latest
```

### Both (camera with video fallback)

```bash
podman run -it --rm \
  --device /dev/video0 \
  -p 8554:8554 -p 8888:8888 -p 8889:8889 -p 8189:8189/udp \
  --group-add video \
  -v /path/to/videos:/videos:ro,z \
  -e MTX_WEBRTCADDITIONALHOSTS=<your-host-ip> \
  quay.io/luisarizmendi/camera-gateway-rtsp:latest
```

Replace `<your-host-ip>` with the LAN IP of the machine running the container (e.g. `192.168.1.41`). This is required for WebRTC to work from a browser — without it the media connection cannot be established.

## Accessing the stream

| Protocol | URL | Client |
|----------|-----|--------|
| RTSP | `rtsp://<host-ip>:8554/stream` | VLC, ffplay, any RTSP player |
| HLS | `http://<host-ip>:8888/stream` | Browser, VLC |
| WebRTC | `http://<host-ip>:8889/stream` | Browser (lowest latency) |

**WebRTC** gives the lowest latency (sub-second). Open the URL in any modern browser — MediaMTX serves a built-in player at that address.

**HLS** has higher latency (3–10 s) but is the most broadly compatible option if WebRTC is not working.

**RTSP** is best for local network players like VLC or ffplay:
```bash
vlc rtsp://192.168.1.41:8554/stream
ffplay rtsp://192.168.1.41:8554/stream
```

## Ports

| Port | Protocol | Purpose |
|------|----------|---------|
| 8554 | TCP | RTSP |
| 8888 | TCP | HLS (HTTP) |
| 8889 | TCP | WebRTC signaling (HTTP) |
| 8189 | UDP | WebRTC ICE media path |

All four ports must be exposed/mapped for full functionality. The UDP port 8189 is critical for WebRTC — without it the browser can connect for signaling but no video will flow.

## Environment variables

All behaviour is controlled via environment variables. Pass them with `-e KEY=value` or `--env-file .env`.

### Stream destination (internal MediaMTX)

| Variable | Default | Description |
|----------|---------|-------------|
| `RTSP_HOST` | `127.0.0.1` | MediaMTX host (keep as-is when bundled) |
| `RTSP_PORT` | `8554` | RTSP port |
| `RTSP_NAME` | `stream` | Stream path name |

### Webcam options

| Variable | Default | Description |
|----------|---------|-------------|
| `CAM_VIDEO_CODEC` | `libx264` | Video encoder |
| `CAM_AUDIO_CODEC` | `libopus` | Audio encoder |
| `CAM_VIDEO_BITRATE` | `600k` | Video bitrate |
| `CAM_AUDIO_BITRATE` | `64k` | Audio bitrate |
| `CAM_PRESET` | `ultrafast` | x264 encoding preset |
| `CAM_TUNE` | `zerolatency` | x264 tune |
| `CAM_FRAMERATE` | `30` | Capture frame rate |
| `CAM_RESOLUTION` | _(empty)_ | Force resolution e.g. `1280x720`. Empty = camera default |
| `CAM_RTBUFSIZE` | `100M` | Input ring-buffer size (increase if frames are dropped) |

### Video file fallback options

| Variable | Default | Description |
|----------|---------|-------------|
| `VID_DIR` | `/videos` | Directory scanned for video files |
| `VID_VIDEO_CODEC` | `libx264` | Video encoder |
| `VID_AUDIO_CODEC` | `libopus` | Audio encoder |
| `VID_VIDEO_BITRATE` | `600k` | Video bitrate |
| `VID_AUDIO_BITRATE` | `64k` | Audio bitrate |
| `VID_PRESET` | `fast` | x264 encoding preset |

### MediaMTX overrides

MediaMTX supports overriding any config key via `MTX_<UPPERCASEKEY>` environment variables. The most useful ones:

| Variable | Example | Description |
|----------|---------|-------------|
| `MTX_WEBRTCADDITIONALHOSTS` | `192.168.1.41` | **Required for WebRTC from LAN.** Host IP advertised to WebRTC clients as an ICE candidate |

### Misc

| Variable | Default | Description |
|----------|---------|-------------|
| `DEVICE_PROBE_TIMEOUT` | `5` | Seconds to wait when probing each `/dev/video*` device |

## Building from source

```bash
cd src/
podman build -t camera-gateway-rtsp -f Containerfile .
```

For ARM64 (e.g. Raspberry Pi), change the MediaMTX download URL in the `Containerfile`:
```
mediamtx_v1.9.3_linux_arm64v8.tar.gz
```

## SELinux note

On Fedora/RHEL hosts, volume mounts require the `:z` flag to relabel the directory for container access:

```bash
-v /path/to/videos:/videos:ro,z
```

Without `:z` the container will get a `Permission denied` error even if the directory exists and is readable on the host.

## Camera detection

The container probes all `/dev/video*` devices in alphabetical order and picks the first one that successfully captures a frame. If you have multiple cameras and want to use a specific one, pass only that device:

```bash
--device /dev/video2
```

If your camera device is not `/dev/video0`, check which device node it uses:
```bash
v4l2-ctl --list-devices
```

## Troubleshooting

**WebRTC plays in the browser but no video appears**
Make sure `MTX_WEBRTCADDITIONALHOSTS` is set to the LAN IP of the host. Without it, the WebRTC ICE negotiation fails silently on local networks.

**`Permission denied` on `/videos`**
Add `:z` to the volume mount: `-v /path/to/videos:/videos:ro,z`. This is a SELinux relabeling requirement on Fedora/RHEL.

**Camera not detected**
Verify the device is accessible on the host with `v4l2-ctl --list-devices`, then pass the correct device node with `--device /dev/videoN`. Also ensure `--group-add video` is included so the container process can access video devices.

**Stream works in VLC but not in browser**
HLS (`http://<host>:8888/stream`) is the most compatible browser fallback — try that first. For WebRTC, make sure port `8189/udp` is mapped and not blocked by a firewall.

**ffmpeg drops frames / buffer overflow warnings**
Increase `CAM_RTBUFSIZE`, e.g. `-e CAM_RTBUFSIZE=200M`.
