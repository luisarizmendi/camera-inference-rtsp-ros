# Running the stack

This directory has two ways to run the camera inference stack:

- **`compose.yml`**, run everything with a single `podman compose` command. Good for development and quick testing.
- **`quadlets/`**, run each container as a native systemd service. Good for production and boot-persistent setups.

---

## Before you start

### 1. Find your host LAN IP

Both run methods need the LAN IP of the machine running the stack, so that WebRTC ICE candidates and the RTSP pull URL point to the right address. Replace `192.168.1.41` in the examples below with your actual IP.

```bash
ip -4 addr show | grep -oP '(?<=inet )\d+\.\d+\.\d+\.\d+' | grep -v 127
```

### 2. Check your camera device

The default device is `/dev/video0`. Verify yours:
```bash
v4l2-ctl --list-devices
# or
ls /dev/video*
```

### 3. Ensure the camera device is accessible

The container needs read/write access to the camera device (e.g. `/dev/video0`). The user running the container must be a member of the `video` group:

```bash
sudo usermod -aG video $USER
# Log out and back in for the group change to take effect, then verify:
id $USER | grep video
```

Pass the device and group when running the container:

```bash
--device /dev/video0 \
--group-add $(getent group video | cut -d: -f3)
```

### 4. NVIDIA GPU (optional)

To use the GPU for inference, CDI must be configured on the host first. Without it Podman will fail with `unresolvable CDI devices nvidia.com/gpu=all`.

**Install the NVIDIA Container Toolkit** (if not already installed):

```bash
# RHEL/Fedora
sudo dnf install -y nvidia-container-toolkit

# Ubuntu/Debian
curl -fsSL https://nvidia.github.io/libnvidia-container/gpgkey \
  | sudo gpg --dearmor -o /usr/share/keyrings/nvidia-container-toolkit-keyring.gpg
curl -sL https://nvidia.github.io/libnvidia-container/stable/deb/nvidia-container-toolkit.list \
  | sudo tee /etc/apt/sources.list.d/nvidia-container-toolkit.list
sudo apt-get update && sudo apt-get install -y nvidia-container-toolkit
```

**Generate the CDI specification:**

```bash
sudo nvidia-ctk cdi generate --output=/etc/cdi/nvidia.yaml
```

Verify it worked:

```bash
nvidia-ctk cdi list
# Expected output includes: nvidia.com/gpu=all
```

> Re-run `nvidia-ctk cdi generate` after any driver upgrade or GPU configuration change.

---

## Option A — Podman Compose

### Requirements

`podman-compose` installed:
```bash
dnf install podman-compose
# or
pip install podman-compose
```

### Configure

Open `compose/compose.yml` and update the values marked with `########`:

```yaml
# In ros2-inference:
RTSP_URL: "rtsp://<YOUR_HOST_IP>:8554/stream"

# In camera-gateway-rtsp (uncomment if WebRTC ICE fails):
# MTX_WEBRTCADDITIONALHOSTS: "<YOUR_HOST_IP>"
```

Update the camera device if needed (default `/dev/video0`):
```yaml
devices:
  - /dev/video0
```

### Start

```bash
cd _run_/compose
podman compose up -d
```

### Check status

```bash
podman compose ps
podman compose logs -f                 # all services
podman compose logs -f ros2-inference  # single service
```

### Stop

```bash
podman compose down
```

### GPU inference

Uncomment the `devices` block and set `DEVICE` in the `ros2-inference` section of `compose.yml`:

```yaml
ros2-inference:
  ...
  devices:
    - nvidia.com/gpu=all
  environment:
    DEVICE: "cuda"
```

### Custom model

Mount the model file and set `INFERENCE_MODEL`. Both `.pt` and `.onnx` are supported:

```yaml
ros2-inference:
  volumes:
    - /path/to/my_model.onnx:/opt/models/my_model.onnx:ro
  environment:
    INFERENCE_MODEL: "my_model.onnx"
```

### Class names for custom models

If your model does not embed class names (common with third-party ONNX exports), provide them via env var or file:

```yaml
# Option A — inline list
environment:
  CLASS_NAMES: "person,bicycle,car,motorcycle,bus,truck"

# Option B — file (one name per line, line 0 = class 0)
volumes:
  - /path/to/classes.txt:/opt/models/classes.txt:ro
environment:
  CLASS_NAMES_FILE: "/opt/models/classes.txt"
```

### Service summary

| Service | Ports | Notes |
|---------|-------|-------|
| `camera-gateway-rtsp` | 8554 (RTSP), 8888 (HLS), 8889 (WebRTC), 8189/udp (ICE) | `network_mode: host` |
| `ros2-inference` | (none mapped) | `network_mode: host`, RTSP pull + DDS |
| `ros2-rosbridge` | 9099 (WebSocket) | `network_mode: host`, DDS |
| `image-inference-viewer` | 8080 (HTTP) | bridge network is fine |

The ROS2 containers use `network_mode: host` because DDS multicast does not reliably cross Podman bridge networks.

---

## Option B — Podman Quadlets (systemd)

Quadlets turn `.container` files into systemd units automatically. Each container becomes a proper systemd service with boot start, failure restart, and `journalctl` integration.

### Requirements

