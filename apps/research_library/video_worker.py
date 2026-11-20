"""Compatibility entry point for the shared bounded video decoder."""

import sys

from apps.private_media.video_worker import main

if __name__ == "__main__":
    try:
        main()
    except Exception:
        sys.exit(1)
