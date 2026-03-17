# ros2-broker-watch

Optional monitoring service. Subscribes to ROS2 topics and publishes health
diagnostics on `/broker/camera_status` as `diagnostic_msgs/DiagnosticArray`.

In this architecture it is not in the critical path. Run it to get visibility
into detection rates and topic liveness.

## Structure

```
ros2-broker-watch/
├── README.md
└── src/
    ├── Containerfile
    ├── entrypoint.sh
    └── ros2_pkg/
        ├── package.xml
        ├── setup.cfg
        ├── setup.py
        ├── resource/
        │   └── image_broker
        └── image_broker/
            ├── __init__.py
            └── image_broker_node.py
```

## Environment variables

| Variable                | Default        | Description |
|-------------------------|----------------|-------------|
| `BROKER_NODE_NAME`      | `image_broker` | ROS2 node name |
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
cd ros2-broker-watch/src      && podman build -t ros2-broker-watch:latest .
```

## Run

```bash
podman run --rm --network host \
  -e CAMERA_TOPICS="/detections" \
  -e STALE_TIMEOUT="5" \
  ros2-broker-watch:latest
```

## Diagnostics

```bash
ros2 topic echo /broker/camera_status
```

Each entry reports:

| Field           | Description |
|-----------------|-------------|
| `level`         | `0` = OK · `2` = STALE |
| `total_frames`  | Messages received since startup |
| `fps_estimate`  | Estimated messages/s over last 2s |
| `last_seen_ago` | Time since the last message |
