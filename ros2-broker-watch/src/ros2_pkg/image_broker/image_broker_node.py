"""
ROS2 Topic Broker / Health Monitor

Central ROS2 node that:
  - Monitors any configured ROS2 topic regardless of message type
  - Detects topic type dynamically
  - Tracks message rate and last seen timestamp
  - Publishes consolidated diagnostics on /broker/topic_status

Environment variables
---------------------
BROKER_NODE_NAME        ROS2 node name (default: topic_broker)
TOPICS                  Comma-separated list of topics to monitor
                        e.g. /camera/front/image_raw,/detections
HEALTH_CHECK_INTERVAL   Seconds between health evaluations (default: 5)
STALE_TIMEOUT           Seconds without messages before marking STALE (default: 10)
QOS_DEPTH               QoS history depth (default: 5)
VERBOSE                 Log every received message: 1/true/yes
"""

import os
import time
from typing import Dict

import rclpy
from rclpy.node import Node
from rclpy.qos import QoSProfile, QoSReliabilityPolicy, QoSHistoryPolicy

from diagnostic_msgs.msg import DiagnosticArray, DiagnosticStatus, KeyValue

from rosidl_runtime_py.utilities import get_message


# ── Helpers ─────────────────────────────────────────────────────────────

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


# ── Per-topic statistics ─────────────────────────────────────────────────

class TopicStats:

    def __init__(self, topic: str):
        self.topic = topic
        self.frame_count = 0
        self.last_seen = 0.0
        self.fps_estimate = 0.0

        self._fps_check_time = time.monotonic()
        self._fps_check_frames = 0

    def record(self):
        now = time.monotonic()
        self.frame_count += 1
        self.last_seen = now

        elapsed = now - self._fps_check_time
        if elapsed >= 2.0:
            self.fps_estimate = (self.frame_count - self._fps_check_frames) / elapsed
            self._fps_check_time = now
            self._fps_check_frames = self.frame_count

    def is_stale(self, timeout: float):
        if self.last_seen == 0:
            return True
        return (time.monotonic() - self.last_seen) > timeout

    def last_seen_ago(self):
        if self.last_seen == 0:
            return "never"
        return f"{time.monotonic() - self.last_seen:.1f}s"


# ── Node ────────────────────────────────────────────────────────────────

class TopicBrokerNode(Node):

    def __init__(self):

        node_name = os.environ.get("BROKER_NODE_NAME", "topic_broker")
        super().__init__(node_name)

        # ── Configuration ─────────────────────────────────────────────

        topics_raw = os.environ.get("TOPICS", "")
        self.TOPICS = [t.strip() for t in topics_raw.split(",") if t.strip()]

        self.health_interval = _env_float("HEALTH_CHECK_INTERVAL", 5.0)
        self.stale_timeout = _env_float("STALE_TIMEOUT", 10.0)
        self.qos_depth = _env_int("QOS_DEPTH", 5)
        self.verbose = _env_bool("VERBOSE")

        # ── QoS ──────────────────────────────────────────────────────

        qos = QoSProfile(
            reliability=QoSReliabilityPolicy.BEST_EFFORT,
            history=QoSHistoryPolicy.KEEP_LAST,
            depth=self.qos_depth,
        )

        diag_qos = QoSProfile(
            reliability=QoSReliabilityPolicy.RELIABLE,
            history=QoSHistoryPolicy.KEEP_LAST,
            depth=10,
        )

        # ── Internal state ───────────────────────────────────────────

        self._stats: Dict[str, TopicStats] = {}
        self._subs = {}
        self._qos = qos

        # ── Diagnostics publisher ────────────────────────────────────

        self._diag_pub = self.create_publisher(
            DiagnosticArray,
            "/broker/topic_status",
            diag_qos
        )

        if not self.TOPICS:
            self.get_logger().warning("TOPICS empty — broker idle")

        else:
            for topic in self.TOPICS:
                self._stats[topic] = TopicStats(topic)

        # ── Timers ───────────────────────────────────────────────────

        self.create_timer(1.0, self._discover_topics)
        self.create_timer(self.health_interval, self._health_check)

        self.get_logger().info(
            f"Broker ready | monitoring={self.TOPICS} "
            f"| stale_timeout={self.stale_timeout}s"
        )

    # ── Topic discovery ─────────────────────────────────────────────

    def _discover_topics(self):

        known_topics = dict(self.get_topic_names_and_types())

        for topic in self.TOPICS:

            if topic in self._subs:
                continue

            if topic not in known_topics:
                continue

            msg_type = known_topics[topic][0]

            try:
                msg_class = get_message(msg_type)
            except Exception as e:
                self.get_logger().error(f"Cannot load type {msg_type}: {e}")
                continue

            self._subs[topic] = self.create_subscription(
                msg_class,
                topic,
                self._make_callback(topic),
                self._qos,
            )

            self.get_logger().info(
                f"Subscribed {topic} [{msg_type}]"
            )

    # ── Callbacks ───────────────────────────────────────────────────

    def _make_callback(self, topic: str):

        def _cb(msg):
            stats = self._stats[topic]
            stats.record()

            if self.verbose:
                self.get_logger().info(
                    f"[{topic}] message #{stats.frame_count}"
                )

        return _cb

    # ── Health evaluation ───────────────────────────────────────────

    def _health_check(self):

        array = DiagnosticArray()
        array.header.stamp = self.get_clock().now().to_msg()

        for topic, stats in self._stats.items():

            st = DiagnosticStatus()
            st.name = f"topic:{topic}"
            st.hardware_id = topic

            if stats.is_stale(self.stale_timeout):
                st.level = DiagnosticStatus.ERROR
                st.message = "STALE — no recent messages"
                level_label = "STALE"
            else:
                st.level = DiagnosticStatus.OK
                st.message = "OK"
                level_label = "OK"

            st.values = [
                KeyValue(key="topic", value=topic),
                KeyValue(key="total_messages", value=str(stats.frame_count)),
                KeyValue(key="fps_estimate", value=f"{stats.fps_estimate:.2f}"),
                KeyValue(key="last_seen_ago", value=stats.last_seen_ago()),
            ]

            array.status.append(st)

            # 👇 restore the log message
            self.get_logger().info(
                f"[health] {topic} -> {level_label} | "
                f"frames={stats.frame_count} "
                f"fps~{stats.fps_estimate:.1f} "
                f"last={stats.last_seen_ago()}"
            )

        if array.status:
            self._diag_pub.publish(array)


# ── Entry point ─────────────────────────────────────────────────────

def main(args=None):

    rclpy.init(args=args)

    node = TopicBrokerNode()

    try:
        rclpy.spin(node)
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()