"""
Image Streamer Node

Se suscribe a un topic ROS2 de imágenes (sensor_msgs/Image) y las reenvía
a MediaMTX via FFmpeg (pipe rawvideo → RTSP), haciéndolas disponibles como:
  - RTSP  → rtsp://<host>:8554/<RTSP_NAME>
  - HLS   → http://<host>:8888/<RTSP_NAME>
  - WebRTC → http://<host>:8889/<RTSP_NAME>

El nodo escribe los frames crudos en un pipe hacia un subproceso ffmpeg,
siguiendo el mismo patrón que el camera-gateway-rtsp de referencia.

Variables de entorno
--------------------
ROS_TOPIC        Topic ROS2 del que consumir imágenes
                 (por defecto: /camera/image_raw)
RTSP_HOST        Host al que publicar en MediaMTX (por defecto: 127.0.0.1)
RTSP_PORT        Puerto RTSP de MediaMTX (por defecto: 8554)
RTSP_NAME        Nombre del path RTSP (por defecto: stream)
VIDEO_CODEC      Codec FFmpeg de vídeo (por defecto: libx264)
VIDEO_BITRATE    Bitrate de vídeo (por defecto: 1000k)
VIDEO_PRESET     Preset x264 (por defecto: ultrafast)
VIDEO_TUNE       Tune x264 (por defecto: zerolatency)
TARGET_FPS       FPS del stream de salida (por defecto: 30)
IMAGE_WIDTH      Ancho de redimensionado antes de publicar; 0 = sin cambio
                 (por defecto: 0)
IMAGE_HEIGHT     Alto de redimensionado antes de publicar; 0 = sin cambio
                 (por defecto: 0)
QOS_DEPTH        Profundidad del historial QoS del subscriber (por defecto: 1)
VERBOSE          Log de cada frame procesado: 1/true/yes (por defecto: false)
ROS_DOMAIN_ID    ID de dominio DDS de ROS2 (por defecto: 0)
"""

import os
import subprocess
import threading
import time
from typing import Optional

import cv2
import numpy as np
import rclpy
from rclpy.node import Node
from rclpy.qos import QoSProfile, QoSReliabilityPolicy, QoSHistoryPolicy
from sensor_msgs.msg import Image
from cv_bridge import CvBridge


# ── Helpers ───────────────────────────────────────────────────────────────────

def _env_int(key: str, default: int) -> int:
    try:
        return int(os.environ.get(key, default))
    except ValueError:
        return default


def _env_bool(key: str, default: bool = False) -> bool:
    val = os.environ.get(key, "").lower()
    return val in ("1", "true", "yes") if val else default


def _h264_compat_flags() -> list[str]:
    """Flags necesarios para compatibilidad WebRTC en navegadores."""
    return [
        "-pix_fmt",   "yuv420p",
        "-profile:v", "baseline",
        "-level:v",   "4.2",
        "-bf",        "0",       # sin B-frames (requerimiento WebRTC)
    ]


# ── Node ──────────────────────────────────────────────────────────────────────

