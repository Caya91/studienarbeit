"""
Sniffing (ADR-0004): classify an accumulated packet pool into broken vs. trusted
packets before ARC/localization runs on any of them.

Two asymmetric signals:
- Self-check failure is conclusive proof of corruption.
- Self-check success is graded: trust grows with the number of other
  self-check-passing packets a packet is pairwise cross-orthogonal to.
"""

from icecream import ic

from binary_ext_fields.custom_field import TableField
from binary_ext_fields.generate_symbols import check_orth_packet
from binary_ext_fields.operations import inner_product_bytes


def sniff_pool(
    field: TableField,
    packet_pool: list[bytearray],
    min_trust_count: int = 4,
    min_pool_size: int = 10,
) -> tuple[list[int], list[int]]:
    """
    Returns (broken_indices, trusted_indices) into packet_pool.

    Self-check failure -> broken (conclusive).
    Self-check success + cross-check success count >= min_trust_count -> trusted.
    Packets that pass self-check but haven't hit the trust threshold are
    reported as neither broken nor trusted (still unknown).

    Only classifies once len(packet_pool) >= min_pool_size; otherwise the
    counts wouldn't be statistically meaningful (ADR-0004), so returns ([], []).
    """
    if len(packet_pool) < min_pool_size:
        return [], []

    self_pass = [i for i, p in enumerate(packet_pool) if check_orth_packet(field, p)]
    broken = [i for i in range(len(packet_pool)) if i not in self_pass]

    trust_count = {}
    for i in self_pass:
        count = 0
        for j in self_pass:
            if i == j:
                continue
            if inner_product_bytes(field, packet_pool[i], packet_pool[j]) == 0:
                count += 1
        trust_count[i] = count

    trusted = [i for i in self_pass if trust_count[i] >= min_trust_count]

    ic(broken, trusted, trust_count)

    return broken, trusted
