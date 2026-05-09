from dataclasses import dataclass

@dataclass
class Packet:
    coeffs:  bytearray   # coding vector, length = gen_size
    segment: bytearray   # data payload for this segment

    def __len__(self):
        return len(self.coeffs) + len(self.segment)

    def to_flat(self) -> bytearray:
        """Serialize back to flat bytearray format if needed."""
        return bytearray(self.coeffs + self.segment)

    @staticmethod
    def from_flat(flat: bytearray, gen_size: int) -> 'Packet':
        """Reconstruct from existing flat bytearray format."""
        return Packet(
            coeffs  = bytearray(flat[:gen_size]),
            segment = bytearray(flat[gen_size:])
        )
    
'''
for packets with multiple segments:,
@dataclass
class Packet_segments:
    coeffs:   bytearray        # coding vector
    segments: list[bytearray]  # one entry per segment slot



'''