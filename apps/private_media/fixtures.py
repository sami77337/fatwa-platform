"""Fabricated test-only files; no human voice or source documents."""

import io
import wave
from pathlib import Path


def synthetic_files():
    from PIL import Image
    from pypdf import PdfWriter

    files = [("synthetic.txt", "text/plain", "نص اصطناعي".encode())]
    for suffix, media, format_name in (
        ("jpg", "image/jpeg", "JPEG"),
        ("png", "image/png", "PNG"),
        ("webp", "image/webp", "WEBP"),
    ):
        output = io.BytesIO()
        Image.new("RGB", (16, 12), "#698abc").save(output, format=format_name)
        files.append(("synthetic." + suffix, media, output.getvalue()))
    output = io.BytesIO()
    writer = PdfWriter()
    writer.add_blank_page(width=200, height=200)
    writer.write(output)
    files.append(("synthetic.pdf", "application/pdf", output.getvalue()))
    output = io.BytesIO()
    with wave.open(output, "wb") as sound:
        sound.setnchannels(1)
        sound.setsampwidth(2)
        sound.setframerate(16000)
        sound.writeframes(b"\x00\x00" * 1600)
    files.append(("synthetic.wav", "audio/wav", output.getvalue()))
    for suffix, media in (("mp3", "audio/mpeg"), ("m4a", "audio/mp4")):
        raw = (
            Path(__file__).with_suffix("").parent / "fixtures" / ("synthetic." + suffix)
        ).read_bytes()
        files.append(("synthetic." + suffix, media, raw))
    return files
