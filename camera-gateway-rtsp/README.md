# camera-gateway-rtsp

Captures a USB webcam (or loops video files as fallback) and broadcasts it via MediaMTX as RTSP, WebRTC and HLS.

This is the entry point for the whole pipeline: the browser gets the video directly via WebRTC (~150 ms latency), and the inference service pulls the same stream over RTSP.

## Structure

```
camera-gateway-rtsp/
├── README.md
├── build.sh
└── src/
    ├── Containerfile
    ├── entrypoint.sh
    ├── mediamtx.yml
    └── stream.py
```

## How it works

`entrypoint.sh` starts MediaMTX, waits for the RTSP port to be ready, then runs `stream.py`. The script probes `/dev/video*` devices, picks the first working webcam, and streams it to MediaMTX via FFmpeg. If no camera is found it falls back to looping video files from `VID_DIR`.

The base image is Fedora latest with FFmpeg from RPM Fusion.

## Build

```bash
cd camera-gateway-rtsp
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

# Build and push to a custom registry
./build.sh --registry ghcr.io/myuser

# Cross-build amd64 + arm64 from an x86_64 host
./build.sh --cross
```

Or build manually:

```bash
podman build -t camera-gateway-rtsp:latest src/
```

## Environment variables

### Stream output

| Variable    | Default     | Description |
|-------------|-------------|-------------|
| `RTSP_HOST` | `127.0.0.1` | MediaMTX host for FFmpeg to push to |
| `RTSP_PORT` | `8554`      | RTSP port |
| `RTSP_NAME` | `stream`    | Stream path (`rtsp://host:8554/stream`) |

### Webcam options

| Variable            | Default       | Description |
|---------------------|---------------|-------------|
| `CAM_FRAMERATE`     | `30`          | Capture framerate |
| `CAM_RESOLUTION`    | _(auto)_      | Resolution, e.g. `1280x720`, empty means camera default |
| `CAM_VIDEO_CODEC`   | `libx264`     | FFmpeg video codec |
| `CAM_VIDEO_BITRATE` | `600k`        | Video bitrate |
| `CAM_AUDIO_CODEC`   | `libopus`     | Audio codec |
| `CAM_AUDIO_BITRATE` | `64k`         | Audio bitrate |
| `CAM_PRESET`        | `ultrafast`   | x264 preset |
| `CAM_TUNE`          | `zerolatency` | x264 tune |
| `CAM_RTBUFSIZE`     | `100M`        | FFmpeg input ring-buffer size |

### Video file fallback

| Variable            | Default   | Description |
|---------------------|-----------|-------------|
| `VID_DIR`           | `/videos` | Directory to scan for video files |
| `VID_VIDEO_CODEC`   | `libx264` | Video codec for file streaming |
| `VID_VIDEO_BITRATE` | `600k`    | Bitrate for file streaming |
| `VID_PRESET`        | `fast`    | x264 preset for file streaming |

### Misc

| Variable               | Default | Description |
|------------------------|---------|-------------|
| `DEVICE_PROBE_TIMEOUT` | `5`     | Seconds to wait when probing a camera device |

## Ports

| Port     | Protocol | Description |
|----------|----------|-------------|
| 8554     | RTSP     | Camera stream, pulled by ros2-inference |
| 8888     | HLS      | Web player |
| 8889     | WebRTC   | Browser viewer (WHEP endpoint) |
| 8189/udp | ICE      | WebRTC media transport |

## Camera device permissions

The container needs read/write access to `/dev/video0` (or whichever `/dev/video*` node your camera appears as) on the host.

### Why it works on Fedora but not on RHEL / headless systems

On a Fedora desktop `systemd-logind` automatically sets a POSIX ACL that grants the locally logged-in user direct access to every `/dev/video*` device:

```
user:youruser:rw-   ← added automatically by logind
```

On RHEL, CentOS Stream, or any headless system (including an NVIDIA Jetson) this automatic ACL is never applied, so even with `--device /dev/video0` and `--group-add video` the container process gets a `permission denied` error:

```
[WARNING] Cannot read /dev/video0 — permission denied.
```

### Diagnosing the problem

```bash
# Check whether your user already has an ACL entry:
getfacl /dev/video0

# Check the GID that owns the device:
ls -la /dev/video0

# Check whether the video group exists locally:
getent group video
grep video /etc/group   # empty output = managed by SSSD/LDAP
```

### Permanent fix — systemd service (works in all cases, no re-login needed)

```bash
sudo tee /etc/systemd/system/camera-acl.service <<'EOF'
[Unit]
Description=Set camera device ACL for the container user
After=systemd-udev-settle.service

[Service]
Type=oneshot
ExecStart=/usr/bin/setfacl -m u:YOUR_USER:rw /dev/video0
ExecStart=/usr/bin/setfacl -m u:YOUR_USER:rw /dev/video1

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl enable --now camera-acl.service

# Verify
getfacl /dev/video0   # must show user:YOUR_USER:rw-
```

Replace `YOUR_USER` with the actual user running the container. Add or remove `ExecStart` lines to match your `/dev/video*` devices.

### Alternative fix — add the user to the video group

```bash
# Works only if the video group is local (appears in /etc/group):
sudo usermod -aG video YOUR_USER
# Log out and back in, then verify:
id YOUR_USER | grep video
```

> If the `video` group is absent from `/etc/group` (managed by SSSD/LDAP), you cannot add local users to it — use the systemd service fix above instead.

### Why udev RUN+= rules do not work here

A `udev` rule with `RUN+="/usr/bin/setfacl ..."` looks attractive but on systems with SELinux enforcing (RHEL default) the udev worker process is denied the `setfacl` call and the rule silently does nothing. A systemd `oneshot` service runs in a less restricted SELinux context and is the reliable alternative.

## Run (standalone)

```bash
podman run --rm \
  --network host \
  --device /dev/video0 \
  --security-opt label=disable \
  --group-add $(getent group video | cut -d: -f3) \
  -e MTX_WEBRTCADDITIONALHOSTS=192.168.1.41 \
  -e CAM_FRAMERATE=30 \
  -e CAM_RESOLUTION=1280x720 \
  quay.io/luisarizmendi/camera-gateway-rtsp:latest
```

Set `MTX_WEBRTCADDITIONALHOSTS` to your host LAN IP so browsers on other machines receive usable WebRTC ICE candidates.
