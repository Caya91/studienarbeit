from pathlib import Path
from datetime import datetime
import shutil
import numpy as np  # type: ignore

BASE_DIR = Path(__file__).resolve().parent.parent  # repo root: adjust if needed
LOG_DIR = BASE_DIR / "logs"
LOG_DIR.mkdir(exist_ok=True, parents=True)

def get_run_log_dir(script_name: str, **run_params) -> Path:
    """logs/<script_name>/<timestamp>_<params>/"""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    suffix = "_".join(f"{k}{v}" for k, v in run_params.items() if v != "")
    run_id = f"{timestamp}_{suffix}" if suffix else timestamp
    run_dir = LOG_DIR / script_name / run_id
    run_dir.mkdir(exist_ok=True, parents=True)
    return run_dir

def get_field_subdir(run_dir: Path, field: str) -> Path:
    """<run_dir>/<field>/, e.g. bin4 or bin8"""
    field_dir = run_dir / field
    field_dir.mkdir(exist_ok=True, parents=True)
    return field_dir

def clear_logs() -> None:
    """Delete entire logs dir (keep top-level logs)."""
    if LOG_DIR.exists():
        for child in LOG_DIR.iterdir():
            if child.is_dir():
                shutil.rmtree(child)
            else:
                child.unlink()

def save_array(path: Path, array) -> None:
    """Save a numpy-like array to .npy."""
    np.save(path, array)