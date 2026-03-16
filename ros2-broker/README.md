# ros2-broker

Servicio contenerizado que actúa como **nodo central del grafo ROS2** para el sistema de streaming de cámaras.

Se levanta una única instancia de este servicio. Los contenedores `rtsp-bridge` (uno por cámara) publican en sus topics, y este broker los monitoriza y expone diagnósticos.

---

## Estructura

```
ros2-broker/
├── README.md
└── src/
    ├── Containerfile
    └── ros2_pkg/
        ├── package.xml
        ├── setup.py
        ├── resource/
        │   └── image_broker
        └── image_broker/
            ├── __init__.py
            └── image_broker_node.py
```

---

## Variables de entorno

| Variable                | Obligatoria | Por defecto      | Descripción |
|-------------------------|:-----------:|------------------|-------------|
| `BROKER_NODE_NAME`      |             | `image_broker`   | Nombre del nodo ROS2 |
| `CAMERA_TOPICS`         |             | _(vacío)_        | Topics a monitorizar, separados por coma |
| `HEALTH_CHECK_INTERVAL` |             | `5`              | Segundos entre evaluaciones de estado |
| `STALE_TIMEOUT`         |             | `10`             | Segundos sin frames para marcar como STALE |
| `REPUBLISH`             |             | `false`          | Re-publica cada topic en `/broker/<topic>/image` |
| `QOS_DEPTH`             |             | `5`              | Profundidad del historial QoS |
| `VERBOSE`               |             | `false`          | Log por cada frame recibido |
| `ROS_DOMAIN_ID`         |             | `0`              | ID de dominio DDS de ROS2 |

---

## Construir la imagen

```bash
cd ros2-broker/src
podman build -t ros2-broker:latest .
```

---

## Ejecutar

```bash
podman run --rm --network host \
  -e CAMERA_TOPICS="/camera/front/image_raw,/camera/rear/image_raw" \
  -e STALE_TIMEOUT="10" \
  -e HEALTH_CHECK_INTERVAL="5" \
  ros2-broker:latest
```

---

## Topic de diagnósticos

El broker publica en `/broker/camera_status` mensajes `diagnostic_msgs/DiagnosticArray`.

Cada entrada contiene:

| Campo           | Descripción |
|-----------------|-------------|
| `level`         | `0` = OK · `2` = STALE |
| `total_frames`  | Frames recibidos desde el inicio |
| `fps_estimate`  | FPS estimados en los últimos 2 segundos |
| `last_seen_ago` | Tiempo desde el último frame |

Monitorización en tiempo real:

```bash
ros2 topic echo /broker/camera_status
```

---

## Notas

- El broker es **independiente** de los `rtsp-bridge`: estos publican sus topics aunque el broker no esté activo.
- Usa `network_mode: host` para que el DDS discovery de ROS2 funcione entre contenedores.
- El `ROS_DOMAIN_ID` debe coincidir en todos los contenedores del sistema.
