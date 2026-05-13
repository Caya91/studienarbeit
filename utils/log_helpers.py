from pathlib import Path
from datetime import datetime
import pickle
from icecream import ic

from binary_ext_fields.custom_field import TableField, create_field
from binary_ext_fields.operations import inner_product_bytes

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


def get_playground_dir(playground_folder: str) -> Path:
    """"generate a folder in <root>/logs/*  to log palyground data"""
    return LOG_DIR / playground_folder


def to_byte_matrix(M):
    '''converts a matrix of ints to a bytearray for consistency'''
    return [bytearray(row) for row in M]


def to_int_matrx(M)-> list[list[int]]:
    '''converts the bytearray matrix to ints'''
    ic(M)
    new_matrix = []
    for row in M:
        new_row = []
        for e in row:
            new_row.append(int(e))
        new_matrix.append(new_row)
    return new_matrix


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

def print_table(field, table,  filename: str = None):
        """Print the add/mul table of a field as a formatted table.
        
        Args:
            filename: save to this text file .
        """
        maxv = field.max_value
        header = "   " + " ".join(f"{i:3}" for i in range(maxv + 1))
        lines = [header]
        
        for i in range(maxv + 1):
            row_str = f"{i:2} " + " ".join(f"{table[i][j]:3}" for j in range(maxv + 1))
            lines.append(row_str)
        
        if filename:
            with open(filename, 'w') as f:
                f.write("Multiplication Table (GF(2^m)):\n")
                f.write("\n".join(lines) + "\n")
            print(f"Table saved to {filename}")


def print_generation(
    generation: list[bytearray]    
) -> None:
    for idx, pkt in enumerate(generation):
        print(f'Packet[{idx}]: {list(pkt)}\n')


def log_packet(label: str, packet: list[bytearray], f) -> None:
    f.write(f"{label} (len={len(packet)}): {packet}\n")

def _interal_log_packet(label: str, packet: list[bytearray], log_file:Path) -> None:
    with log_file.open("a", encoding="utf-8") as f:
        f.write(f"{label} (len={len(packet)}): {packet}\n")


def write_to_file(text, log_file:Path = None):
    # append each ic() call as a new line
    if not log_file:
        log_file = LOG_DIR
    with open(log_file  / "ic.txt", "a", encoding="utf-8") as f:
        f.write(text + "\n")


def log_header(text, log_file_path):
    with open(log_file_path, 'a') as f:
        f.write(f"\n======== {text} ========\n")
    # Optional: also print to console if you want to see it live
    print(f"======== {text} ========")


def make_ic_logger(log_file:Path):
    def write_ic_file(text):
        with open(log_file , "a", encoding="utf-8") as f:
            f.write(text + "\n")
    return write_ic_file

def custom_format(obj):
    if isinstance(obj, (bytearray, bytes)):
        # Converts bytearray(b'\x07\x05\t\x01') into [7, 5, 9, 1]
        return str(list(obj))
    
    # Fallback to the default formatting for everything else
    return repr(obj)



def log_inner_product_detail(
    field: TableField,
    p1: bytes | bytearray,
    p2: bytes | bytearray,
    label1: str = "P1",
    label2: str = "P2",
    log_file: Path = None,
) -> None:
    assert len(p1) == len(p2), "Packets must have same length"

    if log_file == None:
        print(f"=== Detailed inner product ===")
        print(f"{label1} (len={len(p1)}): {p1}")
        print(f"{label2} (len={len(p2)}): {p2}")

        tmp = bytearray(1)
        acc = 0

        print("Index | a | b | a*b | acc")
        print("------+---+---+-----+-----")

        for idx, (a, b) in enumerate(zip(p1, p2)):
            tmp[0] = a
            field.vector_multiply_into(tmp, b)
            prod = tmp[0]
            acc = field.add(acc, prod)
            print(f"{idx:5d} | {a:2d} | {b:2d} | {prod:3d} | {acc:3d}")

        final = inner_product_bytes(field, p1, p2)
        print(f"Final inner_product_bytes = {final}\n")
    else:
        with log_file.open("a", encoding="utf-8") as f:
            f.write("=== Detailed inner product ===\n")
            log_packet(label1, p1, f)
            log_packet(label2, p2, f)

            tmp = bytearray(1)
            acc = 0

            f.write("Index | a | b | a*b | acc\n")
            f.write("------+---+---+-----+-----\n")

            for idx, (a, b) in enumerate(zip(p1, p2)):
                tmp[0] = a
                field.vector_multiply_into(tmp, b)
                prod = tmp[0]
                acc = field.add(acc, prod)
                f.write(f"{idx:5d} | {a:2d} | {b:2d} | {prod:3d} | {acc:3d}\n")

            final = inner_product_bytes(field, p1, p2)
            f.write(f"Final inner_product_bytes = {final}\n\n")


def log_generation_detail(
    generation: list[bytearray],
    field:TableField,
    log_file: Path = None,
    log_only_nonzero: bool = False,
) -> None:

    if log_file == None:
        print("========================================")
        print("Detailed generation inspection")
        for idx, pkt in enumerate(generation):
            print(f"Packet[{idx:>3}]: {list(pkt)}")
        print("\n")
    else:
        with log_file.open("a", encoding="utf-8") as f:
            f.write("========================================\n")
            f.write("Detailed generation inspection\n")
            for idx, pkt in enumerate(generation):
                f.write(f"Packet[{idx:>3}]: {list(pkt)}\n")
            f.write("\n")

    # For each pair (i, j), call the detailed logger
    for i, p1 in enumerate(generation):
        for j, p2 in enumerate(generation):
            prod = inner_product_bytes(field, p1, p2)
            if log_only_nonzero and prod == 0:
                continue
            # reuse the detailed function; it will append to same file
            log_inner_product_detail(field, p1, p2, label1=f"P[{i}]", label2=f"P[{j}]", log_file=log_file)