class ImageStreamerNode(Node):

    def __init__(self):
        super().__init__("image_streamer")

        # ── Config ────────────────────────────────────────────────────────────
        self.ros_topic: str    = os.environ.get("ROS_TOPIC", "/camera/image_raw")
        self.rtsp_host: str    = os.environ.get("RTSP_HOST", "127.0.0.1")
        self.rtsp_port: str    = os.environ.get("RTSP_PORT", "8554")
        self.rtsp_name: str    = os.environ.get("RTSP_NAME", "stream")
        self.codec: str        = os.environ.get("VIDEO_CODEC", "libx264")
        self.bitrate: str      = os.environ.get("VIDEO_BITRATE", "1000k")
        self.preset: str       = os.environ.get("VIDEO_PRESET", "ultrafast")
        self.tune: str         = os.environ.get("VIDEO_TUNE", "zerolatency")
        self.target_fps: int   = _env_int("TARGET_FPS", 30)
        self.img_width: int    = _env_int("IMAGE_WIDTH", 0)
        self.img_height: int   = _env_int("IMAGE_HEIGHT", 0)
        self.qos_depth: int    = _env_int("QOS_DEPTH", 1)
        self.verbose: bool     = _env_bool("VERBOSE")

        self.rtsp_url = f"rtsp://{self.rtsp_host}:{self.rtsp_port}/{self.rtsp_name}"

        # ── Estado interno ────────────────────────────────────────────────────
        self._bridge = CvBridge()
        self._ffmpeg: Optional[subprocess.Popen] = None
        self._lock = threading.Lock()
        self._frame_count = 0

        # Dimensiones del stream (se detectan en el primer frame)
        self._width: Optional[int] = None
        self._height: Optional[int] = None

        # ── QoS ───────────────────────────────────────────────────────────────
        qos = QoSProfile(
            reliability=QoSReliabilityPolicy.BEST_EFFORT,
            history=QoSHistoryPolicy.KEEP_LAST,
            depth=self.qos_depth,
        )

        self._sub = self.create_subscription(
            Image,
            self.ros_topic,
            self._on_image,
            qos,
        )

        self.get_logger().info(
            f"\n  Topic ROS2 : {self.ros_topic}"
            f"\n  RTSP URL   : {self.rtsp_url}"
            f"\n  HLS        : http://{self.rtsp_host}:8888/{self.rtsp_name}"
            f"\n  WebRTC     : http://{self.rtsp_host}:8889/{self.rtsp_name}"
            f"\n  Codec      : {self.codec}  bitrate={self.bitrate}"
            f"\n  Target FPS : {self.target_fps}"
            f"\n  Resize     : {self.img_width}x{self.img_height} (0 = sin cambio)"
        )

    # ── Callback ROS2 ─────────────────────────────────────────────────────────

    def _on_image(self, msg: Image):
        try:
            frame: np.ndarray = self._bridge.imgmsg_to_cv2(msg, desired_encoding="bgr8")
        except Exception as exc:
            self.get_logger().error(f"Error convirtiendo imagen: {exc}")
            return

        if self.img_width > 0 and self.img_height > 0:
            frame = cv2.resize(frame, (self.img_width, self.img_height))

        h, w = frame.shape[:2]

        with self._lock:
            # Si las dimensiones han cambiado (o primer frame), reiniciar ffmpeg
            if self._ffmpeg is None or self._width != w or self._height != h:
                self._restart_ffmpeg(w, h)

            if self._ffmpeg is None or self._ffmpeg.poll() is not None:
                self.get_logger().warning("FFmpeg no está corriendo, descartando frame.")
                return

            try:
                self._ffmpeg.stdin.write(frame.tobytes())
            except BrokenPipeError:
                self.get_logger().warning("Pipe roto con FFmpeg, se reiniciará en el próximo frame.")
                self._ffmpeg = None
                return

        self._frame_count += 1
        if self.verbose:
            self.get_logger().info(f"Frame #{self._frame_count} enviado a FFmpeg")

    # ── FFmpeg management ─────────────────────────────────────────────────────

    def _build_ffmpeg_cmd(self, width: int, height: int) -> list[str]:
        cmd = [
            "ffmpeg",
            "-loglevel", "warning",
            # Entrada: rawvideo desde stdin
            "-f",          "rawvideo",
            "-pixel_format", "bgr24",
            "-video_size",  f"{width}x{height}",
            "-framerate",   str(self.target_fps),
            "-i",          "pipe:0",
            # Codec de salida
            "-c:v", self.codec,
        ]

        if self.codec == "libx264":
            cmd += _h264_compat_flags()
            cmd += ["-preset", self.preset, "-tune", self.tune]

        cmd += [
            "-b:v", self.bitrate,
            "-an",              # sin audio (el topic ROS2 es sólo vídeo)
            "-f",  "rtsp",
            self.rtsp_url,
        ]
        return cmd

    def _restart_ffmpeg(self, width: int, height: int):
        """Cierra el proceso ffmpeg existente y arranca uno nuevo."""
        if self._ffmpeg is not None:
            try:
                self._ffmpeg.stdin.close()
                self._ffmpeg.wait(timeout=3)
            except Exception:
                self._ffmpeg.kill()

        self._width = width
        self._height = height

        cmd = self._build_ffmpeg_cmd(width, height)
        self.get_logger().info(
            f"Arrancando FFmpeg {width}x{height} → {self.rtsp_url}\n"
            f"  cmd: {' '.join(cmd)}"
        )

        self._ffmpeg = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
        )

        # Hilo para leer stderr de ffmpeg y enviarlo al logger
        threading.Thread(
            target=self._log_ffmpeg_stderr,
            args=(self._ffmpeg,),
            daemon=True,
        ).start()

    def _log_ffmpeg_stderr(self, proc: subprocess.Popen):
        for line in proc.stderr:
            decoded = line.decode(errors="replace").rstrip()
            if decoded:
                self.get_logger().warning(f"[ffmpeg] {decoded}")

    # ── Cleanup ───────────────────────────────────────────────────────────────

    def destroy_node(self):
        with self._lock:
            if self._ffmpeg is not None:
                try:
                    self._ffmpeg.stdin.close()
                    self._ffmpeg.wait(timeout=3)
                except Exception:
                    self._ffmpeg.kill()
        super().destroy_node()


# ── Entry point ───────────────────────────────────────────────────────────────

def main(args=None):
    rclpy.init(args=args)
    node = ImageStreamerNode()
    try:
        rclpy.spin(node)
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
