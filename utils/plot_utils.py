"""
Reusable plotting utilities for error rate analysis.
Each function is well-commented to explain every step.
"""
import matplotlib.pyplot as plt
import numpy as np
from typing import Dict, Tuple
from pathlib import Path

from utils.log_helpers import get_playground_dir

def plot_error_rates_bar(
    field_results: Dict[str, Tuple[float, float]],
    output_path: Path = None,
    title: str = "Tag Zero Error Rates by Field Size"
):
    """
    Create a bar plot comparing error rates across different field sizes.
    
    Args:
        field_results: Dict mapping field names to (error_rate, std_dev)
                      e.g., {"GF(2^4)": (0.023, 0.001), "GF(2^8)": (0.045, 0.002)}
        output_path: Where to save the plot (if None, just display)
        title: Plot title
    
    Steps explained:
    1. Extract data from dictionary
    2. Create figure and axis
    3. Draw bars with error bars
    4. Customize appearance (labels, colors, grid)
    5. Add value labels on top of bars
    6. Save or display
    """
    # Step 1: Extract field names, error rates, and std devs
    field_names = list(field_results.keys())
    error_rates = [val[0] for val in field_results.values()]
    std_devs = [val[1] for val in field_results.values()]
    
    # Step 2: Create figure (8 inches wide, 6 inches tall)
    fig, ax = plt.subplots(figsize=(8, 6))
    
    # Step 3: Create bar positions (0, 1, 2, ...)
    x_pos = np.arange(len(field_names))
    
    # Step 4: Draw bars with error bars (std dev shown as thin black lines)
    bars = ax.bar(
        x_pos,                    # x positions
        error_rates,              # bar heights
        yerr=std_devs,           # error bars (±std_dev)
        capsize=5,               # horizontal caps on error bars
        color=['#3498db', '#e74c3c', '#2ecc71', '#f39c12'][:len(field_names)],  # nice colors
        edgecolor='black',       # black border around bars
        linewidth=1.5,           # border thickness
        alpha=0.8                # slight transparency
    )
    
    # Step 5: Customize x-axis
    ax.set_xticks(x_pos)
    ax.set_xticklabels(field_names, fontsize=12, fontweight='bold')
    
    # Step 6: Customize y-axis
    ax.set_ylabel('Error Rate (1 - Acceptance Probability)', fontsize=12, fontweight='bold')
    ax.set_ylim(0, max(error_rates) * 1.2)  # Add 20% space above highest bar
    
    # Step 7: Add title
    ax.set_title(title, fontsize=14, fontweight='bold', pad=20)
    
    # Step 8: Add grid (makes reading values easier)
    ax.yaxis.grid(True, linestyle='--', alpha=0.3)
    ax.set_axisbelow(True)  # Grid behind bars
    
    # Step 9: Add value labels on top of each bar
    for i, (bar, rate, std) in enumerate(zip(bars, error_rates, std_devs)):
        height = bar.get_height()
        # Place text slightly above the error bar
        ax.text(
            bar.get_x() + bar.get_width()/2.,  # x: center of bar
            height + std + 0.002,               # y: above error bar
            f'{rate:.4f}',                      # text: formatted rate
            ha='center',                        # horizontal alignment
            va='bottom',                        # vertical alignment
            fontsize=10,
            fontweight='bold'
        )
    
    # Step 10: Tight layout (prevents label cutoff)
    plt.tight_layout()
    
    # Step 11: Save or display
    if output_path:
        plt.savefig(output_path, dpi=300, bbox_inches='tight')
        print(f"✓ Plot saved to: {output_path}")
    
    #plt.show()
    return


