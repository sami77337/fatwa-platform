"""Bounded real local ffmpeg execution. No Django, provider, network or stored grant."""

import base64
import io
import json
import os
import selectors
import signal
import stat
import subprocess
import sys
import wave
from dataclasses import dataclass, field
from hashlib import sha256
from pathlib import Path
from threading import BoundedSemaphore
from time import monotonic

TASKS = frozenset({"THUMBNAIL", "AUDIO_PLAYBACK"})
RECIPE_VERSION = "technical-private-v1"
MAX_INPUT = 192000
MAX_OUTPUT = 8 * 1024 * 1024
WALL_SECONDS = 15
SLOT = BoundedSemaphore(1)
ENV = {"PATH": os.defpath, "LANG": "C.UTF-8", "LC_ALL": "C.UTF-8", "PYTHONDONTWRITEBYTECODE": "1"}


@dataclass(frozen=True, slots=True)
class Outcome:
    status: str
    code: str
    raw: bytes = b""
    media_type: str = ""
    metadata: dict = field(default_factory=dict)
    engine: dict = field(default_factory=dict)


def invoke(command, raw, *, timeout, limit, cancelled=lambda: False):
    """Drain bounded pipes and kill/reap this process group on every failed exit.

    No preexec_fn in a threaded server. The worker applies its own rlimits before
    opening a decoder. This controller never waits on a timed-out executor pool.
    """
    process = subprocess.Popen(
        command,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        start_new_session=True,
        env=ENV,
        cwd=Path(__file__).resolve().parents[2],
        close_fds=True,
    )
    started, written = monotonic(), 0
    output, error = bytearray(), bytearray()
    selector = selectors.DefaultSelector()
    try:
        for stream, event, name in (
            (process.stdin, selectors.EVENT_WRITE, "input"),
            (process.stdout, selectors.EVENT_READ, "output"),
            (process.stderr, selectors.EVENT_READ, "error"),
        ):
            os.set_blocking(stream.fileno(), False)
            selector.register(stream, event, name)
        while selector.get_map():
            if cancelled():
                raise InterruptedError("cancelled")
            if monotonic() - started > timeout:
                raise TimeoutError("bounded_child_timeout")
            for key, _ in selector.select(0.05):
                stream = key.fileobj
                if key.data == "input":
                    try:
                        if written < len(raw):
                            written += os.write(stream.fileno(), raw[written : written + 65536])
                        if written == len(raw):
                            selector.unregister(stream)
                            stream.close()
                    except BrokenPipeError:
                        selector.unregister(stream)
                        stream.close()
                else:
                    part = os.read(stream.fileno(), 65536)
                    if not part:
                        selector.unregister(stream)
                        stream.close()
                        continue
                    target = output if key.data == "output" else error
                    target.extend(part)
                    if len(target) > (limit if key.data == "output" else 8192):
                        raise ValueError("bounded_child_output")
        process.wait(timeout=max(0.01, timeout - (monotonic() - started)))
        if process.returncode != 0 or error:
            raise ValueError("bounded_child_failed")
        return bytes(output)
    finally:
        selector.close()
        if process.poll() is None:
            os.killpg(process.pid, signal.SIGKILL)
        # A child cannot escape with a live group even after its main process
        # exits: it has no reason to leave decoder descendants behind.
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        process.wait(timeout=2)
        for stream in (process.stdin, process.stdout, process.stderr):
            if stream and not stream.closed:
                stream.close()


def _binary(path):
    if type(path) is not str or not path.startswith("/"):
        raise OSError("configured_absolute_binary_required")
    selected = Path(path)
    info = selected.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_mode & 0o022 or not os.access(selected, os.X_OK):
        raise OSError("trusted_local_binary_required")
    if not 1 <= info.st_size <= 100 * 1024 * 1024:
        raise OSError("binary_bound")
    return sha256(selected.read_bytes()).hexdigest(), (
        info.st_dev,
        info.st_ino,
        info.st_size,
        info.st_mtime_ns,
    )


