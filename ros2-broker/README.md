# ros2-broker

Optional monitoring service. Subscribes to ROS2 topics and publishes
health diagnostics on `/broker/camera_status`.

In the new architecture, this is no longer in the critical path.
Run it to get visibility into detection rates and topic health.

## Environment variables

| Variable                | Default        | Description |
|-------------------------|----------------|-------------|
| `CAMERA_TOPICS`         | _(empty)_      | Comma-separated topics to monitor |
| `HEALTH_CHECK_INTERVAL` | `5`            | Seconds between health evaluations |
| `STALE_TIMEOUT`         | `10`           | Seconds without messages before STALE |
| `REPUBLISH`             | `false`        | Re-publish on `/broker/<topic>/image` |
| `QOS_DEPTH`             | `5`            | QoS history depth |
| `VERBOSE`               | `false`        | Log every received message |
| `ROS_DOMAIN_ID`         | `0`            | ROS2 DDS domain ID |

## Build

```bash
cd ros2-fedora-base/src && podman build -t ros2-fedora-base:latest .
cd ros2-broker/src      && podman build -t ros2-broker:latest .
```

## Run

```bash
podman run --rm --network host \
  -e CAMERA_TOPICS="/detections" \
  ros2-broker:latest
```

## Diagnostics topic

```bash
ros2 topic echo /broker/camera_status
```
