from binary_ext_fields.log_utils import clear_logs
from binary_ext_fields.orthogonal_tag_creator import OrthogonalTagGenerator as OTC_custom

from binary_ext_fields.custom_field import TableField, build_tables_gf2m, PRIMES_GF2M
from binary_ext_fields.generate_symbols import generate_symbols_random, check_orth, recode


from utils.log_helpers import get_run_log_dir, get_field_subdir, save_generation_txt, print_generation
from utils.plot_utils import plot_acceptance_rates_comparison, get_playground_dir

import pathlib
from pathlib import Path

from icecream import ic
import statistics
import random

fields = list(range(2,9))


def monte_carlo_recoding_test(num_trials, data_fields, gen_size, field:TableField):
    '''
    
    Returns:

    (prob, std, total_accepted, num_trials)
    '''

    
    accepts = []
    tag_gen = OTC_custom(field)


    logs_dir = pathlib.Path("logs")
    logs_dir.mkdir(exist_ok=True)


    script_name = Path(__file__).stem
    run_dir = get_run_log_dir(
        script_name,
        trials=num_trials,
        data_fields=data_fields,
        gen_size=gen_size,
    )
    bin_dir = get_field_subdir(run_dir, field.name)

    bin_gen_txt = bin_dir / "all_generations.txt"
    bin_tagged_txt = bin_dir / "all_tagged_generations.txt"

    for txt_file in [bin_gen_txt, bin_tagged_txt]:
        txt_file.write_text(f"# ALL TRIALS for {txt_file.name}\n")


    for trial in range(num_trials):
            if trial % 1000 == 0: print("progess loop counter:", trial)

            generation = generate_symbols_random(0,field.max_value,data_fields,gen_size)

            gen_w_coefficients = []
            for i, pkt in enumerate(generation):
                coefficients = bytearray(gen_size)
                coefficients[i] = 1
        
                gen_w_coefficients.append(coefficients.copy() + pkt.copy())



            tagged_gen = tag_gen.generate_all_tags(gen_w_coefficients)


            recoded_gen = recode(field, tagged_gen,len(tagged_gen))



            bin_failures_file = bin_dir / "orth_failures.log"
            accepts.append(check_orth(field, recoded_gen, log_dir=bin_failures_file))

            save_generation_txt(bin_gen_txt, generation, trial, label="generation")
            save_generation_txt(bin_tagged_txt, recoded_gen, trial, label="tagged")
            

    prob = statistics.mean(accepts)
    std = statistics.stdev(accepts) / (num_trials ** 0.5) if len(accepts) > 1 else 0

    total_accepted = accepts.count(1)


    return (prob, std, total_accepted, num_trials)

def recoding_test1():
    clear_logs()
    dir = get_playground_dir("recoding_pl.txt")

    accepts = False
    while not accepts:

        data_fields = 3
        gen_size = 5
        field = 5

        prime = PRIMES_GF2M.get(field)
        add_table, mul_table = build_tables_gf2m(field,prime)
        table_field = TableField(add_table, mul_table, prime)
        tag_gen = OTC_custom(table_field)

        generation = generate_symbols_random(0,table_field.max_value,data_fields,gen_size)

        # new matrix with Identity matrix in the front

        gen_w_coefficients = []
        generation_size = len(generation)

        coefficients = bytearray(generation_size)


        for i, pkt in enumerate(generation):
            coefficients = bytearray(generation_size)
            coefficients[i] = 1
    
            gen_w_coefficients.append(coefficients.copy() + pkt.copy())


        tagged_gen = tag_gen.generate_all_tags(gen_w_coefficients)

        accepts = (check_orth(table_field, tagged_gen, dir)) # loop until a generation doesnt have the 0 tag error

    # test recode function
    recoded_packets = recode(table_field, tagged_gen, 5)

    print_generation(recoded_packets)
    print_generation(tagged_gen)

    return check_orth(table_field, recoded_packets)


if __name__ == "__main__":

    print(recoding_test1())


 #clear_logs()
    #ic(monte_carlo_test(10000, 4,12))
    

    primes = []
    table_fields = []
    for f in fields:
        prime = PRIMES_GF2M.get(f)
        primes.append(prime)
        add_table, mul_table = build_tables_gf2m(f,prime)
        table_field = TableField(add_table, mul_table, prime)
        table_fields.append(table_field) 
        ic(bin(prime), table_field.max_value)

    ic(primes, table_fields)


    num_trials = 100
    data_fields = 7
    gen_size = 7


    tuples_for_plotting = {}
    for i, field in enumerate(table_fields):

        print(f"===== Field Nr. {i }  {field.name} ========")
        #ic( monte_carlo_single_field(num_trials, data_fields, gen_size, field))
        monte_carlo_result_tuple = monte_carlo_recoding_test(num_trials, data_fields, gen_size, field)
        '''
            Args:
        field_results: Dict mapping to (accept_prob, std_dev, accepted_count, total_trials)
                      e.g., {"GF(2^4)": (0.977, 0.001, 9770, 10000)}
        '''
        tuples_for_plotting.update({field.name: monte_carlo_result_tuple})
    
    #ic(tuples_for_plotting)
    plot_acceptance_rates_comparison(tuples_for_plotting,get_playground_dir("plots_error"))