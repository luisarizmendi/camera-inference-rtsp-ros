# ros2-fedora-base

Common base image for all ROS2 containerized services.

Built on `fedora:42` and includes:
- ROS2 Kilted via COPR (`tavie/ros2`)
- `ros-kilted-rmw-cyclonedds-cpp` — DDS middleware shared by all services
- Common runtime dependencies (`spdlog`, `lttng-ust`, `numpy`, etc.)
- Development tools (`cmake`, `gcc`, `colcon`, `rosdep`, `flake8`, etc.)
- OpenSSH server with X11 forwarding enabled
- FastDDS UDPv4-only profile (`fastdds.xml`) — disables shared memory transport
- Pre-configured runtime environment (see table below)

## Structure

```
ros2-fedora-base/
├── README.md
└── src/
    ├── Containerfile
    └── fastdds.xml
```

## Baked-in environment variables

These are set as `ENV` in the Containerfile and inherited by all derived images.
They can be overridden at runtime with `-e`.

| Variable                          | Value                        | Reason |
|-----------------------------------|------------------------------|--------|
| `ROS_HOME`                        | `/tmp/ros_home`              | Default `$HOME/.ros` resolves to `/ros2_ws/.ros` which is not writable at runtime |
| `RMW_IMPLEMENTATION`              | `rmw_fastrtps_cpp`           | Pins all services to the same RMW so they can exchange data. Mixed RMW environments allow topic discovery but silently block data transport |
| `FASTDDS_DEFAULT_PROFILES_FILE`   | `/etc/ros2/fastdds.xml`      | Points FastDDS to the UDPv4-only profile. FastDDS shared memory transport does not work across container boundaries even with `--network host` (separate mount namespaces) |

## FastDDS shared memory — why it is disabled

By default FastDDS uses shared memory for localhost communication. Shared memory
segments created in one container are not accessible from another container even
with `--network host`, because containers have separate mount namespaces. This
causes topic discovery to work (multicast) but data to never arrive in other
containers. The bundled `fastdds.xml` disables shared memory and forces UDPv4
transport, which works correctly across containers on the same host network.

## Build

```bash
cd ros2-fedora-base/src
podman build -t ros2-fedora-base:latest .
```

## Usage in derived images

```dockerfile
FROM ros2-fedora-base:latest
```

The three services that use this base are:
- `ros2-rtsp-bridge`
- `ros2-broker`
- `ros2-image-streamer`

## Build order

Always build the base image before any service image:

```bash
cd ros2-fedora-base/src    && podman build -t ros2-fedora-base:latest .
cd ros2-rtsp-bridge/src    && podman build -t ros2-rtsp-bridge:latest .
cd ros2-broker/src         && podman build -t ros2-broker:latest .
cd ros2-image-streamer/src && podman build -t ros2-image-streamer:latest .
```
