"""
Image Broker Node

Nodo central ROS2 que:
  - Se suscribe a los topics de imagen publicados por los contenedores rtsp-bridge
  - Monitoriza la liveness de cada topic
  - Publica un DiagnosticArray con el estado de cada cámara en /broker/camera_status
  - Opcionalmente re-publica las imágenes en topics normalizados /broker/<camera>/image

Variables de entorno
--------------------
BROKER_NODE_NAME        Nombre del nodo ROS2 (por defecto: image_broker)
CAMERA_TOPICS           Lista de topics a monitorizar, separados por coma
                        Ejemplo: /camera/front/image_raw,/camera/rear/image_raw
HEALTH_CHECK_INTERVAL   Segundos entre evaluaciones de estado (por defecto: 5)
STALE_TIMEOUT           Segundos sin frames para marcar un topic como STALE
                        (por defecto: 10)
REPUBLISH               Re-publicar imágenes en /broker/<topic>/image: 1/true/yes
                        (por defecto: false)
QOS_DEPTH               Profundidad del historial QoS (por defecto: 5)
VERBOSE                 Log por cada frame recibido: 1/true/yes (por defecto: false)
ROS_DOMAIN_ID           ID de dominio DDS de ROS2 (por defecto: 0)
"""

import os
import time
from typing import Dict

import rclpy
from rclpy.node import Node
from rclpy.qos import QoSProfile, QoSReliabilityPolicy, QoSHistoryPolicy
from sensor_msgs.msg import Image
from diagnostic_msgs.msg import DiagnosticArray, DiagnosticStatus, KeyValue


# ── Helpers ───────────────────────────────────────────────────────────────────

def _env_float(key: str, default: float) -> float:
    try:
        return float(os.environ.get(key, default))
    except ValueError:
        return default


def _env_int(key: str, default: int) -> int:
    try:
        return int(os.environ.get(key, default))
    except ValueError:
        return default


def _env_bool(key: str, default: bool = False) -> bool:
    val = os.environ.get(key, "").lower()
    return val in ("1", "true", "yes") if val else default


# ── Per-topic statistics ──────────────────────────────────────────────────────

class TopicStats:
    def __init__(self, topic: str):
        self.topic = topic
        self.frame_count: int = 0
        self.last_seen: float = 0.0
        self.fps_estimate: float = 0.0
        self._fps_check_time: float = time.monotonic()
        self._fps_check_frames: int = 0

    def record(self):
        now = time.monotonic()
        self.frame_count += 1
        self.last_seen = now

        elapsed = now - self._fps_check_time
        if elapsed >= 2.0:
            self.fps_estimate = (self.frame_count - self._fps_check_frames) / elapsed
            self._fps_check_time = now
            self._fps_check_frames = self.frame_count

    def is_stale(self, timeout: float) -> bool:
        if self.last_seen == 0.0:
            return True
        return (time.monotonic() - self.last_seen) > timeout

    def last_seen_ago(self) -> str:
        if self.last_seen == 0.0:
            return "nunca"
        return f"{time.monotonic() - self.last_seen:.1f}s"


# ── Node ──────────────────────────────────────────────────────────────────────

