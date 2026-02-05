import pathlib
from typing import Sequence

from binary_2pow8.operations_bin8 import inner_product_bytes_bin8
from pyerasure.finite_field import Binary4

BASE_DIR = pathlib.Path(__file__).resolve().parent
LOG_DIR = BASE_DIR / "logs"
LOG_DIR.mkdir(exist_ok=True)

LOG_FILE = LOG_DIR / "debug_inner_products.log"

def log_packet(label: str, packet: Sequence[int], f) -> None:
    f.write(f"{label} (len={len(packet)}): {list(packet)}\n")

def log_inner_product_detail(
    field,
    p1: bytes | bytearray,
    p2: bytes | bytearray,
    label1: str = "P1",
    label2: str = "P2",
    log_file: pathlib.Path = LOG_FILE,
) -> None:
    assert len(p1) == len(p2), "Packets must have same length"

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

        final = inner_product_bytes_bin8(p1, p2)
        f.write(f"Final inner_product_bytes = {final}\n\n")


def log_generation_detail(
    generation: list[bytearray],
    log_only_nonzero: bool = True,
    log_file: pathlib.Path = LOG_FILE,
) -> None:
    field = Binary4()

    with log_file.open("a", encoding="utf-8") as f:
        f.write("========================================\n")
        f.write("Detailed generation inspection\n")
        for idx, pkt in enumerate(generation):
            f.write(f"Packet[{idx}]: {list(pkt)}\n")
        f.write("\n")

    # For each pair (i, j), call the detailed logger
    for i, p1 in enumerate(generation):
        for j, p2 in enumerate(generation):
            prod = inner_product_bytes_bin8(p1, p2)
            if log_only_nonzero and prod == 0:
                continue
            # reuse the detailed function; it will append to same file
            log_inner_product_detail(field, p1, p2, label1=f"P[{i}]", label2=f"P[{j}]")
