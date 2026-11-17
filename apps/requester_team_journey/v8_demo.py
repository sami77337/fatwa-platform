"""Explicit opt-in local V8 demo; inherits the fresh synthetic database guard."""

from .v7_demo import main

if __name__ == "__main__":
    main(multipart=True)
