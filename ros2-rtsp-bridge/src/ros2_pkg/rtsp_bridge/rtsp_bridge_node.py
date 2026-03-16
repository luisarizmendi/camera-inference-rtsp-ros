"""
RTSP Bridge Node

Captura frames de un stream RTSP y los publica como sensor_msgs/Image
en un topic de ROS2 configurable.

Variables de entorno
--------------------
RTSP_URL            URL del stream RTSP (obligatoria)
                    Ejemplo: rtsp://user:pass@192.168.1.10:554/stream1
ROS_TOPIC           Topic donde se publican las imágenes
                    (por defecto: /camera/image_raw)
CAMERA_NAME         Nombre lógico de la cámara; se usa como frame_id y
                    nombre del nodo ROS2 (por defecto: rtsp_bridge)
TARGET_FPS          Frecuencia de publicación en fps (por defecto: 10)
MAX_FRAMES          Frames máximos antes de parar; 0 = sin límite
                    (por defecto: 0)
IMAGE_WIDTH         Ancho de redimensionado en píxeles; 0 = sin cambio
                    (por defecto: 0)
IMAGE_HEIGHT        Alto de redimensionado en píxeles; 0 = sin cambio
                    (por defecto: 0)
JPEG_QUALITY        Calidad JPEG para recodificar antes de publicar (1-100);
                    0 = sin recodificar (por defecto: 0)
RECONNECT_DELAY     Segundos de espera entre reconexiones (por defecto: 5)
RECONNECT_RETRIES   Intentos máximos de reconexión; 0 = infinito
                    (por defecto: 0)
QOS_DEPTH           Profundidad del historial QoS del publisher
                    (por defecto: 1)
VERBOSE             Log de cada frame publicado: 1/true/yes
                    (por defecto: false)
ROS_DOMAIN_ID       ID de dominio DDS de ROS2 (variable estándar de ROS2;
                    por defecto: 0)
"""

import os
import time
import threading
from typing import Optional

import cv2
import numpy as np
import rclpy
from rclpy.node import Node
from rclpy.qos import QoSProfile, QoSReliabilityPolicy, QoSHistoryPolicy
from sensor_msgs.msg import Image
from std_msgs.msg import Header
from cv_bridge import CvBridge


# ── Helpers ───────────────────────────────────────────────────────────────────

def _env_int(key: str, default: int) -> int:
    try:
        return int(os.environ.get(key, default))
    except ValueError:
        return default


def _env_float(key: str, default: float) -> float:
    try:
        return float(os.environ.get(key, default))
    except ValueError:
        return default


def _env_bool(key: str, default: bool = False) -> bool:
    val = os.environ.get(key, "").lower()
    return val in ("1", "true", "yes") if val else default


# ── Node ──────────────────────────────────────────────────────────────────────

