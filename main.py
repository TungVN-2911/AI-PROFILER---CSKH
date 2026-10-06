"""Entry point: python main.py --url "https://www.facebook.com/<username>"."""

import sys

from app.cli import run

if __name__ == "__main__":
    sys.exit(run())
