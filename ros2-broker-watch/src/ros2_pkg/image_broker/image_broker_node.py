"""
Image Broker Node

Central ROS2 node that:
  - Subscribes to all configured image topics published by ros2-rtsp-bridge containers
  - Monitors the liveness of each topic
  - Publishes a consolidated DiagnosticArray on /broker/camera_status
  - Optionally re-publishes images on normalised topics /broker/<camera>/image

Environment variables
---------------------
BROKER_NODE_NAME        ROS2 node name (default: image_broker)
TOPICS           Comma-separated list of topics to monitor
                        e.g. /camera/front/image_raw,/camera/rear/image_raw
HEALTH_CHECK_INTERVAL   Seconds between health evaluations (default: 5)
STALE_TIMEOUT           Seconds without frames before marking a topic STALE
                        (default: 10)
REPUBLISH               Re-publish images on /broker/<topic>/image: 1/true/yes
                        (default: false)
QOS_DEPTH               QoS history depth (default: 5)
VERBOSE                 Log every received frame: 1/true/yes (default: false)
ROS_DOMAIN_ID           ROS2 DDS domain ID (default: 0)
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
            return "never"
        return f"{time.monotonic() - self.last_seen:.1f}s"


# ── Node ──────────────────────────────────────────────────────────────────────

class ImageBrokerNode(Node):

    def __init__(self):
        node_name = os.environ.get("BROKER_NODE_NAME", "image_broker")
        super().__init__(node_name)

        # ── Config ────────────────────────────────────────────────────────────
        topics_raw = os.environ.get("TOPICS", "")
        self.TOPICS: list[str] = [
            t.strip() for t in topics_raw.split(",") if t.strip()
        ]
        self.health_interval: float = _env_float("HEALTH_CHECK_INTERVAL", 5.0)
        self.stale_timeout: float   = _env_float("STALE_TIMEOUT", 10.0)
        self.republish: bool        = _env_bool("REPUBLISH")
        self.qos_depth: int         = _env_int("QOS_DEPTH", 1)
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

        # ── Internal state ────────────────────────────────────────────────────
        self._stats: Dict[str, TopicStats] = {}
        self._subs = []
        self._repub_pubs: Dict[str, object] = {}

        # ── Diagnostics publisher ─────────────────────────────────────────────
        self._diag_pub = self.create_publisher(
            DiagnosticArray, "/broker/camera_status", pub_qos
        )

        # ── Subscriptions ─────────────────────────────────────────────────────
        if not self.TOPICS:
            self.get_logger().warning(
                "TOPICS is empty. Broker is running but not monitoring any topic."
            )
        else:
            for topic in self.TOPICS:
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
                    self.get_logger().info(f"Re-publishing {topic} -> {out}")

            self.get_logger().info(
                f"Monitoring {len(self.TOPICS)} topic(s): "
                + ", ".join(self.TOPICS)
            )

        # ── Health check timer ────────────────────────────────────────────────
        self.create_timer(self.health_interval, self._health_check)

        self.get_logger().info(
            f"ImageBrokerNode ready | "
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
                st.message = "STALE — no recent frames"
            else:
                st.level = DiagnosticStatus.OK
                st.message = "OK"

            st.values = [
                KeyValue(key="topic",          value=topic),
                KeyValue(key="total_frames",   value=str(stats.frame_count)),
                KeyValue(key="fps_estimate",   value=f"{stats.fps_estimate:.2f}"),
                KeyValue(key="last_seen_ago",  value=stats.last_seen_ago()),
            ]
            array.status.append(st)

            level_label = "OK" if st.level == DiagnosticStatus.OK else "STALE"
            self.get_logger().info(
                f"[health] {topic} -> {level_label} | "
                f"frames={stats.frame_count} "
                f"fps~{stats.fps_estimate:.1f} "
                f"last={stats.last_seen_ago()}"
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
