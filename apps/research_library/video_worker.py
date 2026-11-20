"""Isolated local decode, with no URL, network, playlist, attachment or file protocol."""

import json
import math
import resource
import subprocess
import sys


def main():
    resource.setrlimit(resource.RLIMIT_CPU, (7, 7))
    resource.setrlimit(resource.RLIMIT_AS, (768 * 1024 * 1024, 768 * 1024 * 1024))
    resource.setrlimit(resource.RLIMIT_FSIZE, (0, 0))
    resource.setrlimit(resource.RLIMIT_NOFILE, (32, 32))
    raw = sys.stdin.buffer.read(192001)
    extension = sys.argv[1]
    if not 1 <= len(raw) <= 192000 or extension not in {"webm", "mp4"}:
        raise ValueError
    probe = subprocess.run(
        [
            "/usr/bin/ffprobe",
            "-v",
            "error",
            "-threads",
            "1",
            "-protocol_whitelist",
            "pipe",
            "-i",
            "pipe:0",
            "-show_entries",
            "format=format_name,duration:stream=codec_type,codec_name,width,height,duration",
            "-of",
            "json",
        ],
        input=raw,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=3,
    )
    if probe.returncode or probe.stderr or len(probe.stdout) > 8192:
        raise ValueError
    data = json.loads(probe.stdout)
    streams = data["streams"]
    videos = [s for s in streams if s["codec_type"] == "video"]
    audios = [s for s in streams if s["codec_type"] == "audio"]
    if (
        len(videos) != 1
        or len(audios) > 1
        or len(streams) != len(videos) + len(audios)
        or videos[0]["codec_name"] not in {"h264", "vp8", "vp9"}
        or any(a["codec_name"] not in {"aac", "opus", "vorbis"} for a in audios)
    ):
        raise ValueError
    container = data["format"]["format_name"]
    if (extension == "webm" and "webm" not in container) or (
        extension == "mp4" and "mp4" not in container
    ):
        raise ValueError
    duration = float(data["format"].get("duration", videos[0].get("duration", "nan")))
    width, height = videos[0]["width"], videos[0]["height"]
    if (
        not math.isfinite(duration)
        or not 0 < duration <= 60
        or not (1 <= width <= 1280 and 1 <= height <= 720)
    ):
        raise ValueError
    decode = subprocess.run(
        [
            "/usr/bin/ffmpeg",
            "-v",
            "error",
            "-nostdin",
            "-threads",
            "1",
            "-protocol_whitelist",
            "pipe",
            "-i",
            "pipe:0",
            "-threads",
            "1",
            "-map",
            "0:v:0",
            "-map",
            "0:a?",
            "-f",
            "null",
            "-",
        ],
        input=raw,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        timeout=5,
    )
    if decode.returncode or decode.stderr:
        raise ValueError
    print(
        json.dumps(
            {
                "validated": True,
                "kind": "video",
                "duration_seconds": duration,
                "width": width,
                "height": height,
                "codec": videos[0]["codec_name"],
            }
        )
    )


if __name__ == "__main__":
    try:
        main()
    except Exception:
        sys.exit(1)
