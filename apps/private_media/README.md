# Bounded private media primitives

`validation.validate(raw, filename, media_type)` returns a frozen `ValidatedMedia`
with exact original bytes, filename, canonical MIME, SHA-256, size, kind and
parser metadata. Failure raises `MediaValidationError` with a fixed safe code.
No content is rewritten. No authority, case, answer, publication or delivery is
created here. Callers retain their separate domain bindings and authorize reads.

Supported fabricated files: UTF-8 text ≤65536 bytes; PDF/JPEG/PNG/WebP/MP3/M4A/WAV
≤192000 bytes. The surrounding existing request guard remains 256KiB.

Validation runs in a Python worker process: six-second wall timeout, POSIX
three-second CPU and 256MiB address-space limits. Pillow 13.0.0 verifies and loads
single-frame images ≤4 million pixels. pypdf 7.1.0 parses strict PDFs ≤10 pages,
bounded graph depth/count and decoded streams; encrypted documents, actions,
external links, forms, scripts, embedded files and active media are rejected.
mutagen 1.48.1 parses MP3/M4A metadata; M4A atoms must bound one audio-only track,
with AAC codec. WAV uses `wave` with complete PCM-frame count and RIFF length.
Audio is limited to stereo, 8–96kHz and 120 seconds. This is structural admission,
**not malware scanning, a safety certification or full audio decoding**.

`storage.PrivateStorage.put/get` is a configurable private adapter contract. The
shipped `InlineDatabaseStorage` packages bytes for the caller's immutable ORM row;
`verify_original` rechecks digest/size. The default has no credentials/network or
public URL. An optional `FATWA_PRIVATE_MEDIA_STORAGE` server object must implement
the typed interface. Current attachment schema accepts inline storage only and
rejects external pointer records pending an explicit schema migration. Thus this
is an object-storage integration seam, not a claim that D-031 object storage has
been deployed. Answer media may retain exact bytes in its own immutable model.

`fixtures.synthetic_files()` produces all eight test formats. Images are 16×12
solid color, PDF is one blank page, WAV is silence, and committed MP3/M4A fixtures
are a 0.2-second generated 440Hz sine. Generated using installed ffmpeg 7.1.5:

```sh
ffmpeg -f lavfi -i sine=frequency=440:duration=0.2 -ar 22050 -ac 1 -codec:a libmp3lame -b:a 32k synthetic.mp3
ffmpeg -f lavfi -i sine=frequency=440:duration=0.2 -ar 22050 -ac 1 -codec:a aac -b:a 32k -movflags +faststart synthetic.m4a
```

ffmpeg is not a runtime dependency. Python package versions were verified from
the publishers' PyPI metadata; pins are integrated by the campaign parent.
No production configuration, external sending or AI ruling is included.
NOT_DEPLOYED / GATES_HOLD / ACCEPTANCE_HOLD.