class ImageBrokerNode(Node):

    def __init__(self):
        node_name = os.environ.get("BROKER_NODE_NAME", "image_broker")
        super().__init__(node_name)

        # ── Config ────────────────────────────────────────────────────────────
        topics_raw = os.environ.get("CAMERA_TOPICS", "")
        self.camera_topics: list[str] = [
            t.strip() for t in topics_raw.split(",") if t.strip()
        ]
        self.health_interval: float = _env_float("HEALTH_CHECK_INTERVAL", 5.0)
        self.stale_timeout: float   = _env_float("STALE_TIMEOUT", 10.0)
        self.republish: bool        = _env_bool("REPUBLISH")
        self.qos_depth: int         = _env_int("QOS_DEPTH", 5)
        self.verbose: bool          = _env_bool("VERBOSE")

        # ── QoS ───────────────────────────────────────────────────────────────
        sub_qos = QoSProfile(
            reliability=QoSReliabilityPolicy.BEST_EFFORT,
            history=QoSHistoryPolicy.KEEP_LAST,
            depth=self.qos_depth,
        )
        pub_qos = QoSProfile(
            reliability=QoSReliabilityPolicy.RELIABLE,
            history=QoSHistoryPolicy.KEEP_LAST,
            depth=self.qos_depth,
        )

        # ── Estado interno ────────────────────────────────────────────────────
        self._stats: Dict[str, TopicStats] = {}
        self._subs = []
        self._repub_pubs: Dict[str, object] = {}

        # ── Publisher de diagnósticos ─────────────────────────────────────────
        self._diag_pub = self.create_publisher(
            DiagnosticArray, "/broker/camera_status", pub_qos
        )

        # ── Suscripciones ─────────────────────────────────────────────────────
        if not self.camera_topics:
            self.get_logger().warning(
                "CAMERA_TOPICS está vacío. El broker arranca pero no monitoriza ningún topic."
            )
        else:
            for topic in self.camera_topics:
                self._stats[topic] = TopicStats(topic)
                self._subs.append(
                    self.create_subscription(
                        Image,
                        topic,
                        self._make_callback(topic),
                        sub_qos,
                    )
                )
                if self.republish:
                    out = "/broker/" + topic.replace("/", "_").strip("_") + "/image"
                    self._repub_pubs[topic] = self.create_publisher(Image, out, pub_qos)
                    self.get_logger().info(f"Re-publicando {topic} → {out}")

            self.get_logger().info(
                f"Monitorizando {len(self.camera_topics)} topic(s): "
                + ", ".join(self.camera_topics)
            )

        # ── Timer de health check ─────────────────────────────────────────────
        self.create_timer(self.health_interval, self._health_check)

        self.get_logger().info(
            f"ImageBrokerNode listo | "
            f"health_interval={self.health_interval}s | "
            f"stale_timeout={self.stale_timeout}s | "
            f"republish={self.republish}"
        )

    # ── Callbacks ─────────────────────────────────────────────────────────────

    def _make_callback(self, topic: str):
        def _cb(msg: Image):
            self._stats[topic].record()
            if self.verbose:
                self.get_logger().info(
                    f"[{topic}] frame #{self._stats[topic].frame_count}"
                )
            if self.republish and topic in self._repub_pubs:
                self._repub_pubs[topic].publish(msg)
        return _cb

    def _health_check(self):
        array = DiagnosticArray()
        array.header.stamp = self.get_clock().now().to_msg()

        for topic, stats in self._stats.items():
            st = DiagnosticStatus()
            st.name = f"camera_topic:{topic}"
            st.hardware_id = topic

            if stats.is_stale(self.stale_timeout):
                st.level = DiagnosticStatus.ERROR
                st.message = "STALE — sin frames recientes"
            else:
                st.level = DiagnosticStatus.OK
                st.message = "OK"

            st.values = [
                KeyValue(key="topic",           value=topic),
                KeyValue(key="total_frames",    value=str(stats.frame_count)),
                KeyValue(key="fps_estimate",    value=f"{stats.fps_estimate:.2f}"),
                KeyValue(key="last_seen_ago",   value=stats.last_seen_ago()),
            ]
            array.status.append(st)

            level_label = "OK" if st.level == DiagnosticStatus.OK else "STALE"
            self.get_logger().info(
                f"[health] {topic} → {level_label} | "
                f"frames={stats.frame_count} "
                f"fps≈{stats.fps_estimate:.1f} "
                f"último={stats.last_seen_ago()}"
            )

        if array.status:
            self._diag_pub.publish(array)


# ── Entry point ───────────────────────────────────────────────────────────────

def main(args=None):
    rclpy.init(args=args)
    node = ImageBrokerNode()
    try:
        rclpy.spin(node)
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
