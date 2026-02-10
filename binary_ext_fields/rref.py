from binary_ext_fields.custom_field import TableField, PRIMES_GF2M, build_tables_gf2m





def packets_to_rref(packets: list[bytearray], field, gen_size: int) -> list[bytearray]:
    """Convert tagged packets to RREF over GF(2^m). """
    
    # PSEUDOCODE
    '''

    only reduce form for the packet coefficients columns of the matrix

    generate_matrix
    for r in row:
        find pivot elements
        swap rows
    until row reduced echelon form is reached:
        use gaussian elimination
        create pivot elements
        swap rows
    
    return row reduced echelon form
    
    '''
    
    pass