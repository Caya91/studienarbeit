"""Receiver-secret choice of WHICH checks a packet faces (S2, 2026-09-29).

Both arms can cap verification work: the keyless receiver cross-checks a packet against
only `verify_count` trusted witnesses, the keyed receiver verifies only `mac_verify_count`
of the g MAC tags. The security of that cap depends on whether an attacker can predict
the checked subset:

  "first"  -- deterministic (first core members by arrival / first keys). An attacker who
              knows the arrival order or which keys leaked knows exactly what it faces.
  "random" -- per checked packet, the subset with the lowest `secret_rank`, a keyed hash of
              (receiver secret, checked packet index, candidate index). Unpredictable without
              the secret, stable across admit calls (the same packet keeps the same subset,
              so re-running admit does not hand a forger fresh lottery tickets).
"""
import hashlib

WITNESS_POLICIES = ("first", "random")


def secret_rank(secret: int, domain: str):
    """rank(a, c) -> int: a pseudo-random order of candidates c for checked packet a,
    fixed by `secret`. `domain` separates independent uses (witnesses vs MAC keys)."""
    prefix = f"{secret}/{domain}/".encode()

    def rank(a: int, c: int) -> int:
        return int.from_bytes(hashlib.blake2b(prefix + f"{a}/{c}".encode(), digest_size=8).digest(), "big")

    return rank


def witness_rank_for(policy: str, secret: int):
    """classify_segment_trust's witness_rank for a policy (None = deterministic "first")."""
    assert policy in WITNESS_POLICIES, f"unknown witness policy {policy!r}"
    return None if policy == "first" else secret_rank(secret, "witness")


def key_rank_for(policy: str, secret: int):
    """classify_segment_trust_mac's key_rank for a policy (None = deterministic first keys)."""
    assert policy in WITNESS_POLICIES, f"unknown witness policy {policy!r}"
    return None if policy == "first" else secret_rank(secret, "mac_key")
