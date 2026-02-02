import pathlib

BASE_DIR = pathlib.Path(__file__).resolve().parent
LOG_DIR = BASE_DIR / "logs"
LOG_DIR.mkdir(exist_ok=True)

def clear_logs() -> None:
    """Delete all files in the logs directory (keep the folder)."""
    for path in LOG_DIR.iterdir():
        if path.is_file():
            path.unlink()