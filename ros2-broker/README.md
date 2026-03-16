# ros2-broker

Containerized service that acts as the **central ROS2 node** for the camera streaming system.
Subscribes to all configured image topics, monitors their liveness, and publishes
a consolidated diagnostic report on `/broker/camera_status`.

Built on `ros2-fedora-base:latest`. Run a single instance per ROS2 domain.

## Structure

```
ros2-broker/
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
| `CAMERA_TOPICS`         | _(empty)_      | Comma-separated list of topics to monitor |
| `HEALTH_CHECK_INTERVAL` | `5`            | Seconds between health evaluations |
| `STALE_TIMEOUT`         | `10`           | Seconds without frames before marking a topic STALE |
| `REPUBLISH`             | `false`        | Re-publish each topic on `/broker/<topic>/image` |
| `QOS_DEPTH`             | `5`            | QoS history depth |
| `VERBOSE`               | `false`        | Log every received frame |
| `ROS_DOMAIN_ID`         | `0`            | ROS2 DDS domain ID |

## Build

```bash
cd ros2-fedora-base/src && podman build -t ros2-fedora-base:latest .
cd ros2-broker/src      && podman build -t ros2-broker:latest .
```

## Run

```bash
podman run --rm --network host \
  -e CAMERA_TOPICS="/camera/front/image_raw,/camera/rear/image_raw" \
  -e STALE_TIMEOUT="10" \
  -e HEALTH_CHECK_INTERVAL="5" \
  ros2-broker:latest
```

## Diagnostics topic

The broker publishes `diagnostic_msgs/DiagnosticArray` on `/broker/camera_status`.

```bash
ros2 topic echo /broker/camera_status
```

Each entry reports:

| Field           | Description |
|-----------------|-------------|
| `level`         | `0` = OK · `2` = STALE |
| `total_frames`  | Frames received since startup |
| `fps_estimate`  | Estimated FPS over the last 2 seconds |
| `last_seen_ago` | Time since the last frame |

## Troubleshooting

### Topics visible but no data received

This is almost always a FastDDS shared memory issue. The base image ships a
`fastdds.xml` profile that disables shared memory and forces UDPv4 transport,
which is required for data to flow between containers. Make sure you are using
the latest base image build.

To verify data is flowing from inside the broker container:

```bash
podman exec -it <container_id> /bin/bash
source /usr/lib64/ros2-kilted/setup.bash
ros2 topic hz /camera/front/image_raw
```

### Checking RMW implementation

All containers must use the same RMW. The base image sets
`RMW_IMPLEMENTATION=rmw_fastrtps_cpp`. Verify inside any container:

```bash
source /usr/lib64/ros2-kilted/setup.bash
ros2 doctor --report | grep "middleware name"
```
