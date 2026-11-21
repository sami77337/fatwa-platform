"""Locally generated, content-free video fixtures; never uploaded user material."""

import base64
import subprocess
from functools import lru_cache
from pathlib import Path


@lru_cache(maxsize=2)
def video(extension="webm"):
    raw = base64.b64decode(Path(__file__).with_name("synthetic_video.b64").read_text())
    if extension == "webm":
        return raw
    if extension != "mp4":
        raise ValueError("unsupported synthetic video format")
    return subprocess.run(
        ["/usr/bin/ffmpeg", "-v", "error", "-nostdin", "-threads", "1",
         "-protocol_whitelist", "pipe", "-i", "pipe:0", "-an", "-c:v", "libx264",
         "-threads", "1", "-pix_fmt", "yuv420p", "-movflags", "frag_keyframe+empty_moov",
         "-f", "mp4", "pipe:1"],
        input=raw, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True, timeout=8,
    ).stdout
