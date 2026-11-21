"""Resource-limited derivative process. No Django, database, URLs or user options."""

import base64
import io
import json
import math
import resource
import subprocess
import sys
import wave
from fractions import Fraction

from apps.private_media.worker import _audio, _image

from .execution import MAX_INPUT, MAX_OUTPUT, TASKS

EXTENSIONS = {
    "audio/wav": ".wav",
    "audio/mpeg": ".mp3",
    "audio/mp4": ".m4a",
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/webp": ".webp",
}


def command(executable, raw, options, *, limit):
    result = subprocess.run(
        [executable, *options],
        input=raw,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=7,
        check=False,
    )
    if result.returncode or result.stderr or not 1 <= len(result.stdout) <= limit:
        raise ValueError("decode_rejected")
    return result.stdout


def inspect_video(probe, raw, media_type):
    output = command(
        probe,
        raw,
        [
            "-v",
            "error",
            "-threads",
            "1",
            "-protocol_whitelist",
            "pipe",
            "-i",
            "pipe:0",
            "-show_entries",
            "format=format_name,duration:stream=codec_type,codec_name,width,height,duration,channels,sample_rate,sample_aspect_ratio",
            "-of",
            "json",
        ],
        limit=8192,
    )
    data = json.loads(output)
    streams = data["streams"]
    video = [item for item in streams if item["codec_type"] == "video"]
    audio = [item for item in streams if item["codec_type"] == "audio"]
    if (
        len(video) != 1
        or len(audio) > 1
        or len(video) + len(audio) != len(streams)
        or video[0]["codec_name"] not in {"h264", "vp8", "vp9"}
        or any(item["codec_name"] not in {"aac", "opus", "vorbis"} for item in audio)
        or not (1 <= video[0]["width"] <= 1280 and 1 <= video[0]["height"] <= 720)
        or ("webm" if media_type == "video/webm" else "mp4") not in data["format"]["format_name"]
    ):
        raise ValueError("video_contract")
    duration = float(data["format"].get("duration", video[0].get("duration", "nan")))
    if not math.isfinite(duration) or not 0 < duration <= 60:
        raise ValueError("video_duration")
    return {
        "width": video[0]["width"],
        "height": video[0]["height"],
        "duration_seconds": duration,
        "audio": audio,
        "sample_aspect_ratio": video[0].get("sample_aspect_ratio", "1:1"),
    }


def main():
    for name, bound in (
        ("RLIMIT_CPU", 12),
        ("RLIMIT_AS", 768 * 1024 * 1024),
        ("RLIMIT_FSIZE", 0),
        ("RLIMIT_NOFILE", 32),
        ("RLIMIT_CORE", 0),
    ):
        resource.setrlimit(getattr(resource, name), (bound, bound))
    request = json.loads(sys.stdin.buffer.read(300001))
    if set(request) != {"raw", "task", "media_type", "executable", "probe"}:
        raise ValueError("worker_contract")
    raw = base64.b64decode(request["raw"], validate=True)
    task, media_type = request["task"], request["media_type"]
    if not 1 <= len(raw) <= MAX_INPUT or task not in TASKS:
        raise ValueError("worker_bound")
    if media_type in {"video/mp4", "video/webm"}:
        original = inspect_video(request["probe"], raw, media_type)
    elif media_type in EXTENSIONS:
        original = (_audio if media_type.startswith("audio/") else _image)(
            raw, EXTENSIONS[media_type]
        )
    else:
        raise ValueError("unsupported_original")
    options = [
        "-v",
        "error",
        "-nostdin",
        "-threads",
        "1",
        "-filter_threads",
        "1",
        "-protocol_whitelist",
        "pipe",
        "-noautorotate",
        "-i",
        "pipe:0",
        "-threads",
        "1",
        "-map_metadata",
        "-1",
        "-map_chapters",
        "-1",
        "-sn",
        "-dn",
    ]
    if task == "THUMBNAIL":
        if not media_type.startswith(("image/", "video/")):
            raise ValueError("thumbnail_source")
        aspect = original.get("sample_aspect_ratio", "1:1")
        if aspect in {"N/A", "0:1"}:
            aspect = "1:1"
        numerator, denominator = [int(value) for value in aspect.split(":")]
        if not 1 <= numerator <= 10000 or not 1 <= denominator <= 10000:
            raise ValueError("video_aspect")
        width, height = Fraction(original["width"] * numerator, denominator), original["height"]
        factor = min(Fraction(1), Fraction(320, 1) / width, Fraction(320, height))
        target_width, target_height = max(1, int(width * factor)), max(1, int(height * factor))
        options += [
            "-map",
            "0:v:0",
            "-an",
            "-frames:v",
            "1",
            "-vf",
            f"scale=w={target_width}:h={target_height},setsar=1",
            "-c:v",
            "png",
            "-pix_fmt",
            "rgb24",
            "-f",
            "image2pipe",
            "pipe:1",
        ]
        derived = command(request["executable"], raw, options, limit=400000)
        metadata = _image(derived, ".png")
        metadata = {"width": metadata["width"], "height": metadata["height"], "frame_ms": 0}
        output_type = "image/png"
    else:
        if media_type.startswith("video/"):
            if len(original["audio"]) != 1:
                raise ValueError("video_has_no_audio")
            audio = original["audio"][0]
            channels, rate = int(audio["channels"]), int(audio["sample_rate"])
        elif media_type.startswith("audio/"):
            channels, rate = original["channels"], original["sample_rate"]
        else:
            raise ValueError("playback_source")
        if not 1 <= channels <= 2 or not 8000 <= rate <= 96000:
            raise ValueError("audio_parameters")
        if channels * rate * 2 * original["duration_seconds"] + 44 > MAX_OUTPUT:
            raise ValueError("audio_output_bound")
        # No -t/-ss/-ar/-ac or a truncating -fs: preserve complete time range,
        # sample rate and distinct channels. The output cap is rejection only.
        options += ["-map", "0:a:0", "-vn", "-c:a", "pcm_s16le", "-f", "s16le", "pipe:1"]
        pcm = command(request["executable"], raw, options, limit=MAX_OUTPUT - 44)
        if len(pcm) % (2 * channels):
            raise ValueError("partial_audio_frame")
        frames = len(pcm) // (2 * channels)
        if abs(frames / rate - original["duration_seconds"]) > 0.25 or not 0 < frames / rate <= 120:
            raise ValueError("incomplete_audio")
        if media_type == "audio/wav":
            with wave.open(io.BytesIO(raw)) as source:
                if frames != source.getnframes():
                    raise ValueError("incomplete_original_audio")
        output = io.BytesIO()
        with wave.open(output, "wb") as sound:
            sound.setnchannels(channels)
            sound.setsampwidth(2)
            sound.setframerate(rate)
            sound.writeframes(pcm)
        derived = output.getvalue()
        metadata = {"channels": channels, "sample_rate": rate, "frames": frames}
        output_type = "audio/wav"
    print(
        json.dumps(
            {
                "raw": base64.b64encode(derived).decode(),
                "media_type": output_type,
                "metadata": metadata,
            }
        )
    )


if __name__ == "__main__":
    try:
        main()
    except Exception:
        sys.exit(1)
