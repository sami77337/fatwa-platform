"""Real local decoder tests; source material is generated, never a scholarly corpus."""

import io
import subprocess
import sys
import tempfile
import unittest
import wave
from pathlib import Path
from time import monotonic
from unittest.mock import patch

from PIL import Image

from . import execution


def recording():
    stream = io.BytesIO()
    with wave.open(stream, "wb") as output:
        output.setnchannels(2)
        output.setsampwidth(2)
        output.setframerate(8000)
        # Deliberately different channels and a non-silent tail: no downmix/cut.
        output.writeframes((b"\x10\x02\x20\x03" * 8000) + (b"\x44\x04\x55\x05" * 800))
    return stream.getvalue()


def picture():
    stream = io.BytesIO()
    Image.new("RGB", (640, 320), (210, 40, 60)).save(stream, format="PNG")
    return stream.getvalue()


class RealFFmpegExecutionTests(unittest.TestCase):
    def engine(self):
        return execution.FFmpegProcessor("/usr/bin/ffmpeg", "/usr/bin/ffprobe")

    def test_full_audio_preserves_channels_rate_tail_and_original(self):
        raw = recording()
        before = bytes(raw)
        result = self.engine().run(raw, media_type="audio/wav", task="AUDIO_PLAYBACK")
        self.assertEqual(result.status, "READY", result.code)
        self.assertEqual(raw, before)
        with wave.open(io.BytesIO(raw)) as original, wave.open(io.BytesIO(result.raw)) as derived:
            self.assertEqual(derived.getparams(), original.getparams())
            self.assertEqual(derived.readframes(100000), original.readframes(100000))
        self.assertEqual(result.media_type, "audio/wav")
        self.assertEqual(result.engine["mode"], "LOCAL_FFMPEG")
        self.assertEqual(len(result.engine["ffmpeg_sha256"]), 64)
        self.assertIn("ffmpeg version", result.engine["ffmpeg_version"])

    def test_real_thumbnail_preserves_full_frame_aspect_and_original(self):
        raw = picture()
        result = self.engine().run(raw, media_type="image/png", task="THUMBNAIL")
        self.assertEqual(result.status, "READY", result.code)
        self.assertEqual(raw, picture())
        with Image.open(io.BytesIO(result.raw)) as output:
            self.assertEqual(output.format, "PNG")
            self.assertEqual(output.size, (320, 160))
            self.assertEqual(output.getpixel((0, 0)), (210, 40, 60))
            self.assertEqual(output.getpixel((319, 159)), (210, 40, 60))

    def test_video_thumbnail_preserves_display_aspect_for_non_square_pixels(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "synthetic.webm"
            subprocess.run(
                [
                    "/usr/bin/ffmpeg",
                    "-v",
                    "error",
                    "-threads",
                    "1",
                    "-f",
                    "lavfi",
                    "-i",
                    "color=c=red:s=64x32:r=2:d=1",
                    "-vf",
                    "setsar=2/1",
                    "-c:v",
                    "libvpx-vp9",
                    "-threads",
                    "1",
                    "-an",
                    "-y",
                    str(path),
                ],
                check=True,
                timeout=5,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
            )
            raw = path.read_bytes()
        result = self.engine().run(raw, media_type="video/webm", task="THUMBNAIL")
        self.assertEqual(result.status, "READY", result.code)
        with Image.open(io.BytesIO(result.raw)) as output:
            self.assertEqual(output.size, (128, 32))

    def test_missing_binary_is_unavailable_and_has_no_fake_output(self):
        result = execution.FFmpegProcessor("/missing/ffmpeg", "/missing/ffprobe").run(
            recording(), media_type="audio/wav", task="AUDIO_PLAYBACK"
        )
        self.assertEqual((result.status, result.raw, result.engine), ("UNAVAILABLE", b"", {}))

    def test_unsupported_asr_or_filter_cannot_become_an_engine_command(self):
        for task in ("TRANSCRIPT", "APPROVE_ANSWER", "THUMBNAIL;touch /tmp/no", ""):
            with self.subTest(task=task):
                with self.assertRaises(ValueError):
                    self.engine().run(recording(), media_type="audio/wav", task=task)

    def test_kind_mismatch_and_external_playlist_are_rejected(self):
        for raw, media_type, task in (
            (recording(), "video/mp4", "THUMBNAIL"),
            (b"#EXTM3U\nhttps://example.invalid/private.wav\n", "audio/wav", "AUDIO_PLAYBACK"),
            (picture(), "image/png", "AUDIO_PLAYBACK"),
        ):
            with self.subTest(media_type=media_type, task=task):
                result = self.engine().run(raw, media_type=media_type, task=task)
                self.assertEqual(result.status, "FAILED")
                self.assertEqual(result.raw, b"")

    def test_original_input_bound_precedes_decoder(self):
        with patch.object(execution, "invoke") as child:
            result = self.engine().run(b"x" * 192001, media_type="audio/wav", task="AUDIO_PLAYBACK")
        self.assertEqual(result.status, "FAILED")
        child.assert_not_called()

    def test_cancellation_before_child_leaves_no_result(self):
        with patch.object(execution, "invoke") as child:
            result = self.engine().run(
                recording(), media_type="audio/wav", task="AUDIO_PLAYBACK", cancelled=lambda: True
            )
        self.assertEqual((result.status, result.raw), ("CANCELLED", b""))
        child.assert_not_called()


class BoundedDecoderProcessTests(unittest.TestCase):
    def test_ignored_deadline_is_killed_and_reaped_without_waiting_for_child(self):
        began = monotonic()
        with self.assertRaises(TimeoutError):
            execution.invoke(
                [sys.executable, "-c", "import time; time.sleep(30)"],
                b"",
                timeout=0.05,
                limit=128,
            )
        self.assertLess(monotonic() - began, 2)

    def test_output_limit_is_rejection_instead_of_truncation(self):
        with self.assertRaises(ValueError):
            execution.invoke(
                [sys.executable, "-c", "import sys; sys.stdout.buffer.write(b'x' * 1000000)"],
                b"",
                timeout=2,
                limit=128,
            )

    def test_current_cancellation_during_process_discards_all_buffered_bytes(self):
        started = monotonic()
        with self.assertRaises(InterruptedError):
            execution.invoke(
                [
                    sys.executable,
                    "-c",
                    "import sys,time; print('partial',flush=True); time.sleep(30)",
                ],
                b"",
                timeout=2,
                limit=128,
                cancelled=lambda: monotonic() - started > 0.05,
            )
        self.assertLess(monotonic() - started, 2)
