# image-inference-viewer

Static single-page HTML viewer served by nginx. The browser connects to
MediaMTX (WebRTC) and rosbridge (WebSocket) directly — nginx only delivers
the HTML file. All video decoding and overlay rendering happens client-side.

## Structure

```
viewer/
├── README.md
└── src/
    ├── Containerfile
    ├── nginx.conf
    └── index.html
```

## Build

```bash
cd viewer/src
podman build -t viewer:latest .
```

## Run

```bash
podman run --rm -p 8080:8080 viewer:latest
```

Then open `http://<host-ip>:8080` in any browser on the network.

## Usage

In the sidebar:
1. Set **MediaMTX host** to your host IP (e.g. `192.168.1.41`)
2. Set **rosbridge WebSocket** to `ws://192.168.1.41:9099`
3. Click **Connect**

The page auto-fills these fields from the hostname it was served from,
so if you open it from `http://192.168.1.41:8080` the fields are
pre-populated correctly.

## What runs where

| Component       | Runs on  | Description |
|-----------------|----------|-------------|
| nginx           | server   | Serves index.html |
| WebRTC client   | browser  | Decodes and renders video |
| WebSocket client| browser  | Receives detections from rosbridge |
| Canvas overlay  | browser  | Draws bounding boxes on top of video |

Nothing is proxied through nginx — the browser connects directly to
MediaMTX and rosbridge. nginx is purely a file delivery mechanism.


