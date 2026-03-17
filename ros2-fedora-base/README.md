# ros2-fedora-base

Common base image for all ROS2 containerized services. Not run directly.

Built on `fedora:42` with the `tavie/ros2` COPR repository for ROS2 Kilted packages.

## What it includes

- ROS2 Kilted (`ros-kilted-ros-base`, `ros-kilted-rmw-cyclonedds-cpp`, `ros-kilted-vision-msgs`)
- `python3-colcon-common-extensions` — build tool for ROS2 packages
- Dev tools: `cmake`, `gcc-c++`, `git`, `make`, `python3-rosdep`, `flake8`, etc.
- OpenSSH server with X11 forwarding enabled
- `fastdds.xml` — disables FastDDS shared memory transport (required for cross-container DDS communication)

## Baked-in environment variables

| Variable                        | Value                      | Reason |
|---------------------------------|----------------------------|--------|
| `ROS_HOME`                      | `/tmp/ros_home`            | `/ros2_ws/.ros` is not writable at runtime |
| `RMW_IMPLEMENTATION`            | `rmw_fastrtps_cpp`         | All containers must use the same RMW |
| `FASTDDS_DEFAULT_PROFILES_FILE` | `/etc/ros2/fastdds.xml`    | Disables shared memory — containers have separate mount namespaces even with `--network host` |

## Why FastDDS shared memory is disabled

FastDDS uses shared memory by default for localhost communication.
Shared memory segments created in one container are not accessible from
another container even with `--network host` (separate mount namespaces).
This causes topic discovery to work but data to never arrive. The bundled
`fastdds.xml` forces UDPv4 transport which works correctly across containers.

## Structure

```
ros2-fedora-base/
├── README.md
└── src/
    ├── Containerfile
    └── fastdds.xml
```

## Build

```bash
cd ros2-fedora-base/src
podman build -t ros2-fedora-base:latest .
```

> Must be built before any other service image.
