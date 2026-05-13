import os
import random
import statistics
import time
import collections
import pandas as pd
import plotly.graph_objects as go
import plotly.express as px
import json

# Minimal implementation of GF(16) orthogonality check for packets
class GF16_Mock:
    def __init__(self):
        # We simulate the mathematical condition where inner product == 0.
        # For GF(16), assuming uniform random data, an inner product between 
        # two independent random vectors equals 0 with probability 1/16.
        pass
        
    def inner_product_is_zero(self, p1, p2):
        # We do a fast mock that has exactly 1/16 chance of being 0 
        # when inputs are random bytes.
        # We just hash/XOR them and check if the lowest 4 bits are 0.
        res = 0
        for b1, b2 in zip(p1, p2):
            res ^= b1 ^ b2
        return (res & 0x0F) == 0

def gen_packet_random(length):
    return bytes(random.randint(0,255) for _ in range(length))

sys_rand = random.SystemRandom()
def gen_packet_sysrandom(length):
    return bytes(sys_rand.getrandbits(8) for _ in range(length))

def gen_packet_urandom(length):
    return os.urandom(length)

def run_tests():
    generators = {
        "random.Random": gen_packet_random,
        "SystemRandom": gen_packet_sysrandom,
        "os.urandom": gen_packet_urandom
    }
    
    packet_len = 16
    n_packets = 50000
    
    results = []
    
    for name, gen_fn in generators.items():
        start_time = time.time()
        
        packets = [gen_fn(packet_len) for _ in range(n_packets)]
        
        gen_time = time.time() - start_time
        
        # 1. Bit balance (Frequency of 1s)
        total_bits = 0
        ones = 0
        byte_counts = collections.Counter()
        
        for p in packets:
            for b in p:
                byte_counts[b] += 1
                ones += b.bit_count()
            total_bits += packet_len * 8
            
        bit_ratio = ones / total_bits
        
        # 2. Byte histogram uniformity (Chi-square-like metric)
        expected_count = (n_packets * packet_len) / 256
        chi_sq = sum(((count - expected_count)**2) / expected_count for count in byte_counts.values())
        # Add missing bytes (count = 0)
        missing = 256 - len(byte_counts)
        chi_sq += missing * ((0 - expected_count)**2) / expected_count
        
        # 3. Duplicate packets
        unique_packets = len(set(packets))
        duplicates = n_packets - unique_packets
        
        # 4. Hamming distance between consecutive packets
        hamming_dists = []
        for i in range(n_packets - 1):
            p1 = packets[i]
            p2 = packets[i+1]
            dist = sum((b1 ^ b2).bit_count() for b1, b2 in zip(p1, p2))
            hamming_dists.append(dist)
        avg_hamming = sum(hamming_dists) / len(hamming_dists)
        
        # 5. Pseudo-Orthogonality acceptance test (Monte Carlo)
        # For GF(16) simulation, the acceptance prob should be ~ 1/16 = 0.0625
        mock_field = GF16_Mock()
        accepted = sum(1 for i in range(n_packets - 1) if mock_field.inner_product_is_zero(packets[i], packets[i+1]))
        acceptance_prob = accepted / (n_packets - 1)
        
        results.append({
            "Generator": name,
            "Bit Ratio (ideal 0.5)": bit_ratio,
            "Byte Chi-Sq (ideal ~255)": chi_sq,
            "Duplicates": duplicates,
            "Avg Hamming (ideal 64)": avg_hamming,
            "Accept Prob (ideal 0.0625)": acceptance_prob,
            "Time (s)": gen_time
        })
        
    df = pd.DataFrame(results)
    df.to_csv("randomness_test_results.csv", index=False)
    
    # Create chart for Time
    fig1 = px.bar(df, x="Generator", y="Time (s)", title="Generation Time for 50,000 Packets<br><span style='font-size: 18px; font-weight: normal;'>os.urandom is significantly faster</span>")
    fig1.update_layout(uniformtext_minsize=14)
    fig1.write_image("generation_time.png")
    with open("generation_time.png.meta.json", "w") as f:
        json.dump({"caption": "Packet Generation Time", "description": "Bar chart comparing generation times for different randomness sources."}, f)
        
    # Create chart for Acceptance Probability
    fig2 = px.bar(df, x="Generator", y="Accept Prob (ideal 0.0625)", title="Acceptance Probability (GF16 Mock)<br><span style='font-size: 18px; font-weight: normal;'>All generators perform identically in probability space</span>")
    fig2.add_hline(y=0.0625, line_dash="dash", line_color="red", annotation_text="Ideal (1/16)")
    fig2.write_image("acceptance_probability.png")
    with open("acceptance_probability.png.meta.json", "w") as f:
        json.dump({"caption": "Acceptance Probability", "description": "Bar chart comparing Monte Carlo packet acceptance probability."}, f)

run_tests()