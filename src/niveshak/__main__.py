"""Enable `python -m niveshak ...` (mirrors the installed `niveshak` console script)."""

from niveshak.cli import app

if __name__ == "__main__":
    app()
