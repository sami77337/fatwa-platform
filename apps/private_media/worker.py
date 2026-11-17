"""Isolated parsers: no Django, no URLs, no extraction of attachments or active content."""

import base64
import io
import json
import struct
import sys
import warnings
import wave

MAX_PIXELS = 4_000_000
MAX_DURATION = 120


def _image(raw, extension):
    from PIL import Image

    Image.MAX_IMAGE_PIXELS = MAX_PIXELS
    warnings.simplefilter("error", Image.DecompressionBombWarning)
    expected = {".jpg": "JPEG", ".jpeg": "JPEG", ".png": "PNG", ".webp": "WEBP"}[extension]
    with Image.open(io.BytesIO(raw)) as image:
        if (
            image.format != expected
            or image.width * image.height > MAX_PIXELS
            or getattr(image, "n_frames", 1) != 1
        ):
            raise ValueError
        image.verify()
    with Image.open(io.BytesIO(raw)) as image:
        image.load()
        return {"width": image.width, "height": image.height, "format": expected}


def _pdf(raw):
    from pypdf import PdfReader
    from pypdf.generic import ArrayObject, DictionaryObject, IndirectObject, StreamObject

    if not raw.startswith(b"%PDF-") or not raw.rstrip().endswith(b"%%EOF"):
        raise ValueError
    reader = PdfReader(io.BytesIO(raw), strict=True)
    if reader.is_encrypted or not 1 <= len(reader.pages) <= 10:
        raise ValueError
    blocked = {
        "/A",
        "/Annots",
        "/Next",
        "/3D",
        "/Rendition",
        "/JS",
        "/JavaScript",
        "/AA",
        "/OpenAction",
        "/EmbeddedFiles",
        "/EmbeddedFile",
        "/RichMedia",
        "/Launch",
        "/GoToR",
        "/URI",
        "/SubmitForm",
        "/ImportData",
        "/AcroForm",
        "/XFA",
        "/Encrypt",
        "/Sound",
        "/Movie",
    }
    seen = set()
    count, decoded = 0, 0

    def visit(obj, depth=0):
        nonlocal count, decoded
        count += 1
        if count > 4096 or depth > 32:
            raise ValueError
        if isinstance(obj, IndirectObject):
            identity = (obj.idnum, obj.generation)
            if identity in seen:
                return
            seen.add(identity)
            obj = obj.get_object()
        if isinstance(obj, DictionaryObject):
            if any(str(key) in blocked or str(value) in blocked for key, value in obj.items()):
                raise ValueError
            if isinstance(obj, StreamObject):
                decoded += len(obj.get_data())
                if decoded > 4_000_000:
                    raise ValueError
            for value in obj.values():
                visit(value, depth + 1)
        elif isinstance(obj, ArrayObject):
            for value in obj:
                visit(value, depth + 1)

    visit(reader.trailer)
    for page in reader.pages:
        if (
            not 0 < float(page.mediabox.width) <= 20000
            or not 0 < float(page.mediabox.height) <= 20000
        ):
            raise ValueError
    return {"pages": len(reader.pages), "active_content": False}


def _atoms(raw, start=0, end=None, depth=0):
    end = len(raw) if end is None else end
    if depth > 12:
        raise ValueError
    result = []
    while start < end:
        if end - start < 8:
            raise ValueError
        size, name = struct.unpack_from(">I4s", raw, start)
        header = 8
        if size == 1:
            if end - start < 16:
                raise ValueError
            size, header = struct.unpack_from(">Q", raw, start + 8)[0], 16
        if size < header or start + size > end:
            raise ValueError
        result.append((name, start + header, start + size))
        if len(result) > 2048:
            raise ValueError
        start += size
    return result


