from pathlib import Path
from datetime import datetime
import pickle

BASE_DIR = Path(__file__).resolve().parent.parent  # Repo root
LOG_DIR = BASE_DIR / "logs"
LOG_DIR.mkdir(exist_ok=True, parents=True)

def get_run_log_dir(script_name: str, **run_params) -> Path:
    """Returns unique run dir: logs/<script>/<timestamp>_<params>/"""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    run_id = f"{timestamp}_{'_'.join(f'{k}{v}' for k, v in run_params.items() if v)}"
    
    run_dir = LOG_DIR / script_name / run_id
    run_dir.mkdir(exist_ok=True, parents=True)
    return run_dir

def get_field_subdir(run_dir: Path, field: str) -> Path:
    """Field subdir: <run_dir>/<field>/"""
    field_dir = run_dir / field
    field_dir.mkdir(exist_ok=True, parents=True)
    return field_dir

def clear_run_logs(run_dir: Path) -> None:
    """Delete files/subdirs in run dir (keep structure)."""
    for item in run_dir.iterdir():
        if item.is_file():
            item.unlink()
        elif item.is_dir():
            for subitem in item.iterdir():
                subitem.unlink()  # Files in field dirs
            item.rmdir()  # Empty field dirs


def save_generation_txt(path: Path, generation: list[bytearray], 
                       trial_id: int, label: str = "generation", max_symbols: int = 20) -> None:
    """APPEND one trial to SINGLE text file per field."""
    with path.open("a", encoding="utf-8") as f:  # "a" = append!
        f.write(f"\n=== {label.upper()} TRIAL {trial_id} ===\n")
        f.write(f"# {len(generation)} bytearrays\n")
        for i, ba in enumerate(generation):
            hex_dump = " ".join(f"{b:02x}" for b in ba[:max_symbols])
            f.write(f"ba[{i}]: len={len(ba)}, data={hex_dump}")
            if len(ba) > max_symbols:
                f.write(f" ... [{len(ba)-max_symbols} more]")
            f.write("\n")

