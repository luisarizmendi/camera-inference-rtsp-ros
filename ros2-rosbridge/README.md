# ros2-rosbridge

Exposes ROS2 topics as a WebSocket server using `rosbridge_suite`.
The browser viewer connects to this service to receive detection messages
without needing a ROS2 installation.

## Structure

```
ros2-rosbridge/
├── README.md
└── src/
    ├── Containerfile
    └── entrypoint.sh
```

## How it works

`rosbridge_suite` is not available in the `tavie/ros2` COPR for Kilted, so
it is cloned from the official `ros2` branch of
[RobotWebTools/rosbridge_suite](https://github.com/RobotWebTools/rosbridge_suite)
and built with `colcon` during the image build.

Two patches are applied to the cloned source before building:
1. `ament_cmake_mypy` and `ament_mypy` references are stripped from all
   `CMakeLists.txt` files — this package is not available and is only needed
   for type checking, not runtime.
2. `type_support.py` is patched to replace a missing
   `rosidl_pycommon.interface_base_classes` import (not present in Kilted)
   with compatible `object` stubs.

## Environment variables

| Variable         | Default | Description |
|------------------|---------|-------------|
| `ROSBRIDGE_PORT` | `9099`  | WebSocket server port |
| `ROS_DOMAIN_ID`  | `0`     | ROS2 DDS domain ID — must match ros2-inference |

## Build

```bash
cd ros2-fedora-base/src  && podman build -t ros2-fedora-base:latest .
cd ros2-rosbridge/src    && podman build -t ros2-rosbridge:latest .
```

> The build clones rosbridge_suite from GitHub — requires internet access.
> Build time is ~5 minutes due to colcon compilation.

## Run

```bash
podman run --rm --network host \
  -e ROSBRIDGE_PORT=9099 \
  ros2-rosbridge:latest
```

## Browser client protocol

The viewer connects using the native WebSocket API and speaks the
rosbridge v2 JSON protocol directly — no roslibjs library required.

Subscribe example:
```json
{ "op": "subscribe", "topic": "/detections", "type": "vision_msgs/msg/Detection2DArray" }
```

Incoming message format:
```json
{ "op": "publish", "topic": "/detections", "msg": { "detections": [...] } }
```

## Troubleshooting

If the browser can't connect, verify:
1. `ros2-inference` and `ros2-rosbridge` are both running with `--network host`
2. Both have the same `ROS_DOMAIN_ID`
3. Port 9099 is reachable from the browser (no firewall blocking it)
4. The inference node is actually publishing — check with:
   ```bash
   podman exec -it <rosbridge_container> /bin/bash
   source /usr/lib64/ros2-kilted/setup.bash && source /ros2_ws/install/setup.bash
   ros2 topic echo /detections
   ```
