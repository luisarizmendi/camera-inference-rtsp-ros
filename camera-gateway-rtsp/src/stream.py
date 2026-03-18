#!/usr/bin/env python3
"""
RTSP streamer: tries USB webcams first, falls back to looping video files.
All configuration via environment variables.

Codec requirements for WebRTC browser compatibility:
  - Video: libx264 with yuv420p, baseline profile, no B-frames
  - Audio: libopus (AAC not supported by WebRTC)
"""

import os
import subprocess
import glob
import sys
import time
import logging

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)

# ── Environment configuration ────────────────────────────────────────────────
RTSP_HOST       = os.environ.get("RTSP_HOST",       "127.0.0.1")
RTSP_PORT       = os.environ.get("RTSP_PORT",       "8554")
RTSP_NAME       = os.environ.get("RTSP_NAME",       "stream")

# Webcam FFmpeg options
# NOTE: CAM_FRAMERATE and CAM_RESOLUTION intentionally default to "" so that
# the device's native values (discovered via v4l2-ctl) are used as fallback.
# Set these env vars to override the native values.
CAM_RTBUFSIZE     = os.environ.get("CAM_RTBUFSIZE",     "100M")
CAM_VIDEO_CODEC   = os.environ.get("CAM_VIDEO_CODEC",   "libx264")
CAM_AUDIO_CODEC   = os.environ.get("CAM_AUDIO_CODEC",   "libopus")
CAM_VIDEO_BITRATE = os.environ.get("CAM_VIDEO_BITRATE", "600k")
CAM_AUDIO_BITRATE = os.environ.get("CAM_AUDIO_BITRATE", "64k")
CAM_PRESET        = os.environ.get("CAM_PRESET",        "ultrafast")
CAM_TUNE          = os.environ.get("CAM_TUNE",          "zerolatency")
CAM_FRAMERATE     = os.environ.get("CAM_FRAMERATE",     "")   # "" = use native
CAM_RESOLUTION    = os.environ.get("CAM_RESOLUTION",    "")   # "" = use native

# Video-file FFmpeg options
VID_VIDEO_CODEC   = os.environ.get("VID_VIDEO_CODEC",   "libx264")
VID_AUDIO_CODEC   = os.environ.get("VID_AUDIO_CODEC",   "libopus")
VID_VIDEO_BITRATE = os.environ.get("VID_VIDEO_BITRATE", "600k")
VID_AUDIO_BITRATE = os.environ.get("VID_AUDIO_BITRATE", "64k")
VID_PRESET        = os.environ.get("VID_PRESET",        "fast")
VID_DIR           = os.environ.get("VID_DIR",           "/videos")

# Misc
DEVICE_PROBE_TIMEOUT = int(os.environ.get("DEVICE_PROBE_TIMEOUT", "5"))
# ─────────────────────────────────────────────────────────────────────────────


def rtsp_url() -> str:
    return f"rtsp://{RTSP_HOST}:{RTSP_PORT}/{RTSP_NAME}"


def list_video_devices() -> list[str]:
    return sorted(glob.glob("/dev/video*"))


