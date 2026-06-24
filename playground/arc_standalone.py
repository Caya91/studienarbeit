"""
Step 1 — Standalone ARC: compute and verify.

Run this file directly:
    python playground/arc_standalone.py

What to observe:
  - A clean packet passes the check.
  - Flipping any one data byte causes the check to fail.
  - The ARC value itself tells you nothing useful about *which* byte
    was flipped — it only tells you that something changed.
"""



import sys
import random
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from binary_ext_fields.custom_field import create_field
from binary_ext_fields.operations import inner_product_bytes


# ── Core ARC functions ────────────────────────────────────────────────────────

def compute_arc(field, data: bytearray, key: bytearray) -> int:
    """r = <data, key>  =  sum of data[i] * key[i]  in GF(2^m)"""
    assert len(data) == len(key), "data and key must be the same length"
    return inner_product_bytes(field, data, key)


def verify_arc(field, data: bytearray, key: bytearray, r: int) -> bool:
    """Recompute the inner product and compare to the stored check value r."""
    return compute_arc(field, data, key) == r


# ── Demo ──────────────────────────────────────────────────────────────────────

def main():
    field     = create_field(4)           # GF(2^4), values 0-15
    max_val   = field.max_value
    data_len  = 8

    # A fixed key (all-ones is fine for a demo; in practice this would be a
    # shared secret distributed out-of-band)
    key = bytearray([1] * data_len)

    print("=== Step 1: ARC compute & verify ===\n")
    print(f"Field: GF(2^4)  |  data length: {data_len}  |  key: {list(key)}\n")

    # ── 1a. Clean packet ──────────────────────────────────────────────────────
    data = bytearray(random.randint(0, max_val) for _ in range(data_len))
    r    = compute_arc(field, data, key)

    print(f"Original data : {list(data)}")
    print(f"ARC value     : {r}")
    ok = verify_arc(field, data, key, r)
    print(f"verify_arc()  : {ok}   <-- should be True\n")
    assert ok, "clean packet should pass"

    # ── 1b. Corrupt one byte ──────────────────────────────────────────────────
    corrupted = bytearray(data)           # copy
    flip_idx  = random.randrange(data_len)
    old_byte  = corrupted[flip_idx]
    # XOR with a non-zero value to guarantee a change
    corrupted[flip_idx] ^= random.randint(1, max_val)

    print(f"Corrupted data: {list(corrupted)}")
    print(f"  (byte[{flip_idx}] changed: {old_byte} -> {corrupted[flip_idx]})")
    ok_after = verify_arc(field, corrupted, key, r)
    print(f"verify_arc()  : {ok_after}   <-- should be False\n")
    assert not ok_after, "corrupted packet should fail"

    # ── 1c. Try all single-byte errors and count detections ──────────────────
    n_trials    = 1000
    n_detected  = 0
    for _ in range(n_trials):
        d = bytearray(random.randint(0, max_val) for _ in range(data_len))
        r = compute_arc(field, d, key)
        # flip a random byte by a random non-zero amount
        d2 = bytearray(d)
        i  = random.randrange(data_len)
        d2[i] = field.add(d2[i], random.randint(1, max_val))
        if not verify_arc(field, d2, key, r):
            n_detected += 1

    detection_rate = n_detected / n_trials
    ideal          = 1 - 1 / (max_val + 1)   # 1 - 1/16 = 0.9375
    print(f"Detection rate over {n_trials} random single-byte corruptions:")
    print(f"  measured : {detection_rate:.4f}")
    print(f"  ideal    : {ideal:.4f}  (= 1 - 1/|GF|)\n")

    print("Step 1 complete. Next: open arc_standalone.py and add Step 2")
    print("  (homomorphic property demo — ARC survives recoding)")


if __name__ == "__main__":
    main()
