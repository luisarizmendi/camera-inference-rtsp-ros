# camera-gateway-rtsp

A self-contained container that turns a USB webcam (or a folder of video files) into a live stream accessible over multiple protocols — RTSP, HLS, and WebRTC — all from a single `podman run` command.

## What it does

When the container starts it runs two processes:

1. **MediaMTX** — a lightweight media server that acts as the RTSP/HLS/WebRTC broker.
2. **stream.py** — a Python script that detects a working USB webcam and streams it to MediaMTX using FFmpeg. If no camera is found (or none produces a valid image), it falls back to looping all video files found in the `/videos` directory, sorted by filename, restarting from the beginning when the playlist ends. If neither a camera nor video files are available, the container exits with a clear error message.

```
┌─────────────────────────────────────────┐
│              Container                  │
│                                         │
│  ┌──────────┐    RTSP    ┌───────────┐  │
│  │ stream.py│ ─────────► │  MediaMTX │  │
│  │ (ffmpeg) │            │           │  │
│  └──────────┘            └─────┬─────┘  │
│       ▲                        │        │
│       │                   ┌────┴──────┐ │
│  /dev/video*          RTSP │ HLS│WebRTC│ │
│  /videos/             └────┴───┴──────┘ │
└─────────────────────────────────────────┘
            │             │
        VLC/ffplay      Browser
```

The stream is encoded as **H.264 + Opus**, which is compatible with RTSP players (VLC, ffplay) and all modern browsers via WebRTC. Audio is only included if the webcam has a built-in microphone — video-only cameras are handled automatically with no warnings.

## Requirements

- Podman (or Docker)
- A V4L2-compatible USB webcam exposed as `/dev/video*`, OR a directory of video files (mp4, mkv, avi, mov, ts, flv, webm)
- Linux host (tested on Fedora)

## Quick start

### Camera mode

The recommended way to grant device access on SELinux hosts (Fedora/RHEL) is `--security-opt label=disable`, which disables SELinux confinement for the container without granting full root privileges like `--privileged` would:

```bash
podman run -it --rm \
  --device /dev/video0 \
  --security-opt label=disable \
  --group-add $(getent group video | cut -d: -f3) \
  -p 8554:8554 -p 8888:8888 -p 8889:8889 -p 8189:8189/udp \
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
  --security-opt label=disable \
  --group-add $(getent group video | cut -d: -f3) \
  -p 8554:8554 -p 8888:8888 -p 8889:8889 -p 8189:8189/udp \
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
| `CAM_AUDIO_CODEC` | `libopus` | Audio encoder (only used if the webcam has a mic) |
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

## Camera detection

The container probes all `/dev/video*` devices passed via `--device` in alphabetical order. For each device it:

1. Checks read permissions and warns clearly if access is denied.
2. Uses `v4l2-ctl` to verify the node is a video capture device (skipping metadata and output-only nodes — many webcams register multiple `/dev/video*` entries).
3. Tries to grab a frame using mjpeg, yuyv422, and auto format in sequence, picking the first that works.

The first device that successfully produces a frame is used. If you have multiple cameras and want a specific one, pass only that device node:

```bash
--device /dev/video2
```

To find which device node your camera uses:
```bash
v4l2-ctl --list-devices
```

## Device access on SELinux hosts (Fedora / RHEL)

SELinux prevents containers from accessing host devices by default even when `--device` is specified. There are two ways to grant access, in order of preference:

**Option 1 — disable SELinux labeling for the container (recommended):**
```bash
--security-opt label=disable
```
This disables SELinux confinement only for this container without granting full root privileges.

**Option 2 — full privileged mode (less secure, avoid in production):**
```bash
--privileged
```

In both cases, also pass the video group GID so the container process can open the device:
```bash
--group-add $(getent group video | cut -d: -f3)
```

> Note: `--group-add video` (by name) often fails because the `video` group inside the container image may have a different GID than on the host. Using the numeric GID from the host avoids this mismatch.

## SELinux note for volume mounts

On Fedora/RHEL hosts, volume mounts also require the `:z` flag to relabel the directory for container access:

```bash
-v /path/to/videos:/videos:ro,z
```

Without `:z` the container will get a `Permission denied` error even if the directory exists and is readable on the host.

## Troubleshooting

**Camera detected but no image / falls back to video files**
Run with `--security-opt label=disable` and the numeric video GID (see above). Check the probe output in the logs — it now prints the actual ffmpeg error for each failed device.

**`Permission denied` on `/dev/videoN` inside the container**
SELinux is blocking device access. Use `--security-opt label=disable` instead of relying on `--group-add video` alone.

**`Permission denied` on `/videos`**
Add `:z` to the volume mount: `-v /path/to/videos:/videos:ro,z`.

**Container exits immediately with no camera and no files**
Either no `--device` was passed, or the `/videos` directory is empty or not mounted. The container exits with a clear error message in this case rather than looping indefinitely.

**WebRTC — no video in browser**
Make sure `MTX_WEBRTCADDITIONALHOSTS` is set to the LAN IP of the host. Without it, the WebRTC ICE negotiation fails on local networks. Also verify port `8189/udp` is mapped and not blocked by a firewall.

**HLS or WebRTC codec errors in browser**
The stream uses H.264 baseline profile level 4.2 + Opus, which is supported by all modern browsers. If you changed the codec via env vars, revert to the defaults.

**ffmpeg drops frames / buffer overflow warnings**
Increase `CAM_RTBUFSIZE`, e.g. `-e CAM_RTBUFSIZE=200M`.

**`Dequeued v4l2 buffer contains corrupted data` warnings**
These appear for the first few frames while the camera sensor warms up. They are harmless and stop after a second or two.
