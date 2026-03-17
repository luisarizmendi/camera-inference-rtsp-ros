# ros2-fedora-base

Common base image for all ROS2 containerized services. Built on `fedora:42`.

## What it includes

- ROS2 Kilted via COPR (`tavie/ros2`)
- `ros-kilted-vision-msgs` — shared message types for detections
- `ros-kilted-rmw-cyclonedds-cpp` — DDS middleware
- Dev tools (`cmake`, `gcc`, `colcon`, `rosdep`, `flake8`, etc.)
- OpenSSH server with X11 forwarding enabled
- `fastdds.xml` — disables shared memory transport (required for cross-container communication)

## Baked-in environment variables

| Variable                        | Value                     | Reason |
|---------------------------------|---------------------------|--------|
| `ROS_HOME`                      | `/tmp/ros_home`           | Default resolves to non-writable `/ros2_ws/.ros` |
| `RMW_IMPLEMENTATION`            | `rmw_fastrtps_cpp`        | All services must use the same RMW |
| `FASTDDS_DEFAULT_PROFILES_FILE` | `/etc/ros2/fastdds.xml`   | Disables shared memory across containers |

## Build

```bash
cd ros2-fedora-base/src
podman build -t ros2-fedora-base:latest .
```

## Build order

```bash
cd ros2-fedora-base/src  && podman build -t ros2-fedora-base:latest .
cd ros2-inference/src    && podman build -t ros2-inference:latest .
cd ros2-rosbridge/src    && podman build -t ros2-rosbridge:latest .
cd ros2-broker/src       && podman build -t ros2-broker:latest .   # optional
```
