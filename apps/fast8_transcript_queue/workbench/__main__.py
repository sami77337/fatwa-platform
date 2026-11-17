"""python -m apps.fast8_transcript_queue.workbench --port 8016"""

import argparse
import os
import secrets


def main():
    parser = argparse.ArgumentParser(description="Local synthetic transcript workbench")
    parser.add_argument("--port", type=int, default=8016)
    args = parser.parse_args()
    if os.environ.get("FATWA_PRODUCTION") != "0":
        parser.error("set FATWA_PRODUCTION=0 explicitly; synthetic data only")
    if not 1024 <= args.port <= 65535:
        parser.error("port must be between 1024 and 65535")
    os.environ["FATWA_TRANSCRIPT_SECRET"] = secrets.token_urlsafe(48)
    os.environ["FATWA_TRANSCRIPT_WORKBENCH"] = "1"
    os.environ["DJANGO_SETTINGS_MODULE"] = "apps.fast8_transcript_queue.workbench.settings"
    import django
    from django.core.management import call_command

    django.setup()
    print(f"Synthetic transcript review: http://127.0.0.1:{args.port}/transcripts/")
    call_command("runserver", f"127.0.0.1:{args.port}", use_reloader=False)


if __name__ == "__main__":
    main()
