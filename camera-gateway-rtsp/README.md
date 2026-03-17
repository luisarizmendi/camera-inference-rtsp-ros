# camera-gateway-rtsp

USB webcam (or video file fallback) → MediaMTX → RTSP + WebRTC + HLS.

This service is unchanged from the original. It is the entry point for the
entire pipeline: the camera stream goes directly to the browser via WebRTC
(low latency), and is also available as RTSP for the inference service to pull.

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
  camera-gateway-rtsp:latest
```

## Ports

| Port      | Protocol | Description          |
|-----------|----------|----------------------|
| 8554      | RTSP     | Camera stream        |
| 8888      | HLS      | Web player           |
| 8889      | WebRTC   | Browser viewer       |
| 8189/udp  | ICE      | WebRTC media         |