class RtspBridgeNode(Node):

    def __init__(self):
        camera_name = os.environ.get("CAMERA_NAME", "rtsp_bridge")
        node_name = camera_name.replace("-", "_").replace(" ", "_")
        super().__init__(node_name)

        # ── Config ────────────────────────────────────────────────────────────
        self.rtsp_url: str       = os.environ.get("RTSP_URL", "")
        self.topic: str          = os.environ.get("ROS_TOPIC", "/camera/image_raw")
        self.camera_name: str    = camera_name
        self.target_fps: float   = _env_float("TARGET_FPS", 10.0)
        self.max_frames: int     = _env_int("MAX_FRAMES", 0)
        self.img_width: int      = _env_int("IMAGE_WIDTH", 0)
        self.img_height: int     = _env_int("IMAGE_HEIGHT", 0)
        self.jpeg_quality: int   = _env_int("JPEG_QUALITY", 0)
        self.reconnect_delay: float  = _env_float("RECONNECT_DELAY", 5.0)
        self.reconnect_retries: int  = _env_int("RECONNECT_RETRIES", 0)
        self.qos_depth: int      = _env_int("QOS_DEPTH", 1)
        self.verbose: bool       = _env_bool("VERBOSE")

        if not self.rtsp_url:
            self.get_logger().fatal("RTSP_URL no está definido. Saliendo.")
            raise RuntimeError("RTSP_URL not set")

        # ── QoS ───────────────────────────────────────────────────────────────
        qos = QoSProfile(
            reliability=QoSReliabilityPolicy.BEST_EFFORT,
            history=QoSHistoryPolicy.KEEP_LAST,
            depth=self.qos_depth,
        )

        self._pub = self.create_publisher(Image, self.topic, qos)
        self._bridge = CvBridge()
        self._frame_count = 0
        self._stop = threading.Event()

        self.get_logger().info(
            f"\n  RTSP URL  : {self.rtsp_url}"
            f"\n  Topic     : {self.topic}"
            f"\n  FPS       : {self.target_fps}"
            f"\n  Max frames: {self.max_frames or 'sin límite'}"
            f"\n  Resize    : {self.img_width}x{self.img_height} (0 = sin cambio)"
            f"\n  JPEG enc. : {'calidad=' + str(self.jpeg_quality) if self.jpeg_quality else 'desactivado'}"
        )

        self._thread = threading.Thread(target=self._capture_loop, daemon=True)
        self._thread.start()

    # ── Capture loop ──────────────────────────────────────────────────────────

    def _open_capture(self) -> Optional[cv2.VideoCapture]:
        self.get_logger().info(f"Abriendo stream: {self.rtsp_url}")
        cap = cv2.VideoCapture(self.rtsp_url, cv2.CAP_FFMPEG)
        return cap if cap.isOpened() else None

    def _capture_loop(self):
        interval = 1.0 / max(self.target_fps, 0.1)
        attempts = 0

        while not self._stop.is_set():
            cap = self._open_capture()

            if cap is None:
                attempts += 1
                self.get_logger().warning(
                    f"No se pudo abrir el stream (intento {attempts}). "
                    f"Reintentando en {self.reconnect_delay}s …"
                )
                if self.reconnect_retries and attempts >= self.reconnect_retries:
                    self.get_logger().fatal("Máximo de reintentos alcanzado. Deteniendo.")
                    rclpy.shutdown()
                    return
                time.sleep(self.reconnect_delay)
                continue

            attempts = 0
            self.get_logger().info("Stream abierto correctamente.")

            while not self._stop.is_set():
                t0 = time.monotonic()

                ret, frame = cap.read()
                if not ret:
                    self.get_logger().warning("Lectura de frame fallida — stream caído.")
                    break

                if self.img_width > 0 and self.img_height > 0:
                    frame = cv2.resize(frame, (self.img_width, self.img_height))

                if self.jpeg_quality > 0:
                    _, buf = cv2.imencode(
                        ".jpg", frame,
                        [cv2.IMWRITE_JPEG_QUALITY, self.jpeg_quality]
                    )
                    frame = cv2.imdecode(buf, cv2.IMREAD_COLOR)

                self._publish(frame)
                self._frame_count += 1

                if self.verbose:
                    self.get_logger().info(f"Frame #{self._frame_count} publicado")

                if self.max_frames and self._frame_count >= self.max_frames:
                    self.get_logger().info(
                        f"MAX_FRAMES={self.max_frames} alcanzado. Deteniendo."
                    )
                    cap.release()
                    rclpy.shutdown()
                    return

                sleep = interval - (time.monotonic() - t0)
                if sleep > 0:
                    time.sleep(sleep)

            cap.release()
            self.get_logger().warning(f"Reconectando en {self.reconnect_delay}s …")
            time.sleep(self.reconnect_delay)

    def _publish(self, frame: np.ndarray):
        try:
            msg: Image = self._bridge.cv2_to_imgmsg(frame, encoding="bgr8")
            msg.header.stamp = self.get_clock().now().to_msg()
            msg.header.frame_id = self.camera_name
            self._pub.publish(msg)
        except Exception as exc:
            self.get_logger().error(f"Error publicando frame: {exc}")

    def destroy_node(self):
        self._stop.set()
        super().destroy_node()


# ── Entry point ───────────────────────────────────────────────────────────────

def main(args=None):
    rclpy.init(args=args)
    try:
        node = RtspBridgeNode()
        rclpy.spin(node)
    except RuntimeError as exc:
        print(f"[rtsp_bridge] Error fatal: {exc}")
    finally:
        rclpy.shutdown()


if __name__ == "__main__":
    main()
