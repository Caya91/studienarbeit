from binary_2pow4.orthogonal_tag_creator import OrthogonalTagGenerator
from binary_2pow4.config import field

from binary_2pow4.generate_symbols import generate_symbols_random_bin4, check_orth_bin4, LOG_FILE

from binary_2pow4.log_utils import clear_logs

from icecream import ic
import statistics



def monte_carlo_test(num_trials, data_fields, gen_size):
    accepts = []

    tag_gen = OrthogonalTagGenerator(field)


    ic(num_trials, data_fields, gen_size)
    open(LOG_FILE, "w").close()
    for trial in range(num_trials):
        generation = generate_symbols_random_bin4(data_fields,gen_size)
        tagged_gen = tag_gen.generate_all_tags(generation)

        # clear logfile
        
        accepts.append(check_orth_bin4(tagged_gen))

    ic.enable()
    prob = statistics.mean(accepts)
    std = statistics.stdev(accepts) / (num_trials ** 0.5) if len(accepts) > 1 else 0

    total_accepted = accepts.count(1)
    ic(total_accepted)
    #ic(accepts)
    ic(prob,std, 1-prob)

    ic.disable()
    print(f"Acceptance probability: {prob:.6f} ± {std:.6f} over {num_trials} trials")

    return prob, std


if __name__ == "__main__":
    clear_logs()
    ic(monte_carlo_test(10000, 3,8))