def validate_output(raw, media_type, metadata):
    if type(raw) is not bytes or not 1 <= len(raw) <= MAX_OUTPUT or type(metadata) is not dict:
        raise ValueError("invalid_derivative")
    if media_type == "image/png":
        from PIL import Image

        with Image.open(io.BytesIO(raw)) as image:
            if (
                image.format != "PNG"
                or image.width > 320
                or image.height > 320
                or image.n_frames != 1
            ):
                raise ValueError("invalid_thumbnail")
            image.verify()
        with Image.open(io.BytesIO(raw)) as image:
            image.load()
            if metadata != {"width": image.width, "height": image.height, "frame_ms": 0}:
                raise ValueError("thumbnail_metadata")
    elif media_type == "audio/wav":
        with wave.open(io.BytesIO(raw)) as sound:
            channels, rate, frames = sound.getnchannels(), sound.getframerate(), sound.getnframes()
            if (
                sound.getsampwidth() != 2
                or sound.getcomptype() != "NONE"
                or not 1 <= channels <= 2
                or not 8000 <= rate <= 96000
                or not 0 < frames / rate <= 120
                or len(sound.readframes(frames)) != frames * channels * 2
                or metadata != {"channels": channels, "sample_rate": rate, "frames": frames}
                or len(raw) != 44 + frames * channels * 2
            ):
                raise ValueError("invalid_playback")
    else:
        raise ValueError("unsupported_derivative")


@dataclass(frozen=True, slots=True)
class FFmpegProcessor:
    executable: str
    probe: str

    def identity(self, cancelled=lambda: False):
        result = {"mode": "LOCAL_FFMPEG", "recipe_version": RECIPE_VERSION}
        for key, path in (("ffmpeg", self.executable), ("ffprobe", self.probe)):
            digest, before = _binary(path)
            version = invoke([path, "-version"], b"", timeout=2, limit=8192, cancelled=cancelled)
            first = version.decode("utf-8", "strict").splitlines()[0]
            if (
                not first.startswith(key + " version ")
                or len(first) > 512
                or _binary(path) != (digest, before)
            ):
                raise OSError("binary_identity_changed")
            result[key + "_version"] = first
            result[key + "_sha256"] = digest
        return result

    def run(self, raw, *, media_type, task, cancelled=lambda: False):
        if task not in TASKS:
            raise ValueError("unsupported_derivative_task")
        if type(raw) is not bytes or not 1 <= len(raw) <= MAX_INPUT:
            return Outcome("FAILED", "INPUT_BOUND")
        if cancelled():
            return Outcome("CANCELLED", "CANCELLED")
        if not SLOT.acquire(blocking=False):
            return Outcome("UNAVAILABLE", "PROCESSOR_BUSY")
        engine = {}
        try:
            try:
                engine = self.identity(cancelled)
            except InterruptedError:
                return Outcome("CANCELLED", "CANCELLED")
            except (OSError, ValueError, TimeoutError, subprocess.TimeoutExpired):
                return Outcome("UNAVAILABLE", "PROCESSOR_UNAVAILABLE")
            payload = json.dumps(
                {
                    "raw": base64.b64encode(raw).decode("ascii"),
                    "task": task,
                    "media_type": media_type,
                    "executable": self.executable,
                    "probe": self.probe,
                }
            ).encode()
            output = invoke(
                [sys.executable, "-m", "apps.media_derivatives.worker"],
                payload,
                timeout=WALL_SECONDS,
                limit=MAX_OUTPUT * 4 // 3 + 16384,
                cancelled=cancelled,
            )
            result = json.loads(output)
            if type(result) is not dict or set(result) != {"raw", "media_type", "metadata"}:
                raise ValueError("invalid_worker_output")
            derived = base64.b64decode(result["raw"], validate=True)
            validate_output(derived, result["media_type"], result["metadata"])
            if result["media_type"] != ("image/png" if task == "THUMBNAIL" else "audio/wav"):
                raise ValueError("wrong_recipe_output")
            if self.identity(cancelled) != engine:
                raise ValueError("binary_identity_changed")
            return Outcome(
                "READY", "READY", derived, result["media_type"], result["metadata"], engine
            )
        except InterruptedError:
            return Outcome("CANCELLED", "CANCELLED", engine=engine)
        except (TimeoutError, subprocess.TimeoutExpired):
            return Outcome("FAILED", "PROCESSING_TIMEOUT", engine=engine)
        except (OSError, ValueError, TypeError, KeyError, UnicodeError):
            return Outcome("FAILED", "PROCESSING_REJECTED", engine=engine)
        finally:
            SLOT.release()
