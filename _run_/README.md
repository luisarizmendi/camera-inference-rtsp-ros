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

The `camera-gateway-rtsp` container requires read/write access to `/dev/video0` from the user running the container.

**On Fedora desktop** this works automatically — `systemd-logind` grants the logged-in user an ACL on every `/dev/video*` device at login.

**On RHEL, CentOS Stream, or any headless/embedded system** (e.g. NVIDIA Jetson) this automatic ACL is not applied. You will see:

```
[WARNING] Cannot read /dev/video0 — permission denied.
```

even when using `--device /dev/video0` and `--group-add video`.

**Fix — run this once and it survives reboots:**

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
```

Replace `YOUR_USER` with the user that will run the container. Verify it worked:

```bash
getfacl /dev/video0   # must show:  user:YOUR_USER:rw-
```

See [`camera-gateway-rtsp/README.md`](../camera-gateway-rtsp/README.md#camera-device-permissions) for full background and alternative approaches.

---

### Requirements

`podman-compose` installed:
```bash
dnf install podman-compose
# or
pip install podman-compose
```

### Configure

Open `compose/compose.yml` and update the two values marked with `########`:

```yaml
# In ros2-inference:
RTSP_URL: "rtsp://<YOUR_HOST_IP>:8554/stream"

# In camera-gateway-rtsp (uncomment):
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

Uncomment the `devices` block in the `ros2-inference` section of `compose.yml`:

```yaml
ros2-inference:
  ...
  devices:
    - nvidia.com/gpu=all
  environment:
    DEVICE: "cuda"
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

## Option B, Podman Quadlets (systemd)

Quadlets turn `.container` files into systemd units automatically. Each container becomes a proper systemd service with boot start, failure restart, and `journalctl` integration.

### Requirements

- Podman 4.4 or newer (quadlet support built in)
- systemd (standard on Fedora, RHEL, CentOS Stream)

### Configure

Edit the `.container` files in `quadlets/` before installing. At minimum:

**`camera-gateway-rtsp.container`**, set your LAN IP and video device:
```ini
Environment=MTX_WEBRTCADDITIONALHOSTS=192.168.1.41
AddDevice=/dev/video0
AddGroup=44   # GID of the 'video' group on your host
```

Find the `video` group GID:
```bash
getent group video | cut -d: -f3
```

**`ros2-inference.container`**, set your LAN IP:
```ini
Environment=RTSP_URL=rtsp://192.168.1.41:8554/stream
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

Podman reads `.container` and `.network` files from `~/.config/containers/systemd/` (rootless) or `/etc/containers/systemd/` (system) and generates full systemd unit files under `/run/systemd/generator/`. You never write the `[Service]` section by hand, quadlet translates directives like `Image=`, `Network=`, `Environment=` and `PublishPort=` into the right `podman run` arguments.

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
