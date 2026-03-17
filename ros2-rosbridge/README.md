# ros2-rosbridge

Exposes all ROS2 topics as a WebSocket server using `rosbridge_suite`.
The browser viewer connects to this service to receive detection messages.

## Build

```bash
cd ros2-fedora-base/src  && podman build -t ros2-fedora-base:latest .
cd ros2-rosbridge/src    && podman build -t ros2-rosbridge:latest .
```

## Run

```bash
podman run --rm --network host \
  -e ROSBRIDGE_PORT=9099 \
  ros2-rosbridge:latest
```

## Environment variables

| Variable         | Default | Description              |
|------------------|---------|--------------------------|
| `ROSBRIDGE_PORT` | `9099`  | WebSocket server port    |
| `ROS_DOMAIN_ID`  | `0`     | ROS2 DDS domain ID       |
