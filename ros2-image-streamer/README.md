# ros2-image-streamer

Servicio contenerizado que **suscribe a un topic ROS2 de imágenes** y las retransmite como:

- **RTSP** → `rtsp://<host>:8554/<RTSP_NAME>`
- **HLS** (web player) → `http://<host>:8888/<RTSP_NAME>`
- **WebRTC** (web player) → `http://<host>:8889/<RTSP_NAME>`

Internamente usa **MediaMTX** como servidor de streams y **FFmpeg** para codificar los frames recibidos vía pipe desde el nodo ROS2.

---

## Estructura

```
ros2-image-streamer/
├── README.md
└── src/
    ├── Containerfile
    ├── entrypoint.sh
    ├── mediamtx.yml
    └── ros2_pkg/
        ├── package.xml
        ├── setup.py
        ├── resource/
        │   └── image_streamer
        └── image_streamer/
            ├── __init__.py
            └── image_streamer_node.py
```

---

## Variables de entorno

| Variable       | Por defecto          | Descripción |
|----------------|----------------------|-------------|
| `ROS_TOPIC`    | `/camera/image_raw`  | Topic ROS2 del que consumir imágenes |
| `RTSP_HOST`    | `127.0.0.1`          | Host al que publicar en MediaMTX |
| `RTSP_PORT`    | `8554`               | Puerto RTSP de MediaMTX |
| `RTSP_NAME`    | `stream`             | Path del stream (`rtsp://host:8554/<RTSP_NAME>`) |
| `VIDEO_CODEC`  | `libx264`            | Codec FFmpeg de vídeo |
| `VIDEO_BITRATE`| `1000k`              | Bitrate del stream de salida |
| `VIDEO_PRESET` | `ultrafast`          | Preset x264 |
| `VIDEO_TUNE`   | `zerolatency`        | Tune x264 |
| `TARGET_FPS`   | `30`                 | FPS del stream de salida |
| `IMAGE_WIDTH`  | `0`                  | Redimensionado antes de publicar; `0` = sin cambio |
| `IMAGE_HEIGHT` | `0`                  | Redimensionado antes de publicar; `0` = sin cambio |
| `QOS_DEPTH`    | `1`                  | Profundidad del historial QoS del subscriber |
| `VERBOSE`      | `false`              | Log de cada frame procesado |
| `ROS_DOMAIN_ID`| `0`                  | ID de dominio DDS de ROS2 |

Para WebRTC desde un navegador en la misma red, pasa también:
```
-e MTX_WEBRTCADDITIONALHOSTS=<IP_LAN_del_host>
```

---

## Construir la imagen

```bash
cd ros2-image-streamer/src
podman build -t ros2-image-streamer:latest .
```

---

## Ejecutar

```bash
podman run --rm --network host \
  -e ROS_TOPIC="/camera/front/image_raw" \
  -e RTSP_NAME="front" \
  -e TARGET_FPS="15" \
  -e MTX_WEBRTCADDITIONALHOSTS="192.168.1.41" \
  ros2-image-streamer:latest
```

Una vez arriba, el stream está disponible en:

| Protocolo | URL |
|-----------|-----|
| RTSP      | `rtsp://localhost:8554/front` |
| HLS/web   | `http://localhost:8888/front` |
| WebRTC    | `http://localhost:8889/front` |

---

## Notas

- El nodo detecta las dimensiones del frame en el **primer mensaje** recibido. Si el topic no publica nada, FFmpeg no arranca.
- Si las dimensiones del topic cambian en mitad del stream, FFmpeg se reinicia automáticamente.
- El codec `libx264` con los flags de compatibilidad WebRTC permite reproducir el stream directamente en el navegador sin plugins.
- Usa `network_mode: host` para que el DDS discovery de ROS2 funcione correctamente.