- Podman 4.4 or newer (quadlet support built in)
- systemd (standard on Fedora, RHEL, CentOS Stream)

### Configure

Edit the `.container` files in `quadlets/` before installing. At minimum:

**`camera-gateway-rtsp.container`** — set your LAN IP and video device:
```ini
Environment=MTX_WEBRTCADDITIONALHOSTS=192.168.1.41
AddDevice=/dev/video0
AddGroup=44   # GID of the 'video' group on your host
```

Find the `video` group GID:
```bash
getent group video | cut -d: -f3
```

**`ros2-inference.container`** — set your LAN IP:
```ini
Environment=RTSP_URL=rtsp://192.168.1.41:8554/stream
```

To use a custom model, mount it and set `INFERENCE_MODEL`:
```ini
Volume=/path/to/my_model.onnx:/opt/models/my_model.onnx:ro
Environment=INFERENCE_MODEL=my_model.onnx
```

To provide class names for models without embedded metadata:
```ini
# Option A — inline list
Environment=CLASS_NAMES=person,bicycle,car,motorcycle,bus,truck

# Option B — file (mount it first)
Volume=/path/to/classes.txt:/opt/models/classes.txt:ro
Environment=CLASS_NAMES_FILE=/opt/models/classes.txt
```

### Install, rootless (user session)

Rootless quadlets run under your user session without root. They start when you log in, or at boot if lingering is enabled.

```bash
mkdir -p ~/.config/containers/systemd/
cp quadlets/*.container quadlets/*.network ~/.config/containers/systemd/
systemctl --user daemon-reload

# Check the units were generated correctly
systemctl --user list-units 'camera-*' 'ros2-*' 'image-*'
```

Start the services:
```bash
systemctl --user start camera-gateway-rtsp.service
systemctl --user start ros2-inference.service
systemctl --user start ros2-rosbridge.service
systemctl --user start image-inference-viewer.service
```

Enable at boot:
```bash
loginctl enable-linger $USER

systemctl --user enable camera-gateway-rtsp.service
systemctl --user enable ros2-inference.service
systemctl --user enable ros2-rosbridge.service
systemctl --user enable image-inference-viewer.service
```

### Install, system-wide (root)

```bash
sudo cp quadlets/*.container quadlets/*.network /etc/containers/systemd/
sudo systemctl daemon-reload

sudo systemctl start camera-gateway-rtsp.service
sudo systemctl start ros2-inference.service
sudo systemctl start ros2-rosbridge.service
sudo systemctl start image-inference-viewer.service

sudo systemctl enable camera-gateway-rtsp.service
sudo systemctl enable ros2-inference.service
sudo systemctl enable ros2-rosbridge.service
sudo systemctl enable image-inference-viewer.service
```

### Check status

```bash
# Rootless
systemctl --user status camera-gateway-rtsp.service
journalctl --user -u ros2-inference.service -f

# System-wide
systemctl status camera-gateway-rtsp.service
journalctl -u ros2-inference.service -f
```

### Stop and remove

```bash
# Rootless
systemctl --user stop camera-gateway-rtsp.service ros2-inference.service \
  ros2-rosbridge.service image-inference-viewer.service

rm ~/.config/containers/systemd/camera-gateway-rtsp.container \
   ~/.config/containers/systemd/ros2-inference.container \
   ~/.config/containers/systemd/ros2-rosbridge.container \
   ~/.config/containers/systemd/image-inference-viewer.container \
   ~/.config/containers/systemd/camera-inference.network
systemctl --user daemon-reload
```

### GPU inference with quadlets

In `ros2-inference.container`, uncomment:
```ini
AddDevice=nvidia.com/gpu=all
SecurityLabelDisable=true
Environment=DEVICE=cuda
```

Then reload and restart:
```bash
systemctl --user daemon-reload
systemctl --user restart ros2-inference.service
```

### How quadlets work

Podman reads `.container` and `.network` files from `~/.config/containers/systemd/` (rootless) or `/etc/containers/systemd/` (system) and generates full systemd unit files under `/run/systemd/generator/`. You never write the `[Service]` section by hand — quadlet translates directives like `Image=`, `Network=`, `Environment=`, and `Volume=` into the right `podman run` arguments.

To inspect the generated unit:
```bash
systemctl --user cat camera-gateway-rtsp.service
```

---

## Open the viewer

Once all services are running, open:

```
http://<host-ip>:8080
```

Fill in the connection sidebar:

| Field | Value |
|-------|-------|
| MediaMTX host | `<host-ip>` |
| MediaMTX WebRTC port | `8889` |
| Stream name | `stream` |
| rosbridge WebSocket | `ws://<host-ip>:9099` |

The host fields are pre-filled when you open the viewer from the same machine. Click **Connect** and the video and overlay activate independently as each connection is established.

---

## Firewall

If you are running firewalld, open the required ports:

```bash
sudo firewall-cmd --add-port=8554/tcp --permanent
sudo firewall-cmd --add-port=8888/tcp --permanent
sudo firewall-cmd --add-port=8889/tcp --permanent
sudo firewall-cmd --add-port=8189/udp --permanent
sudo firewall-cmd --add-port=9099/tcp --permanent
sudo firewall-cmd --add-port=8080/tcp --permanent
sudo firewall-cmd --reload
```
