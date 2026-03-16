"""
RTSP Bridge Node

Captures frames from an RTSP stream and publishes them as sensor_msgs/Image
messages on a configurable ROS2 topic.

Environment variables
---------------------
RTSP_URL            RTSP stream URL (required)
                    e.g. rtsp://user:pass@192.168.1.10:554/stream1
ROS_TOPIC           Topic to publish images on (default: /camera/image_raw)
CAMERA_NAME         Logical camera name; used as frame_id and ROS2 node name
                    (default: rtsp_bridge)
TARGET_FPS          Publishing rate in frames per second (default: 10)
MAX_FRAMES          Max frames before shutting down; 0 = unlimited (default: 0)
IMAGE_WIDTH         Resize width in pixels; 0 = no resize (default: 0)
IMAGE_HEIGHT        Resize height in pixels; 0 = no resize (default: 0)
JPEG_QUALITY        JPEG re-encode quality 1-100; 0 = disabled (default: 0)
RECONNECT_DELAY     Seconds to wait before reconnecting (default: 5)
RECONNECT_RETRIES   Max reconnection attempts; 0 = unlimited (default: 0)
QOS_DEPTH           Publisher QoS history depth (default: 1)
VERBOSE             Log every published frame: 1/true/yes (default: false)
ROS_DOMAIN_ID       ROS2 DDS domain ID (default: 0)
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
        self.rtsp_url: str      = os.environ.get("RTSP_URL", "")
        self.topic: str         = os.environ.get("ROS_TOPIC", "/camera/image_raw")
        self.camera_name: str   = camera_name
        self.target_fps: float  = _env_float("TARGET_FPS", 10.0)
        self.max_frames: int    = _env_int("MAX_FRAMES", 0)
        self.img_width: int     = _env_int("IMAGE_WIDTH", 0)
        self.img_height: int    = _env_int("IMAGE_HEIGHT", 0)
        self.jpeg_quality: int  = _env_int("JPEG_QUALITY", 0)
        self.reconnect_delay: float  = _env_float("RECONNECT_DELAY", 5.0)
        self.reconnect_retries: int  = _env_int("RECONNECT_RETRIES", 0)
        self.qos_depth: int     = _env_int("QOS_DEPTH", 1)
        self.verbose: bool      = _env_bool("VERBOSE")

        if not self.rtsp_url:
            self.get_logger().fatal("RTSP_URL is not set. Shutting down.")
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
            f"\n  Max frames: {self.max_frames or 'unlimited'}"
            f"\n  Resize    : {self.img_width}x{self.img_height} (0 = disabled)"
            f"\n  JPEG enc. : {'quality=' + str(self.jpeg_quality) if self.jpeg_quality else 'disabled'}"
        )

        self._thread = threading.Thread(target=self._capture_loop, daemon=True)
        self._thread.start()

    # ── Capture loop ──────────────────────────────────────────────────────────

    def _open_capture(self) -> Optional[cv2.VideoCapture]:
        self.get_logger().info(f"Opening stream: {self.rtsp_url}")
        # Suppress FFmpeg H264 decoder warnings (decode_slice_header error,
        # frame num changes, etc.) caused by occasional dropped UDP packets.
        # These are non-fatal and the decoder recovers automatically.
        # LOG_LEVEL_FATAL (8) = only show fatal errors, not warnings.
        os.environ["OPENCV_FFMPEG_LOGLEVEL"] = "8"
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
                    f"Could not open stream (attempt {attempts}). "
                    f"Retrying in {self.reconnect_delay}s ..."
                )
                if self.reconnect_retries and attempts >= self.reconnect_retries:
                    self.get_logger().fatal("Max reconnection attempts reached. Stopping.")
                    rclpy.shutdown()
                    return
                time.sleep(self.reconnect_delay)
                continue

            attempts = 0
            self.get_logger().info("Stream opened successfully.")

            while not self._stop.is_set():
                t0 = time.monotonic()

                ret, frame = cap.read()
                if not ret:
                    self.get_logger().warning("Frame read failed — stream may have dropped.")
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
                    self.get_logger().info(f"Frame #{self._frame_count} published")

                if self.max_frames and self._frame_count >= self.max_frames:
                    self.get_logger().info(
                        f"MAX_FRAMES={self.max_frames} reached. Shutting down."
                    )
                    cap.release()
                    rclpy.shutdown()
                    return

                sleep = interval - (time.monotonic() - t0)
                if sleep > 0:
                    time.sleep(sleep)

            cap.release()
            self.get_logger().warning(f"Reconnecting in {self.reconnect_delay}s ...")
            time.sleep(self.reconnect_delay)

    def _publish(self, frame: np.ndarray):
        try:
            msg: Image = self._bridge.cv2_to_imgmsg(frame, encoding="bgr8")
            msg.header.stamp = self.get_clock().now().to_msg()
            msg.header.frame_id = self.camera_name
            self._pub.publish(msg)
        except Exception as exc:
            self.get_logger().error(f"Failed to publish frame: {exc}")

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
        print(f"[rtsp_bridge] Fatal error: {exc}")
    finally:
        rclpy.shutdown()


if __name__ == "__main__":
    main()