def device_has_image(device: str) -> "dict | None":
    """
    Try to grab a single frame from *device*.
    Returns a dict {"fmt", "size", "fps"} on success, None on failure.

    1. Permission check
    2. v4l2-ctl to confirm capture device and read native format/size/fps
    3. ffmpeg probe with native params first, then fallbacks
    """
    # Step 1: permission check
    if not os.access(device, os.R_OK):
        log.warning("Cannot read %s — permission denied. "
                    "Make sure the container is run with --device %s "
                    "and --group-add video", device, device)
        return None

    # Step 2: confirm it is a video capture device and read native parameters.
    native_fmt  = ""
    native_fps  = ""
    native_size = ""
    try:
        caps = subprocess.run(
            ["v4l2-ctl", "--device", device, "--all"],
            capture_output=True, text=True, timeout=5,
        )
        if caps.returncode == 0:
            if "Video Capture" not in caps.stdout:
                log.info("Skipping %s (not a capture device)", device)
                return None
            for line in caps.stdout.splitlines():
                # e.g. "  Pixel Format : 'YUYV' (YUYV 4:2:2)"
                if "Pixel Format" in line and "'" in line:
                    raw = line.split("'")[1].strip().lower()
                    _fmt_map = {
                        "yuyv": "yuyv422",
                        "mjpg": "mjpeg",
                        "mjpeg": "mjpeg",
                        "h264": "h264",
                        "nv12": "nv12",
                        "rgb3": "rgb24",
                    }
                    native_fmt = _fmt_map.get(raw, raw)
                # e.g. "  Width/Height      : 1600/1200"
                if "Width/Height" in line and "/" in line:
                    try:
                        parts = line.split(":")[1].strip()
                        w, h = parts.split("/")
                        native_size = f"{w.strip()}x{h.strip()}"
                    except Exception:
                        pass
                # e.g. "  Frames per second: 5.000 (5/1)"
                if "Frames per second" in line and "(" in line:
                    try:
                        frac = line.split("(")[1].split(")")[0].strip()
                        num, den = frac.split("/")
                        native_fps = str(int(round(int(num) / int(den))))
                    except Exception:
                        pass
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass  # v4l2-ctl not available — proceed without native hints

    log.info("Device %s reports format=%s size=%s fps=%s",
             device, native_fmt or "?", native_size or "?", native_fps or "?")

    # Step 3: build a prioritised format list — native format first.
    formats: list[str] = []
    if native_fmt:
        formats.append(native_fmt)
    for f in ("mjpeg", "yuyv422", ""):
        if f not in formats:
            formats.append(f)

    # Compute a per-attempt timeout generous enough for slow cameras.
    fps_int = int(native_fps) if native_fps.isdigit() and int(native_fps) > 0 else 0
    extra = max(4, 3 * (1 + (1 // max(fps_int, 1))))
    per_attempt = DEVICE_PROBE_TIMEOUT + extra

    log.info("Probing %s (per-attempt timeout %d s) …", device, per_attempt)
    for fmt in formats:
        cmd = ["ffmpeg", "-loglevel", "error", "-f", "v4l2"]
        if fmt:
            cmd += ["-input_format", fmt]
        if native_fps:
            cmd += ["-framerate", native_fps]
        if native_size:
            cmd += ["-video_size", native_size]
        cmd += ["-i", device, "-vframes", "1", "-f", "null", "-"]
        try:
            result = subprocess.run(cmd, timeout=per_attempt,
                                    capture_output=True, text=True)
            if result.returncode == 0:
                log.info("Device %s working (format=%s size=%s fps=%s)",
                         device, fmt or "auto", native_size or "?", native_fps or "?")
                return {"fmt": fmt or native_fmt, "size": native_size, "fps": native_fps}
            err_lines = (result.stderr or "").strip().splitlines()
            if err_lines:
                for err_line in err_lines:
                    log.warning("  ffmpeg [%s fmt=%s]: %s", device, fmt or "auto", err_line)
            else:
                log.warning("  ffmpeg [%s fmt=%s]: exited non-zero, no stderr",
                            device, fmt or "auto")
        except subprocess.TimeoutExpired:
            log.warning("Probe timed out for %s with format=%s (timeout=%d s) — "
                        "raise DEVICE_PROBE_TIMEOUT if the camera is genuinely slow",
                        device, fmt or "auto", per_attempt)

    log.info("No image from %s after trying all formats", device)
    return None


def find_working_camera() -> "tuple[str, dict] | tuple[None, None]":
    for dev in list_video_devices():
        params = device_has_image(dev)
        if params is not None:
            log.info("Found working camera: %s", dev)
            return dev, params
    return None, None


def h264_extra_flags() -> list[str]:
    """Extra flags needed for H264 WebRTC browser compatibility."""
    return [
        "-pix_fmt",    "yuv420p",
        "-profile:v",  "baseline",
        "-level:v",    "4.2",
        "-bf",         "0",
    ]


def device_has_audio(device: str) -> bool:
    """Check if a v4l2 device also has an associated audio capture capability."""
    try:
        result = subprocess.run(
            ["ffmpeg", "-loglevel", "error", "-f", "v4l2", "-i", device,
             "-t", "0.5", "-f", "null", "-"],
            capture_output=True, text=True, timeout=5,
        )
        return "Audio" in result.stderr or "audio" in result.stderr
    except Exception:
        return False


def stream_camera(device: str, native: dict) -> None:
    url = rtsp_url()
    log.info("Streaming camera %s → %s", device, url)

    has_audio = device_has_audio(device)
    if not has_audio:
        log.info("No audio stream detected on %s — streaming video only", device)

    # Use env-var overrides when explicitly set; fall back to native device
    # values discovered during probing.  This is critical for cameras like the
    # Arducam 16MP that only support 5 fps at 1600x1200 — requesting 30 fps
    # causes VIDIOC_STREAMON to return EPROTO (code 185) and ffmpeg exits.
    framerate  = CAM_FRAMERATE  or native.get("fps",  "")
    resolution = CAM_RESOLUTION or native.get("size", "")

    if not CAM_FRAMERATE and framerate:
        log.info("CAM_FRAMERATE not set — using device native fps=%s", framerate)
    if not CAM_RESOLUTION and resolution:
        log.info("CAM_RESOLUTION not set — using device native size=%s", resolution)

    cmd = [
        "ffmpeg", "-loglevel", "warning",
        "-f", "v4l2",
        "-rtbufsize", CAM_RTBUFSIZE,
    ]
    if framerate:
        cmd += ["-framerate", framerate]
    if resolution:
        cmd += ["-video_size", resolution]
    cmd += [
        "-i", device,
        "-c:v", CAM_VIDEO_CODEC,
    ]
    if CAM_VIDEO_CODEC == "libx264":
        cmd += h264_extra_flags()
        cmd += ["-preset", CAM_PRESET, "-tune", CAM_TUNE]
    cmd += ["-b:v", CAM_VIDEO_BITRATE]
    if has_audio:
        cmd += ["-c:a", CAM_AUDIO_CODEC, "-b:a", CAM_AUDIO_BITRATE]
    else:
        cmd += ["-an"]
    cmd += ["-f", "rtsp", url]

    while True:
        log.info("Running: %s", " ".join(cmd))
        proc = subprocess.run(cmd)
        if proc.returncode == 0:
            break
        log.warning("Camera stream exited with code %d, restarting in 3 s …",
                    proc.returncode)
        time.sleep(3)


def list_video_files() -> list[str]:
    exts = ("*.mp4", "*.mkv", "*.avi", "*.mov", "*.ts", "*.flv", "*.webm")
    files: list[str] = []
    for ext in exts:
        files.extend(glob.glob(os.path.join(VID_DIR, ext)))
    return sorted(files)


def stream_videos() -> None:
    url = rtsp_url()

    files = list_video_files()
    if not files:
        log.error(
            "No video files found in '%s' and no working camera detected. "
            "Mount a directory containing video files with: "
            "-v /your/videos:%s:ro,z",
            VID_DIR, VID_DIR,
        )
        sys.exit(1)

    while True:
        files = list_video_files()
        if not files:
            log.warning("No video files found in %s. Retrying in 10 s …", VID_DIR)
            time.sleep(10)
            continue

        for vf in files:
            log.info("Streaming file %s → %s", vf, url)
            cmd = [
                "ffmpeg", "-loglevel", "warning",
                "-re",
                "-i", vf,
                "-c:v", VID_VIDEO_CODEC,
            ]
            if VID_VIDEO_CODEC == "libx264":
                cmd += h264_extra_flags()
                cmd += ["-preset", VID_PRESET]
            cmd += [
                "-b:v", VID_VIDEO_BITRATE,
                "-c:a", VID_AUDIO_CODEC,
                "-b:a", VID_AUDIO_BITRATE,
                "-f", "rtsp", url,
            ]
            log.info("Running: %s", " ".join(cmd))
            proc = subprocess.run(cmd)
            if proc.returncode not in (0, 1):
                log.warning("ffmpeg exited with code %d for file %s",
                            proc.returncode, vf)
            time.sleep(1)

        log.info("Playlist finished, restarting from the beginning …")


def main() -> None:
    log.info("RTSP streamer starting up.")
    log.info("Target URL: %s", rtsp_url())

    camera, native_params = find_working_camera()
    if camera:
        stream_camera(camera, native_params)
    else:
        log.info("No working camera found. Falling back to video files in %s.", VID_DIR)
        stream_videos()


if __name__ == "__main__":
    main()