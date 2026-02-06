from binary_2pow4.orthogonal_tag_creator import OrthogonalTagGenerator as OTG_bin4
from binary_2pow4.config import field as field_bin4

from binary_2pow4.generate_symbols import generate_symbols_random_bin4, check_orth_bin4, LOG_FILE

from binary_ext_fields.log_utils import clear_logs
import pyerasure.finite_field
from binary_2pow8.orthogonal_tag_creator import OrthogonalTagGenerator as OTG_bin8
from binary_2pow8.config import field as field_bin8

from binary_2pow8.generate_symbols import generate_symbols_random_bin8, check_orth_bin8, LOG_FILE



from icecream import ic
import statistics

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

def monte_carlo_test(num_trials, data_fields, gen_size):
    accepts_bin4 = []
    accepts_bin8 = []


    tag_gen_bin4 = OTG_bin4(field_bin4)
    tag_gen_bin8 = OTG_bin8(field_bin8)

    ic(num_trials, data_fields, gen_size)
    open(LOG_FILE, "w").close()

    for trial in range(num_trials):
        generation1 = generate_symbols_random_bin4(data_fields,gen_size)
        tagged_gen1 = tag_gen_bin4.generate_all_tags(generation1)

        generation2 = generate_symbols_random_bin8(data_fields,gen_size)
        tagged_gen2 = tag_gen_bin8.generate_all_tags(generation1)
        
        accepts_bin4.append(check_orth_bin4(tagged_gen1))
        accepts_bin8.append(check_orth_bin8(tagged_gen2))


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



    ic.disable()
    print(f"Acceptance probability Bin4: {prob1:.6f} ± {std1:.6f} over {num_trials} trials")

    print(f"Acceptance probability Bin8: {prob1:.6f} ± {std1:.6f} over {num_trials} trials")

    return prob1, std1, prob2, std2


if __name__ == "__main__":
    clear_logs()
    ic(monte_carlo_test(10000, 3,8))