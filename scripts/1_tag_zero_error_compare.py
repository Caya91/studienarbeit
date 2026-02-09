from binary_2pow4.orthogonal_tag_creator import OrthogonalTagGenerator as OTG_bin4
from binary_2pow4.config import field as field_bin4

from binary_2pow4.generate_symbols import generate_symbols_random_bin4, check_orth_bin4, LOG_FILE

from binary_ext_fields.log_utils import clear_logs

from utils.logging import get_run_log_dir, get_field_subdir, save_generation_txt
import pyerasure.finite_field
from binary_2pow8.orthogonal_tag_creator import OrthogonalTagGenerator as OTG_bin8
from binary_2pow8.config import field as field_bin8

from binary_2pow8.generate_symbols import generate_symbols_random_bin8, check_orth_bin8, LOG_FILE

import pathlib
from pathlib import Path

from icecream import ic
import statistics


def monte_carlo_test(num_trials, data_fields, gen_size):
    accepts_bin4 = []
    accepts_bin8 = []


    tag_gen_bin4 = OTG_bin4(field_bin4)
    tag_gen_bin8 = OTG_bin8(field_bin8)

    ic(num_trials, data_fields, gen_size)

    logs_dir = pathlib.Path("logs")
    logs_dir.mkdir(exist_ok=True)



    script_name = Path(__file__).stem
    run_dir = get_run_log_dir(
        script_name,
        trials=num_trials,
        data_fields=data_fields,
        gen_size=gen_size,
    )
    bin4_dir = get_field_subdir(run_dir, "bin4")
    bin8_dir = get_field_subdir(run_dir, "bin8")

    bin4_gen_txt = bin4_dir / "all_generations.txt"
    bin4_tagged_txt = bin4_dir / "all_tagged_generations.txt"
    bin8_gen_txt = bin8_dir / "all_generations.txt"
    bin8_tagged_txt = bin8_dir / "all_tagged_generations.txt"

    for txt_file in [bin4_gen_txt, bin4_tagged_txt, bin8_gen_txt, bin8_tagged_txt]:
        txt_file.write_text(f"# ALL TRIALS for {txt_file.name}\n")


    for trial in range(num_trials):
        if trial % 1000 == 0: print("progess loop counter:", trial)
        generation1 = generate_symbols_random_bin4(data_fields,gen_size)
        tagged_gen1 = tag_gen_bin4.generate_all_tags(generation1)

        generation2 = generate_symbols_random_bin8(data_fields,gen_size)
        tagged_gen2 = tag_gen_bin8.generate_all_tags(generation2)
        
        bin4_failures_file = bin4_dir / "orth_failures.log"
        accepts_bin4.append(check_orth_bin4(tagged_gen1, log_dir=bin4_failures_file))

        bin8_failures_file = bin8_dir / "orth_failures.log"
        accepts_bin8.append(check_orth_bin8(tagged_gen2, log_dir=bin8_failures_file))

        bin8_failures_file = bin8_dir / "orth_failures.log"
        accepts_bin8.append(check_orth_bin8(tagged_gen2, log_dir=bin8_failures_file))

        save_generation_txt(bin4_gen_txt, generation1, trial, label="generation")
        save_generation_txt(bin4_tagged_txt, tagged_gen1, trial, label="tagged")
        
        save_generation_txt(bin8_gen_txt, generation2, trial, label="generation")
        save_generation_txt(bin8_tagged_txt, tagged_gen2, trial, label="tagged")



    ic.enable()
    prob1 = statistics.mean(accepts_bin4)
    std1 = statistics.stdev(accepts_bin4) / (num_trials ** 0.5) if len(accepts_bin4) > 1 else 0

    total_accepted_bin4 = accepts_bin4.count(1)
    ic(total_accepted_bin4)
    #ic(accepts)
    ic(prob1,std1, 1-prob1)

    prob2 = statistics.mean(accepts_bin8)
    std2 = statistics.stdev(accepts_bin8) / (num_trials ** 0.5) if len(accepts_bin8) > 1 else 0

    total_accepted_bin8 = accepts_bin8.count(1)
    ic(total_accepted_bin8)
    #ic(accepts)
    ic(prob2,std2, 1-prob2)

    #summaries
    with (bin4_dir / "summary.txt").open("w", encoding="utf-8") as f:
        f.write(f"Bin4: prob={prob1:.6f}, std={std1:.6f}, accepted={total_accepted_bin4}/{num_trials}\n")

    with (bin8_dir / "summary.txt").open("w", encoding="utf-8") as f:
        f.write(f"Bin8: prob={prob2:.6f}, std={std2:.6f}, accepted={total_accepted_bin8}/{num_trials}\n")


    print(f"Logs written to: {run_dir}")


    ic.disable()
    print(f"Acceptance probability Bin4: {prob1:.6f} ± {std1:.6f} over {num_trials} trials")

    print(f"Acceptance probability Bin8: {prob2:.6f} ± {std2:.6f} over {num_trials} trials")

    return prob1, std1, prob2, std2


if __name__ == "__main__":
    #clear_logs()
    ic(monte_carlo_test(10000, 4,12))

'''
def gen_bin(field:pyerasure.finite_field, data_fields:int, gen_size:int):

    match field:
        case pyerasure.finite_field.Binary4:
            generation = generate_symbols_random_bin4(data_fields,gen_size)
            tagged_gen = tag_gen.generate_all_tags(generation)
            print("Bin4")
            return generation
        case pyerasure.finite_field.Binary8:

            print("Bin8")
        


    return generation

'''
