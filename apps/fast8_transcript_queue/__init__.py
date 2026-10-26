"""Synthetic transcript-origin intake, process-local and read-only."""

from .services import TranscriptQueue, build_transcript_queue

__all__ = ["TranscriptQueue", "build_transcript_queue"]
