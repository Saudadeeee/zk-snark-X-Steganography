from src.core.stego import CAVLCSafetyFilter


def test_bit_length_safety_uses_cavlc_max_num_coeff_from_bitstream():
    source = [9, -9, -9, -2, -11, -9, -7, 10, 19, -13, 18, -23, 19, -8, -9, 0]
    modified = list(source)
    modified[1] = -8

    is_safe, source_bits, modified_bits = CAVLCSafetyFilter()._verify_block_bit_length_invariance(
        source,
        modified,
        nC=15,
        nal_bit_length=102,
        max_num_coeff=15,
    )

    assert source_bits == 102
    assert modified_bits == 101
    assert is_safe is False
