"""
Inference Node
 
Pulls frames directly from an RTSP stream (bypassing ROS2 image transport
entirely for minimum latency), runs YOLOv11 detection, and publishes results
as vision_msgs/Detection2DArray on a configurable topic.
 
The browser viewer receives:
  - Video via WebRTC directly from MediaMTX (no ROS2 involvement)
  - Detections via rosbridge WebSocket from this node
 
This architecture eliminates the double video encode pipeline that caused
6+ seconds of latency in the previous design.
 
Environment variables
---------------------
RTSP_URL               RTSP stream to pull frames from (default: rtsp://127.0.0.1:8554/stream)
DETECTION_TOPIC        ROS2 topic to publish detections on (default: /detections)
YOLO_MODEL             Model weights file or name (default: yolo11n.pt)
                       Use yolo11n.pt (nano), yolo11s.pt (small), yolo11m.pt (medium),
                       yolo11l.pt (large), yolo11x.pt (extra-large)
CONFIDENCE_THRESHOLD   Minimum confidence to publish a detection (default: 0.4)
INFERENCE_WIDTH        Frame width fed to YOLO (default: 640)
INFERENCE_HEIGHT       Frame height fed to YOLO (default: 640)
TARGET_FPS             Max inference rate in frames per second (default: 10)
                       Frames between inference cycles are dropped — the node
                       always picks the LATEST available frame from the stream,
                       regardless of the stream FPS.
DETECTION_TTL          Seconds after which an empty detection array is published
                       to clear the overlay if no new detections arrive (default: 1.0)
DEVICE                 Inference device: auto, cpu, cuda, cuda:0, etc. (default: auto)
                       auto = use CUDA if available, fall back to CPU
VERBOSE                Log every detection: 1/true/yes (default: false)
ROS_DOMAIN_ID          ROS2 DDS domain ID (default: 0)
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
from vision_msgs.msg import Detection2DArray, Detection2D, BoundingBox2D, ObjectHypothesisWithPose
from std_msgs.msg import Header
 
 
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
 
def _resolve_device() -> str:
    """Auto-detect CUDA availability."""
    device = os.environ.get("DEVICE", "auto").lower()
    if device != "auto":
        return device
    try:
        import torch
        if torch.cuda.is_available():
            name = torch.cuda.get_device_name(0)
            return "cuda"
        return "cpu"
    except ImportError:
        return "cpu"
 
 
# ── Node ──────────────────────────────────────────────────────────────────────
 
class InferenceNode(Node):
 
    def __init__(self):
        super().__init__("inference_node")
 
        # ── Config ────────────────────────────────────────────────────────────
        self.rtsp_url:    str   = os.environ.get("RTSP_URL",   "rtsp://127.0.0.1:8554/stream")
        self.topic:       str   = os.environ.get("DETECTION_TOPIC", "/detections")
        self.model_name:  str   = os.environ.get("YOLO_MODEL", "yolo11n.pt")
        self.conf_thresh: float = _env_float("CONFIDENCE_THRESHOLD", 0.4)
        self.inf_width:   int   = _env_int("INFERENCE_WIDTH",  640)
        self.inf_height:  int   = _env_int("INFERENCE_HEIGHT", 640)
        self.target_fps:  float = _env_float("TARGET_FPS", 10.0)
        self.det_ttl:     float = _env_float("DETECTION_TTL", 1.0)
        self.device:      str   = _resolve_device()
        self.verbose:     bool  = _env_bool("VERBOSE")
 
        self._interval = 1.0 / max(self.target_fps, 0.1)
 
        # ── QoS ───────────────────────────────────────────────────────────────
        qos = QoSProfile(
            reliability=QoSReliabilityPolicy.BEST_EFFORT,
            history=QoSHistoryPolicy.KEEP_LAST,
            depth=1,
        )
        self._pub = self.create_publisher(Detection2DArray, self.topic, qos)
 
        # ── TTL timer — publishes empty detections to clear the overlay ───────
        self._last_publish_time: float = 0.0
        self.create_timer(0.2, self._ttl_check)
 
        self.get_logger().info(
            f"\n  RTSP URL     : {self.rtsp_url}"
            f"\n  Topic        : {self.topic}"
            f"\n  Model        : {self.model_name}"
            f"\n  Device       : {self.device}"
            f"\n  Confidence   : {self.conf_thresh}"
            f"\n  Infer size   : {self.inf_width}x{self.inf_height}"
            f"\n  Target FPS   : {self.target_fps}"
            f"\n  Detection TTL: {self.det_ttl}s"
        )
 
        # ── Load YOLO model ───────────────────────────────────────────────────
        self.get_logger().info("Loading YOLO model ...")
        from ultralytics import YOLO
 
        models_dir = os.environ.get("YOLO_MODELS_DIR", "/opt/yolo_models")
        candidate  = os.path.join(models_dir, self.model_name)
        model_path = candidate if os.path.exists(candidate) else self.model_name
 
        self.get_logger().info(f"Model path: {model_path}")
        self._model = YOLO(model_path)
        self._model.to(self.device)
        self.get_logger().info(f"Model loaded on {self.device}.")
 
        # ── Start capture thread ──────────────────────────────────────────────
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._inference_loop, daemon=True)
        self._thread.start()
 
    # ── TTL check — clears overlay if no detections for det_ttl seconds ──────
 
    def _ttl_check(self):
        if self._last_publish_time == 0.0:
            return
        if time.monotonic() - self._last_publish_time > self.det_ttl:
            self._publish_empty()
            self._last_publish_time = 0.0  # reset so we don't spam empties
 
    def _publish_empty(self):
        msg = Detection2DArray()
        msg.header.stamp = self.get_clock().now().to_msg()
        msg.header.frame_id = "camera"
        self._pub.publish(msg)
 
    # ── Inference loop ────────────────────────────────────────────────────────
 
    def _open_capture(self) -> Optional[cv2.VideoCapture]:
        self.get_logger().info(f"Opening RTSP stream: {self.rtsp_url}")
        os.environ["OPENCV_FFMPEG_LOGLEVEL"] = "8"
        cap = cv2.VideoCapture(self.rtsp_url, cv2.CAP_FFMPEG)
        if cap.isOpened():
            # Minimise internal buffer — we always want the freshest frame
            cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
            return cap
        return None
 
    def _grab_latest_frame(self, cap: cv2.VideoCapture):
        """
        Drain the capture buffer and return only the most recent frame.
        OpenCV buffers frames internally; if inference is slower than the
        stream FPS the buffer fills with stale frames. Calling grab()
        repeatedly without retrieve() discards old frames cheaply.
        """
        ret = False
        frame = None
        # Grab up to 10 frames without decoding, keep only the last
        for _ in range(10):
            ok = cap.grab()
            if not ok:
                break
            ret = ok
        if ret:
            ret, frame = cap.retrieve()
        return ret, frame
 
    def _inference_loop(self):
        while not self._stop.is_set():
            cap = self._open_capture()
            if cap is None:
                self.get_logger().warning("Could not open stream, retrying in 5s ...")
                time.sleep(5)
                continue
 
            self.get_logger().info("Stream opened. Starting inference ...")
 
            while not self._stop.is_set():
                t0 = time.monotonic()
 
                ret, frame = self._grab_latest_frame(cap)
                if not ret or frame is None:
                    self.get_logger().warning("Frame read failed — stream dropped.")
                    break
 
                src_h, src_w = frame.shape[:2]
                inf_frame = cv2.resize(frame, (self.inf_width, self.inf_height))
                self._run_inference(inf_frame, src_w, src_h)
 
                # Sleep for the remainder of the inference interval
                elapsed = time.monotonic() - t0
                sleep = self._interval - elapsed
                if sleep > 0:
                    time.sleep(sleep)
 
            cap.release()
            self.get_logger().warning("Stream lost, reconnecting in 3s ...")
            time.sleep(3)
 
    def _run_inference(self, frame: np.ndarray, orig_w: int, orig_h: int):
        try:
            results = self._model(frame, conf=self.conf_thresh, verbose=False)
        except Exception as exc:
            self.get_logger().error(f"Inference error: {exc}")
            return
 
        msg = Detection2DArray()
        msg.header.stamp = self.get_clock().now().to_msg()
        msg.header.frame_id = "camera"
 
        scale_x = orig_w / frame.shape[1]
        scale_y = orig_h / frame.shape[0]
 
        for result in results:
            boxes = result.boxes
            if boxes is None:
                continue
            for box in boxes:
                x1, y1, x2, y2 = box.xyxy[0].tolist()
                conf  = float(box.conf[0])
                cls   = int(box.cls[0])
                label = self._model.names.get(cls, str(cls))
 
                x1 *= scale_x; x2 *= scale_x
                y1 *= scale_y; y2 *= scale_y
 
                det = Detection2D()
                det.bbox = BoundingBox2D()
                det.bbox.center.position.x = (x1 + x2) / 2.0
                det.bbox.center.position.y = (y1 + y2) / 2.0
                det.bbox.size_x = x2 - x1
                det.bbox.size_y = y2 - y1
 
                hyp = ObjectHypothesisWithPose()
                hyp.hypothesis.class_id = label
                hyp.hypothesis.score    = conf
                det.results.append(hyp)
                msg.detections.append(det)
 
                if self.verbose:
                    self.get_logger().info(
                        f"  {label} {conf:.2f} [{x1:.0f},{y1:.0f},{x2:.0f},{y2:.0f}]"
                    )
 
        self._pub.publish(msg)
        self._last_publish_time = time.monotonic()
 
        if self.verbose and msg.detections:
            self.get_logger().info(f"Published {len(msg.detections)} detection(s)")
 
    def destroy_node(self):
        self._stop.set()
        super().destroy_node()
 
 
# ── Entry point ───────────────────────────────────────────────────────────────
 
def main(args=None):
    rclpy.init(args=args)
    node = InferenceNode()
    try:
        rclpy.spin(node)
    finally:
        node.destroy_node()
        rclpy.shutdown()
 
 
if __name__ == "__main__":
    main()
 