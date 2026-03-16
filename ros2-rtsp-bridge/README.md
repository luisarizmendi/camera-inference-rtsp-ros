# rtsp-bridge

Servicio contenerizado que actúa como **puente entre un stream RTSP y un topic de ROS2**.
Captura frames de una cámara IP/RTSP y los publica como `sensor_msgs/Image`.

Está diseñado para ejecutarse **uno por cámara**, en paralelo con otros contenedores del mismo tipo.

---

## Estructura

```
rtsp-bridge/
├── README.md
└── src/
    ├── Containerfile
    ├── entrypoint.sh
    └── ros2_pkg/
        ├── package.xml
        ├── setup.py
        ├── resource/
        │   └── rtsp_bridge
        └── rtsp_bridge/
            ├── __init__.py
            └── rtsp_bridge_node.py
```

---

## Variables de entorno

| Variable            | Obligatoria | Por defecto         | Descripción |
|---------------------|:-----------:|---------------------|-------------|
| `RTSP_URL`          | ✅           | —                   | URL completa del stream RTSP |
| `ROS_TOPIC`         |             | `/camera/image_raw` | Topic ROS2 donde se publican los frames |
| `CAMERA_NAME`       |             | `rtsp_bridge`       | Nombre lógico; se usa como `frame_id` y nombre de nodo |
| `TARGET_FPS`        |             | `10`                | Frecuencia de publicación en fps |
| `MAX_FRAMES`        |             | `0`                 | Frames máximos antes de parar; `0` = sin límite |
| `IMAGE_WIDTH`       |             | `0`                 | Ancho de redimensionado en píxeles; `0` = sin cambio |
| `IMAGE_HEIGHT`      |             | `0`                 | Alto de redimensionado en píxeles; `0` = sin cambio |
| `JPEG_QUALITY`      |             | `0`                 | Calidad JPEG al recodificar (1-100); `0` = sin recodificar |
| `RECONNECT_DELAY`   |             | `5`                 | Segundos de espera entre reconexiones |
| `RECONNECT_RETRIES` |             | `0`                 | Intentos máximos de reconexión; `0` = infinito |
| `QOS_DEPTH`         |             | `1`                 | Profundidad del historial QoS del publisher |
| `VERBOSE`           |             | `false`             | Log de cada frame: `1`/`true`/`yes` |
| `ROS_DOMAIN_ID`     |             | `0`                 | ID de dominio DDS (variable estándar de ROS2) |

---

## Construir la imagen

```bash
cd rtsp-bridge/src
podman build -t rtsp-bridge:latest .
```

---

## Ejecutar una cámara

```bash
podman run --rm --network host \
  -e RTSP_URL="rtsp://admin:1234@192.168.1.100:554/stream1" \
  -e ROS_TOPIC="/camera/front/image_raw" \
  -e CAMERA_NAME="camera_front" \
  -e TARGET_FPS="15" \
  -e IMAGE_WIDTH="1280" \
  -e IMAGE_HEIGHT="720" \
  -e JPEG_QUALITY="80" \
  rtsp-bridge:latest
```

## Múltiples cámaras con Docker Compose

Añade un servicio por cámara en el `docker-compose.yml` del proyecto raíz, todos usando la misma imagen `rtsp-bridge:latest` y diferente configuración por variables de entorno.

> **Nota**: se usa `network_mode: host` para que el descubrimiento DDS de ROS2 funcione correctamente.