def plot_acceptance_rates_comparison(
    field_results: Dict[str, Tuple[float, float, int, int]],
    output_path: Path = None
):
    """
    Side-by-side comparison: acceptance rate vs error rate.
    
    Args:
        field_results: Dict mapping to (accept_prob, std_dev, accepted_count, total_trials)
                      e.g., {"GF(2^4)": (0.977, 0.001, 9770, 10000)}
    
    Creates two subplots:
    - Left: Acceptance probability (closer to 1.0 = better)
    - Right: Error rate (closer to 0.0 = better)
    """
    field_names = list(field_results.keys())
    accept_probs = [val[0] for val in field_results.values()]
    std_devs = [val[1] for val in field_results.values()]
    error_rates = [1.0 - val[0] for val in field_results.values()]
    
    # Create figure with 2 subplots side by side
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(14, 6))
    
    x_pos = np.arange(len(field_names))
    colors = ['#3498db', '#e74c3c', '#2ecc71', '#f39c12'][:len(field_names)]
    
    # Left plot: Acceptance Probability
    bars1 = ax1.bar(x_pos, accept_probs, yerr=std_devs, capsize=5,
                    color=colors, edgecolor='black', linewidth=1.5, alpha=0.8)
    ax1.set_xticks(x_pos)
    ax1.set_xticklabels(field_names, fontsize=11, fontweight='bold')
    ax1.set_ylabel('Acceptance Probability', fontsize=12, fontweight='bold')
    ax1.set_title('Acceptance Rates', fontsize=13, fontweight='bold')
    ax1.yaxis.grid(True, linestyle='--', alpha=0.3)
    ax1.set_ylim(0 , 1.0)  # Start near lowest value
    
    # Add labels
    for bar, prob in zip(bars1, accept_probs):
        height = bar.get_height()
        ax1.text(bar.get_x() + bar.get_width()/2., height + 0.005,
                f'{prob:.4f}', ha='center', va='bottom', fontsize=9, fontweight='bold')
    
    # Right plot: Error Rate
    bars2 = ax2.bar(x_pos, error_rates, yerr=std_devs, capsize=5,
                    color=colors, edgecolor='black', linewidth=1.5, alpha=0.8)
    ax2.set_xticks(x_pos)
    ax2.set_xticklabels(field_names, fontsize=11, fontweight='bold')
    ax2.set_ylabel('Error Rate (1 - Acceptance)', fontsize=12, fontweight='bold')
    ax2.set_title('Error Rates', fontsize=13, fontweight='bold')
    ax2.yaxis.grid(True, linestyle='--', alpha=0.3)
    ax2.set_ylim(0, 1)
    
    # Add labels
    for bar, rate in zip(bars2, error_rates):
        height = bar.get_height()
        ax2.text(bar.get_x() + bar.get_width()/2., height + 0.001,
                f'{rate:.4f}', ha='center', va='bottom', fontsize=9, fontweight='bold')
    
    plt.tight_layout()
    
    if output_path:
        plt.savefig(output_path, dpi=300, bbox_inches='tight')
        print(f"✓ Comparison plot saved to: {output_path}")
    
    #plt.show()
    return

if __name__ == "__main__":
    '''
     Args:
        field_results: Dict mapping field names to (error_rate, std_dev)
                      e.g., {"GF(2^4)": (0.023, 0.001), "GF(2^8)": (0.045, 0.002)}
        output_path: Where to save the plot (if None, just display)
        title: Plot title
    '''

    dir_error = get_playground_dir("plots_error")
    dir_accept = get_playground_dir("plot_accept")
    dir_accept_2 = get_playground_dir("plot_accept_2")


    #file_dir = dir 
    print("test")
    error_rates = {"gf2m4": (0.5, 0.1), "gf2m8": (0.2, 0.01) }


    plot_error_rates_bar(error_rates,dir_error)


    #(accept_prob, std_dev, accepted_count, total_trials) e.g., {"GF(2^4)": (0.977, 0.001, 9770, 10000)
    accpeptence_prob = {"gf2m4": (0.5, 0.1, 8770, 10000), "gf2m8": (0.2, 0.01, 9770, 10000) }

    plot_acceptance_rates_comparison(accpeptence_prob, dir_accept )

    accpeptence_prob_2 = {"gf2m4": (0.5, 0.1, 8770, 10000), "gf2m8": (0.2, 0.01, 9770, 10000) 
                          ,"gf2m6": (0.1, 0.05, 9992, 10000) }

    plot_acceptance_rates_comparison(accpeptence_prob_2, dir_accept_2)
