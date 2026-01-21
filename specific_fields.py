from icecream import ic
import sys


def file_output(text):
    with open('debug.log', 'a') as f:
        f.write(text + '\n')

ic.configureOutput(outputFunction=file_output, includeContext=True)


def all_square_fields(field_size):
    ic.disable()


    ic("field size", field_size)
    elements = set()
    elements.update(range(field_size))

    square_elements = set()
    squared_e = 0
    for e in range(field_size):
        # ic(e, field_size)
        squared_e = ic((ic(e) ** 2) % ic(field_size))  
        square_elements.add(squared_e)



    ic.enable()


    if ic(elements) == ic(square_elements):
        ic("for field", field_size, "it works")
        return (field_size)
    else:
        ic(elements, "is unequal to", square_elements)
        return None




if __name__ == "__main__":
    '''
    all_square_fields(2)
    all_square_fields(3)
    all_square_fields(4)
    '''

    desired_field_size = set()
    for element in range(256):
        
        desired_field_size.add(all_square_fields(element))
        
    ic.disable()

    ic(desired_field_size)
    print(desired_field_size)
