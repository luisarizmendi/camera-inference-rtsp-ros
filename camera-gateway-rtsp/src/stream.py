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
CAM_RTBUFSIZE     = os.environ.get("CAM_RTBUFSIZE",     "100M")
CAM_VIDEO_CODEC   = os.environ.get("CAM_VIDEO_CODEC",   "libx264")
CAM_AUDIO_CODEC   = os.environ.get("CAM_AUDIO_CODEC",   "libopus")
CAM_VIDEO_BITRATE = os.environ.get("CAM_VIDEO_BITRATE", "600k")
CAM_AUDIO_BITRATE = os.environ.get("CAM_AUDIO_BITRATE", "64k")
CAM_PRESET        = os.environ.get("CAM_PRESET",        "ultrafast")
CAM_TUNE          = os.environ.get("CAM_TUNE",          "zerolatency")
CAM_FRAMERATE     = os.environ.get("CAM_FRAMERATE",     "30")
CAM_RESOLUTION    = os.environ.get("CAM_RESOLUTION",    "")

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


def device_has_image(device: str) -> bool:
    """
    Try to grab a single frame from *device*.
    1. Check device is readable (permission check)
    2. Use v4l2-ctl to confirm it is a capture device
    3. Try ffmpeg probe with mjpeg, yuyv, and default formats in sequence
    """
    # Step 1: permission check
    if not os.access(device, os.R_OK):
        log.warning("Cannot read %s — permission denied. "
                    "Make sure the container is run with --device %s "
                    "and --group-add video", device, device)
        return False

    # Step 2: check it is a video capture device (not metadata/output node)
    try:
        caps = subprocess.run(
            ["v4l2-ctl", "--device", device, "--info"],
            capture_output=True, text=True, timeout=3,
        )
        if caps.returncode == 0 and "Video Capture" not in caps.stdout:
            log.info("Skipping %s (not a capture device)", device)
            return False
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass  # v4l2-ctl not available — proceed anyway

    # Step 3: try several input formats — webcams vary widely
    formats = ["mjpeg", "yuyv422", ""]   # empty string = let ffmpeg decide
    log.info("Probing %s …", device)
    for fmt in formats:
        cmd = ["ffmpeg", "-loglevel", "warning", "-f", "v4l2"]
        if fmt:
            cmd += ["-input_format", fmt]
        cmd += ["-i", device, "-vframes", "1", "-f", "null", "-"]
        try:
            result = subprocess.run(cmd, timeout=DEVICE_PROBE_TIMEOUT + 2,
                                    capture_output=True, text=True)
            if result.returncode == 0:
                log.info("Device %s working (format: %s)", device, fmt or "auto")
                return True
            last_err = (result.stderr or "").strip().splitlines()
            last_err = last_err[-1] if last_err else "unknown error"
            log.debug("Format %s failed on %s: %s", fmt or "auto", device, last_err)
        except subprocess.TimeoutExpired:
            log.debug("Probe timed out for %s with format %s", device, fmt or "auto")

    log.info("No image from %s after trying all formats", device)
    return False


def find_working_camera() -> str | None:
    for dev in list_video_devices():
        if device_has_image(dev):
            log.info("Found working camera: %s", dev)
            return dev
    return None


def h264_extra_flags() -> list[str]:
    """Extra flags needed for H264 WebRTC browser compatibility."""
    return [
        "-pix_fmt",    "yuv420p",
        "-profile:v",  "baseline",
        "-level:v",    "4.2",        # 4.2 supports up to 1080p60 / 4K30
        "-bf",         "0",          # no B-frames (WebRTC requirement)
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


def stream_camera(device: str) -> None:
    url = rtsp_url()
    log.info("Streaming camera %s → %s", device, url)

    has_audio = device_has_audio(device)
    if not has_audio:
        log.info("No audio stream detected on %s — streaming video only", device)

    cmd = [
        "ffmpeg", "-loglevel", "warning",
        "-f", "v4l2",
        "-rtbufsize", CAM_RTBUFSIZE,
        "-framerate", CAM_FRAMERATE,
    ]
    if CAM_RESOLUTION:
        cmd += ["-video_size", CAM_RESOLUTION]
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
        cmd += ["-an"]   # explicitly disable audio to avoid warnings
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

    # Check once at startup — if the directory is empty, exit clearly rather
    # than looping forever with no useful output.
    files = list_video_files()
    if not files:
        log.error(
            "No video files found in '%s' and no working camera detected. "            "Mount a directory containing video files with: "            "-v /your/videos:%s:ro,z",
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

    camera = find_working_camera()
    if camera:
        stream_camera(camera)
    else:
        log.info("No working camera found. Falling back to video files in %s.", VID_DIR)
        stream_videos()


if __name__ == "__main__":
    main()