def _audio(raw, extension):
    if extension == ".wav":
        if (
            not raw.startswith(b"RIFF")
            or raw[8:12] != b"WAVE"
            or struct.unpack_from("<I", raw, 4)[0] + 8 != len(raw)
        ):
            raise ValueError
        with wave.open(io.BytesIO(raw)) as sound:
            channels, rate, frames = sound.getnchannels(), sound.getframerate(), sound.getnframes()
            width = sound.getsampwidth()
            if sound.getcomptype() != "NONE" or not 1 <= channels <= 2 or width not in (1, 2, 3, 4):
                raise ValueError
            if len(sound.readframes(frames)) != frames * channels * width:
                raise ValueError
            length = frames / rate
    elif extension == ".mp3":
        from mutagen.mp3 import MP3

        if not (raw.startswith(b"ID3") or (raw[0] == 255 and raw[1] & 224 == 224)):
            raise ValueError
        info = MP3(io.BytesIO(raw)).info
        if info.sketchy or info.layer != 3:
            raise ValueError
        channels, rate, length = info.channels, info.sample_rate, info.length
    else:
        from mutagen.mp4 import MP4

        atoms = _atoms(raw)
        if not atoms or atoms[0][0] != b"ftyp" or not any(a[0] == b"mdat" for a in atoms):
            raise ValueError
        moovs = [a for a in atoms if a[0] == b"moov"]
        if len(moovs) != 1:
            raise ValueError
        tracks = [a for a in _atoms(raw, moovs[0][1], moovs[0][2], 1) if a[0] == b"trak"]
        if len(tracks) != 1:
            raise ValueError
        media = [a for a in _atoms(raw, tracks[0][1], tracks[0][2], 2) if a[0] == b"mdia"]
        handlers = [a for a in _atoms(raw, media[0][1], media[0][2], 3) if a[0] == b"hdlr"]
        if (
            len(media) != 1
            or len(handlers) != 1
            or raw[handlers[0][1] + 8 : handlers[0][1] + 12] != b"soun"
        ):
            raise ValueError

        # ISO BMFF external data references are disallowed: only self-contained data.
        def inspect_atoms(start, end, depth=0):
            for name, body, finish in _atoms(raw, start, end, depth):
                if name in {b"moov", b"trak", b"mdia", b"minf", b"dinf", b"stbl"}:
                    inspect_atoms(body, finish, depth + 1)
                elif name == b"dref":
                    if finish - body < 8:
                        raise ValueError
                    entries = _atoms(raw, body + 8, finish, depth + 1)
                    if len(entries) != struct.unpack_from(">I", raw, body + 4)[0]:
                        raise ValueError
                    for entry, data, stop in entries:
                        if (
                            entry != b"url "
                            or stop - data != 4
                            or raw[data:stop] != b"\x00\x00\x00\x01"
                        ):
                            raise ValueError

        inspect_atoms(0, len(raw))
        info = MP4(io.BytesIO(raw)).info
        if not info.codec.startswith("mp4a"):
            raise ValueError
        channels, rate, length = info.channels, info.sample_rate, info.length
    if not 1 <= channels <= 2 or not 8000 <= rate <= 96000 or not 0 < length <= MAX_DURATION:
        raise ValueError
    return {"channels": channels, "sample_rate": rate, "duration_seconds": round(length, 6)}


def parse(raw, extension):
    if extension == ".txt":
        text = raw.decode("utf-8")
        if not text.strip() or any(
            (ord(c) < 32 and c not in "\r\n\t") or ord(c) == 127 for c in text
        ):
            raise ValueError
        return {"encoding": "UTF-8"}
    if extension == ".pdf":
        return _pdf(raw)
    if extension in {".jpg", ".jpeg", ".png", ".webp"}:
        return _image(raw, extension)
    return _audio(raw, extension)


def main():
    try:
        # POSIX CPU/address-space caps supplement the parent wall-clock timeout.
        try:
            import resource

            resource.setrlimit(resource.RLIMIT_CPU, (3, 3))
            resource.setrlimit(resource.RLIMIT_AS, (256 * 1024 * 1024, 256 * 1024 * 1024))
        except ImportError:
            pass
        data = json.loads(sys.stdin.read(300000))
        raw = base64.b64decode(data["raw"], validate=True)
        if not 1 <= len(raw) <= 192000:
            raise ValueError
        result = parse(raw, data["extension"])
        print(json.dumps({"validated": True, **result}))
        return 0
    except Exception:
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
