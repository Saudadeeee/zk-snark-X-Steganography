#include "zkstego/cavlc_stream.hpp"

#include <array>

struct CoeffTokenCode {
    const char* bits;
    std::uint8_t total_coefficients;
    std::uint8_t trailing_ones;
};
constexpr std::array coeff_token_n4_7{
    CoeffTokenCode{"1111", 0, 0},
    CoeffTokenCode{"001111", 1, 0},
    CoeffTokenCode{"1110", 1, 1},
    CoeffTokenCode{"001011", 2, 0},
    CoeffTokenCode{"01111", 2, 1},
    CoeffTokenCode{"1101", 2, 2},
    CoeffTokenCode{"001000", 3, 0},
    CoeffTokenCode{"01100", 3, 1},
    CoeffTokenCode{"01110", 3, 2},
    CoeffTokenCode{"1100", 3, 3},
    CoeffTokenCode{"0001111", 4, 0},
    CoeffTokenCode{"01010", 4, 1},
    CoeffTokenCode{"01011", 4, 2},
    CoeffTokenCode{"1011", 4, 3},
    CoeffTokenCode{"0001011", 5, 0},
    CoeffTokenCode{"01000", 5, 1},
    CoeffTokenCode{"01001", 5, 2},
    CoeffTokenCode{"1010", 5, 3},
    CoeffTokenCode{"0001001", 6, 0},
    CoeffTokenCode{"001110", 6, 1},
    CoeffTokenCode{"001101", 6, 2},
    CoeffTokenCode{"1001", 6, 3},
    CoeffTokenCode{"0001000", 7, 0},
    CoeffTokenCode{"001010", 7, 1},
    CoeffTokenCode{"001001", 7, 2},
    CoeffTokenCode{"1000", 7, 3},
    CoeffTokenCode{"00001111", 8, 0},
    CoeffTokenCode{"0001110", 8, 1},
    CoeffTokenCode{"0001101", 8, 2},
    CoeffTokenCode{"01101", 8, 3},
    CoeffTokenCode{"00001011", 9, 0},
    CoeffTokenCode{"00001110", 9, 1},
    CoeffTokenCode{"0001010", 9, 2},
    CoeffTokenCode{"001100", 9, 3},
    CoeffTokenCode{"000001111", 10, 0},
    CoeffTokenCode{"00001010", 10, 1},
    CoeffTokenCode{"00001101", 10, 2},
    CoeffTokenCode{"0001100", 10, 3},
    CoeffTokenCode{"000001011", 11, 0},
    CoeffTokenCode{"000001110", 11, 1},
    CoeffTokenCode{"00001001", 11, 2},
    CoeffTokenCode{"00001100", 11, 3},
    CoeffTokenCode{"000001000", 12, 0},
    CoeffTokenCode{"000001010", 12, 1},
    CoeffTokenCode{"000001101", 12, 2},
    CoeffTokenCode{"00001000", 12, 3},
    CoeffTokenCode{"0000001101", 13, 0},
    CoeffTokenCode{"000000111", 13, 1},
    CoeffTokenCode{"000001001", 13, 2},
    CoeffTokenCode{"000001100", 13, 3},
    CoeffTokenCode{"0000001001", 14, 0},
    CoeffTokenCode{"0000001100", 14, 1},
    CoeffTokenCode{"0000001011", 14, 2},
    CoeffTokenCode{"0000001010", 14, 3},
    CoeffTokenCode{"0000000101", 15, 0},
    CoeffTokenCode{"0000001000", 15, 1},
    CoeffTokenCode{"0000000111", 15, 2},
    CoeffTokenCode{"0000000110", 15, 3},
    CoeffTokenCode{"0000000001", 16, 0},
    CoeffTokenCode{"0000000100", 16, 1},
    CoeffTokenCode{"0000000011", 16, 2},
    CoeffTokenCode{"0000000010", 16, 3},
};
#include <array>
#include <stdexcept>
#include <string>
#include <string_view>
#include <unordered_map>

namespace zkstego {

namespace {

std::size_t start_code_length_at(const std::vector<std::uint8_t>& bytes, std::size_t offset) {
    if (offset + 3 <= bytes.size() && bytes[offset] == 0 && bytes[offset + 1] == 0 && bytes[offset + 2] == 1) {
        return 3;
    }
    if (offset + 4 <= bytes.size() && bytes[offset] == 0 && bytes[offset + 1] == 0 &&
        bytes[offset + 2] == 0 && bytes[offset + 3] == 1) {
        return 4;
    }
    return 0;
}

constexpr std::array coeff_token_n0_1{
    CoeffTokenCode{"1", 0, 0}, CoeffTokenCode{"000101", 1, 0}, CoeffTokenCode{"01", 1, 1},
    CoeffTokenCode{"00000111", 2, 0}, CoeffTokenCode{"000100", 2, 1}, CoeffTokenCode{"0011", 2, 2},
    CoeffTokenCode{"000000111", 3, 0}, CoeffTokenCode{"00000110", 3, 1}, CoeffTokenCode{"0000101", 3, 2}, CoeffTokenCode{"00011", 3, 3},
    CoeffTokenCode{"0000000111", 4, 0}, CoeffTokenCode{"000000110", 4, 1}, CoeffTokenCode{"00000101", 4, 2}, CoeffTokenCode{"000011", 4, 3},
    CoeffTokenCode{"00000000111", 5, 0}, CoeffTokenCode{"0000000110", 5, 1}, CoeffTokenCode{"000000101", 5, 2}, CoeffTokenCode{"0000100", 5, 3},
    CoeffTokenCode{"0000000001111", 6, 0}, CoeffTokenCode{"00000000110", 6, 1}, CoeffTokenCode{"0000000101", 6, 2}, CoeffTokenCode{"00000100", 6, 3},
    CoeffTokenCode{"0000000001011", 7, 0}, CoeffTokenCode{"0000000001110", 7, 1}, CoeffTokenCode{"00000000101", 7, 2}, CoeffTokenCode{"000000100", 7, 3},
    CoeffTokenCode{"0000000001000", 8, 0}, CoeffTokenCode{"0000000001010", 8, 1}, CoeffTokenCode{"0000000001101", 8, 2}, CoeffTokenCode{"0000000100", 8, 3},
    CoeffTokenCode{"00000000001111", 9, 0}, CoeffTokenCode{"00000000001110", 9, 1}, CoeffTokenCode{"0000000001001", 9, 2}, CoeffTokenCode{"00000000100", 9, 3},
    CoeffTokenCode{"00000000001011", 10, 0}, CoeffTokenCode{"00000000001010", 10, 1}, CoeffTokenCode{"00000000001101", 10, 2}, CoeffTokenCode{"0000000001100", 10, 3},
    CoeffTokenCode{"000000000001111", 11, 0}, CoeffTokenCode{"000000000001110", 11, 1}, CoeffTokenCode{"00000000001001", 11, 2}, CoeffTokenCode{"00000000001100", 11, 3},
    CoeffTokenCode{"000000000001011", 12, 0}, CoeffTokenCode{"000000000001010", 12, 1}, CoeffTokenCode{"000000000001101", 12, 2}, CoeffTokenCode{"00000000001000", 12, 3},
    CoeffTokenCode{"0000000000000111", 13, 0}, CoeffTokenCode{"0000000000001010", 13, 1}, CoeffTokenCode{"000000000001001", 13, 2}, CoeffTokenCode{"000000000001100", 13, 3},
    CoeffTokenCode{"0000000000000100", 14, 0}, CoeffTokenCode{"0000000000000110", 14, 1}, CoeffTokenCode{"0000000000000101", 14, 2}, CoeffTokenCode{"000000000001000", 14, 3},
    CoeffTokenCode{"0000000000001111", 15, 0}, CoeffTokenCode{"0000000000001110", 15, 1}, CoeffTokenCode{"0000000000001101", 15, 2}, CoeffTokenCode{"0000000000001100", 15, 3},
    CoeffTokenCode{"0000000000001011", 16, 0}, CoeffTokenCode{"0000000000001001", 16, 1}, CoeffTokenCode{"0000000000000011", 16, 2}, CoeffTokenCode{"0000000000001000", 16, 3},
};

constexpr std::array coeff_token_n2_3{
    CoeffTokenCode{"11", 0, 0}, CoeffTokenCode{"001011", 1, 0}, CoeffTokenCode{"10", 1, 1},
    CoeffTokenCode{"000111", 2, 0}, CoeffTokenCode{"00111", 2, 1}, CoeffTokenCode{"011", 2, 2},
    CoeffTokenCode{"0000111", 3, 0}, CoeffTokenCode{"001010", 3, 1}, CoeffTokenCode{"001001", 3, 2}, CoeffTokenCode{"0101", 3, 3},
    CoeffTokenCode{"00000111", 4, 0}, CoeffTokenCode{"000110", 4, 1}, CoeffTokenCode{"000101", 4, 2}, CoeffTokenCode{"0100", 4, 3},
    CoeffTokenCode{"00000100", 5, 0}, CoeffTokenCode{"0000110", 5, 1}, CoeffTokenCode{"0000101", 5, 2}, CoeffTokenCode{"00110", 5, 3},
    CoeffTokenCode{"000000111", 6, 0}, CoeffTokenCode{"00000110", 6, 1}, CoeffTokenCode{"00000101", 6, 2}, CoeffTokenCode{"001000", 6, 3},
    CoeffTokenCode{"00000001111", 7, 0}, CoeffTokenCode{"000000110", 7, 1}, CoeffTokenCode{"000000101", 7, 2}, CoeffTokenCode{"000100", 7, 3},
    CoeffTokenCode{"00000001011", 8, 0}, CoeffTokenCode{"00000001110", 8, 1}, CoeffTokenCode{"00000001101", 8, 2}, CoeffTokenCode{"0000100", 8, 3},
    CoeffTokenCode{"000000001111", 9, 0}, CoeffTokenCode{"00000001010", 9, 1}, CoeffTokenCode{"00000001001", 9, 2}, CoeffTokenCode{"000000100", 9, 3},
    CoeffTokenCode{"000000001011", 10, 0}, CoeffTokenCode{"000000001110", 10, 1}, CoeffTokenCode{"000000001101", 10, 2}, CoeffTokenCode{"00000001100", 10, 3},
    CoeffTokenCode{"000000001000", 11, 0}, CoeffTokenCode{"000000001010", 11, 1}, CoeffTokenCode{"000000001001", 11, 2}, CoeffTokenCode{"00000001000", 11, 3},
    CoeffTokenCode{"0000000001111", 12, 0}, CoeffTokenCode{"0000000001110", 12, 1}, CoeffTokenCode{"0000000001101", 12, 2}, CoeffTokenCode{"000000001100", 12, 3},
    CoeffTokenCode{"0000000001011", 13, 0}, CoeffTokenCode{"0000000001010", 13, 1}, CoeffTokenCode{"0000000001001", 13, 2}, CoeffTokenCode{"0000000001100", 13, 3},
    CoeffTokenCode{"0000000000111", 14, 0}, CoeffTokenCode{"00000000001011", 14, 1}, CoeffTokenCode{"0000000000110", 14, 2}, CoeffTokenCode{"0000000001000", 14, 3},
    CoeffTokenCode{"00000000001001", 15, 0}, CoeffTokenCode{"00000000001000", 15, 1}, CoeffTokenCode{"00000000001010", 15, 2}, CoeffTokenCode{"0000000000001", 15, 3},
    CoeffTokenCode{"00000000000111", 16, 0}, CoeffTokenCode{"00000000000110", 16, 1}, CoeffTokenCode{"00000000000101", 16, 2}, CoeffTokenCode{"00000000000100", 16, 3},
};

constexpr std::array coeff_token_n4_5{
    CoeffTokenCode{"1111", 0, 0}, CoeffTokenCode{"1110", 1, 1}, CoeffTokenCode{"1101", 2, 2}, CoeffTokenCode{"1100", 3, 3}, CoeffTokenCode{"1011", 4, 3}, CoeffTokenCode{"1010", 5, 3}, CoeffTokenCode{"1001", 6, 3}, CoeffTokenCode{"1000", 7, 3},
    CoeffTokenCode{"01111", 2, 1}, CoeffTokenCode{"01100", 3, 1}, CoeffTokenCode{"01110", 3, 2}, CoeffTokenCode{"01010", 4, 1}, CoeffTokenCode{"01011", 4, 2}, CoeffTokenCode{"01000", 5, 1}, CoeffTokenCode{"01001", 5, 2}, CoeffTokenCode{"01101", 8, 3},
    CoeffTokenCode{"011111", 1, 0}, CoeffTokenCode{"011011", 2, 0}, CoeffTokenCode{"011000", 3, 0}, CoeffTokenCode{"011110", 6, 1}, CoeffTokenCode{"011101", 6, 2}, CoeffTokenCode{"011010", 7, 1}, CoeffTokenCode{"011001", 7, 2}, CoeffTokenCode{"011100", 9, 3},
    CoeffTokenCode{"0101111", 4, 0}, CoeffTokenCode{"0101011", 5, 0}, CoeffTokenCode{"0101001", 6, 0}, CoeffTokenCode{"0101000", 7, 0}, CoeffTokenCode{"0101110", 8, 1}, CoeffTokenCode{"0101101", 8, 2}, CoeffTokenCode{"0101010", 9, 2}, CoeffTokenCode{"0101100", 10, 3},
    CoeffTokenCode{"01001111", 8, 0}, CoeffTokenCode{"01001011", 9, 0}, CoeffTokenCode{"01001110", 9, 1}, CoeffTokenCode{"01001010", 10, 1}, CoeffTokenCode{"01001101", 10, 2}, CoeffTokenCode{"01001001", 11, 2}, CoeffTokenCode{"01001100", 11, 3}, CoeffTokenCode{"01001000", 12, 3},
    CoeffTokenCode{"010001111", 10, 0}, CoeffTokenCode{"010001011", 11, 0}, CoeffTokenCode{"010001110", 11, 1}, CoeffTokenCode{"010001000", 12, 0}, CoeffTokenCode{"010001010", 12, 1}, CoeffTokenCode{"010001101", 12, 2}, CoeffTokenCode{"010000111", 13, 1}, CoeffTokenCode{"010001001", 13, 2}, CoeffTokenCode{"010001100", 13, 3},
    CoeffTokenCode{"0100001101", 13, 0}, CoeffTokenCode{"0100001001", 14, 0}, CoeffTokenCode{"0100001100", 14, 1}, CoeffTokenCode{"0100001011", 14, 2}, CoeffTokenCode{"0100001010", 14, 3}, CoeffTokenCode{"0100000101", 15, 0}, CoeffTokenCode{"0100001000", 15, 1}, CoeffTokenCode{"0100000111", 15, 2}, CoeffTokenCode{"0100000110", 15, 3}, CoeffTokenCode{"0100000001", 16, 0}, CoeffTokenCode{"0100000100", 16, 1}, CoeffTokenCode{"0100000011", 16, 2}, CoeffTokenCode{"0100000010", 16, 3},
};

constexpr std::array coeff_token_chroma_dc{
    CoeffTokenCode{"1", 1, 1}, CoeffTokenCode{"01", 0, 0}, CoeffTokenCode{"001", 2, 2}, CoeffTokenCode{"000010", 4, 0},
    CoeffTokenCode{"000011", 3, 0}, CoeffTokenCode{"000100", 2, 0}, CoeffTokenCode{"000101", 3, 3}, CoeffTokenCode{"000110", 2, 1},
    CoeffTokenCode{"000111", 1, 0}, CoeffTokenCode{"0000000", 4, 3}, CoeffTokenCode{"0000010", 3, 2}, CoeffTokenCode{"0000011", 3, 1},
    CoeffTokenCode{"00000010", 4, 2}, CoeffTokenCode{"00000011", 4, 1},
};

}  // namespace

H264BaselineSps parse_baseline_sps(const std::vector<std::uint8_t>& rbsp) {
    RbspBitReader reader(rbsp);
    H264BaselineSps sps;
    sps.profile_idc = static_cast<std::uint8_t>(reader.read_bits(8));
    static_cast<void>(reader.read_bits(8));  // constraint flags and reserved bits
    sps.level_idc = static_cast<std::uint8_t>(reader.read_bits(8));
    sps.sequence_parameter_set_id = reader.read_ue();
    if (sps.profile_idc != 66 && sps.profile_idc != 77 && sps.profile_idc != 88) {
        throw std::invalid_argument("native SPS parser currently supports CAVLC baseline/main profiles only");
    }
    sps.log2_max_frame_num_minus4 = reader.read_ue();
    sps.pic_order_cnt_type = reader.read_ue();
    if (sps.pic_order_cnt_type == 0) {
        sps.log2_max_pic_order_cnt_lsb_minus4 = reader.read_ue();
    } else if (sps.pic_order_cnt_type == 1) {
        throw std::invalid_argument("native SPS parser does not yet support pic_order_cnt_type 1");
    } else if (sps.pic_order_cnt_type != 2) {
        throw std::invalid_argument("invalid SPS pic_order_cnt_type");
    }
    static_cast<void>(reader.read_ue());  // max_num_ref_frames
    static_cast<void>(reader.read_bit());  // gaps_in_frame_num_value_allowed_flag
    sps.pic_width_in_mbs_minus1 = reader.read_ue();
    sps.pic_height_in_map_units_minus1 = reader.read_ue();
    sps.frame_mbs_only_flag = reader.read_bit() != 0;
    return sps;
}

H264BaselinePps parse_baseline_pps(const std::vector<std::uint8_t>& rbsp) {
    RbspBitReader reader(rbsp);
    H264BaselinePps pps;
    pps.pic_parameter_set_id = reader.read_ue();
    pps.sequence_parameter_set_id = reader.read_ue();
    pps.entropy_coding_mode_flag = reader.read_bit() != 0;
    if (pps.entropy_coding_mode_flag) {
        throw std::invalid_argument("native CAVLC path rejects CABAC PPS");
    }
    static_cast<void>(reader.read_bit());  // bottom_field_pic_order_in_frame_present_flag
    pps.num_slice_groups_minus1 = reader.read_ue();
    if (pps.num_slice_groups_minus1 != 0) {
        throw std::invalid_argument("native CAVLC path does not support PPS slice groups");
    }
    pps.num_ref_idx_l0_default_active_minus1 = reader.read_ue();
    pps.num_ref_idx_l1_default_active_minus1 = reader.read_ue();
    static_cast<void>(reader.read_bit());  // weighted_pred_flag
    static_cast<void>(reader.read_bits(2));  // weighted_bipred_idc
    pps.pic_init_qp_minus26 = reader.read_se();
    static_cast<void>(reader.read_se());  // pic_init_qs_minus26
    static_cast<void>(reader.read_se());  // chroma_qp_index_offset
    pps.deblocking_filter_control_present_flag = reader.read_bit() != 0;
    static_cast<void>(reader.read_bit());  // constrained_intra_pred_flag
    pps.redundant_pic_cnt_present_flag = reader.read_bit() != 0;
    return pps;
}

H264BaselineIdrSliceHeader parse_baseline_idr_slice_header(
    const std::vector<std::uint8_t>& rbsp,
    const H264BaselineSps& sps,
    const H264BaselinePps& pps) {
    if (!sps.frame_mbs_only_flag || pps.entropy_coding_mode_flag || pps.num_slice_groups_minus1 != 0) {
        throw std::invalid_argument("native IDR parser requires frame-only CAVLC without slice groups");
    }
    if (sps.pic_order_cnt_type != 0 && sps.pic_order_cnt_type != 2) {
        throw std::invalid_argument("native IDR parser requires pic_order_cnt_type 0 or 2");
    }
    RbspBitReader reader(rbsp);
    H264BaselineIdrSliceHeader header;
    header.first_mb_in_slice = reader.read_ue();
    header.slice_type = reader.read_ue();
    if (header.slice_type > 4) {
        header.slice_type -= 5;
    }
    header.pic_parameter_set_id = reader.read_ue();
    header.frame_num = reader.read_bits(static_cast<std::size_t>(sps.log2_max_frame_num_minus4) + 4);
    header.idr_pic_id = reader.read_ue();
    if (sps.pic_order_cnt_type == 0) {
        header.pic_order_cnt_lsb = reader.read_bits(
            static_cast<std::size_t>(sps.log2_max_pic_order_cnt_lsb_minus4) + 4);
    }
    if (pps.redundant_pic_cnt_present_flag) {
        static_cast<void>(reader.read_ue());
    }
    const auto slice_type_modulo = header.slice_type % 5;
    if (slice_type_modulo != 2 && slice_type_modulo != 4) {
        throw std::invalid_argument("native IDR parser currently supports I and SI slices only");
    }
    static_cast<void>(reader.read_bit());  // no_output_of_prior_pics_flag
    static_cast<void>(reader.read_bit());  // long_term_reference_flag
    header.slice_qp_delta = reader.read_se();
    if (pps.deblocking_filter_control_present_flag) {
        const auto disable_deblocking_filter_idc = reader.read_ue();
        if (disable_deblocking_filter_idc != 1) {
            static_cast<void>(reader.read_se());
            static_cast<void>(reader.read_se());
        }
    }
    header.data_bit_offset = reader.position();
    return header;
}

CavlcCoeffToken parse_cavlc_coeff_token(
    const std::vector<std::uint8_t>& rbsp,
    const std::size_t start_bit,
    const int n_c) {
    if (n_c < -2) {
        throw std::invalid_argument("native coeff_token parser received an unsupported nC context");
    }
    RbspBitReader reader(rbsp);
    reader.skip_bits(start_bit);
    if (n_c >= 8) {
        // H.264 Table 9-5(e): a fixed six-bit coeff_token with TotalCoeff
        // in the high four bits and TrailingOnes in the low two bits.
        const auto code = reader.read_bits(6);
        CavlcCoeffToken token;
        if (code == 3U) {
            token.total_coefficients = 0;
        } else {
            token.total_coefficients = code >> 2U;
            token.trailing_ones = code & 0x3U;
        }
        if (token.trailing_ones > token.total_coefficients) {
            throw std::invalid_argument("invalid fixed-length CAVLC coeff_token");
        }
        token.sign_bit_offsets.reserve(token.trailing_ones);
        for (std::size_t index = 0; index < token.trailing_ones; ++index) {
            token.sign_bit_offsets.push_back(reader.position() + index);
        }
        token.level_bit_offset = reader.position() + token.trailing_ones;
        return token;
    }
    std::string bits;
    bits.reserve(16);
    const CoeffTokenCode* longest_match = nullptr;
    for (std::size_t length = 1; length <= 16; ++length) {
        bits.push_back(reader.read_bit() == 0 ? '0' : '1');
        bool has_longer_prefix = false;
        if (n_c == -1) {
            for (const auto& code : coeff_token_chroma_dc) {
                const std::string_view candidate{code.bits};
                if (candidate == bits) longest_match = &code;
                if (candidate.size() > bits.size() && candidate.compare(0, bits.size(), bits) == 0) {
                    has_longer_prefix = true;
                }
            }
        } else {
            const CoeffTokenCode* table = nullptr;
            std::size_t table_size = 0;
            if (n_c <= 1) {
                table = coeff_token_n0_1.data();
                table_size = coeff_token_n0_1.size();
            } else if (n_c <= 3) {
                table = coeff_token_n2_3.data();
                table_size = coeff_token_n2_3.size();
            } else {
                table = coeff_token_n4_7.data();
                table_size = coeff_token_n4_7.size();
            }
            for (std::size_t table_index = 0; table_index < table_size; ++table_index) {
                const auto& code = table[table_index];
                const std::string_view candidate{code.bits};
                if (candidate == bits) longest_match = &code;
                if (candidate.size() > bits.size() && candidate.compare(0, bits.size(), bits) == 0) {
                    has_longer_prefix = true;
                }
            }
        }
        if (!has_longer_prefix) break;
    }
    if (longest_match != nullptr) {
        CavlcCoeffToken token;
        token.total_coefficients = longest_match->total_coefficients;
        token.trailing_ones = longest_match->trailing_ones;
        token.sign_bit_offsets.reserve(token.trailing_ones);
        const auto token_end = start_bit + std::string_view(longest_match->bits).size();
        for (std::size_t index = 0; index < token.trailing_ones; ++index) {
            token.sign_bit_offsets.push_back(token_end + index);
        }
        token.level_bit_offset = token_end + token.trailing_ones;
        return token;
    }
    throw std::invalid_argument("invalid CAVLC coeff_token for nC 0 or 1");
}

CavlcDecodedLevels decode_cavlc_non_trailing_levels(
    const std::vector<std::uint8_t>& rbsp,
    const CavlcCoeffToken& token) {
    if (token.trailing_ones > token.total_coefficients) {
        throw std::invalid_argument("CAVLC trailing-one count exceeds total coefficients");
    }
    if (token.sign_bit_offsets.size() != token.trailing_ones) {
        throw std::invalid_argument("CAVLC trailing-one sign offsets are inconsistent");
    }
    CavlcDecodedLevels decoded;
    decoded.trailing_one_values.reserve(token.trailing_ones);
    for (const auto sign_bit_offset : token.sign_bit_offsets) {
        RbspBitReader sign_reader(rbsp);
        sign_reader.skip_bits(sign_bit_offset);
        decoded.trailing_one_values.push_back(sign_reader.read_bit() == 0 ? 1 : -1);
    }
    RbspBitReader reader(rbsp);
    reader.skip_bits(token.level_bit_offset);
    const auto count = token.total_coefficients - token.trailing_ones;
    decoded.values.reserve(count);
    std::uint32_t suffix_length = token.total_coefficients > 10 && token.trailing_ones < 3 ? 1 : 0;
    for (std::uint32_t index = 0; index < count; ++index) {
        std::uint32_t level_prefix = 0;
        while (reader.read_bit() == 0) {
            if (++level_prefix > 24) {
                throw std::invalid_argument("CAVLC level_prefix exceeds supported range");
            }
        }
        std::uint32_t level_code = 0;
        if (suffix_length == 0) {
            if (level_prefix < 14) {
                level_code = level_prefix;
            } else if (level_prefix == 14) {
                level_code = 14 + reader.read_bits(4);
            } else {
                level_code = 30;
                if (level_prefix >= 16) {
                    level_code += (1U << (level_prefix - 3)) - 4096U;
                }
                level_code += reader.read_bits(level_prefix - 3);
            }
        } else if (level_prefix < 15) {
            level_code = (level_prefix << suffix_length) + reader.read_bits(suffix_length);
        } else {
            level_code = 15U << suffix_length;
            if (level_prefix >= 16) {
                level_code += (1U << (level_prefix - 3)) - 4096U;
            }
            level_code += reader.read_bits(level_prefix - 3);
        }
        // H.264 9.2.2 applies this adjustment to the first decoded level
        // whenever there are fewer than three trailing ones.  Applying it to
        // the opposite case changes suffix-length evolution and desynchronises
        // following residual blocks.
        if (index == 0 && token.trailing_ones < 3) {
            level_code += 2U;
        }
        const auto sign = level_code & 1U;
        std::uint32_t absolute = 0;
        absolute = (level_code - sign + 2U) >> 1U;
        if (absolute > static_cast<std::uint32_t>(INT32_MAX)) {
            throw std::out_of_range("CAVLC level exceeds int32 range");
        }
        decoded.values.push_back(sign == 0 ? static_cast<std::int32_t>(absolute) : -static_cast<std::int32_t>(absolute));
        if (suffix_length == 0) {
            suffix_length = 1;
        }
        if (absolute > (3U << (suffix_length - 1)) && suffix_length < 6) {
            ++suffix_length;
        }
    }
    decoded.next_bit_offset = reader.position();
    return decoded;
}

std::vector<std::int32_t> reconstruct_cavlc_block(
    const CavlcDecodedLevels& decoded_levels,
    const std::vector<std::uint32_t>& runs,
    const std::size_t max_num_coefficients) {
    if (max_num_coefficients == 0) {
        throw std::invalid_argument("CAVLC reconstruction requires a non-empty block");
    }
    const auto total_coefficients = decoded_levels.trailing_one_values.size() + decoded_levels.values.size();
    if (total_coefficients != runs.size()) {
        throw std::invalid_argument("CAVLC level and run counts differ");
    }

    std::vector<std::int32_t> reverse_scan_levels;
    reverse_scan_levels.reserve(total_coefficients);
    reverse_scan_levels.insert(
        reverse_scan_levels.end(), decoded_levels.trailing_one_values.begin(), decoded_levels.trailing_one_values.end());
    reverse_scan_levels.insert(reverse_scan_levels.end(), decoded_levels.values.begin(), decoded_levels.values.end());

    std::vector<std::int32_t> coefficients;
    coefficients.reserve(max_num_coefficients);
    for (std::size_t reverse_index = 0; reverse_index < total_coefficients; ++reverse_index) {
        const auto index = total_coefficients - 1 - reverse_index;
        const auto run = runs[index];
        if (run > max_num_coefficients - coefficients.size()) {
            throw std::invalid_argument("CAVLC run expands beyond block");
        }
        coefficients.insert(coefficients.end(), run, 0);
        if (coefficients.size() >= max_num_coefficients) {
            throw std::invalid_argument("CAVLC coefficient expands beyond block");
        }
        coefficients.push_back(reverse_scan_levels[index]);
    }
    coefficients.resize(max_num_coefficients, 0);
    return coefficients;
}

CavlcResidualTail decode_cavlc_luma_residual_tail(
    const std::vector<std::uint8_t>& rbsp,
    const std::size_t start_bit,
    const std::uint32_t total_coefficients) {
    struct VlcCode { const char* bits; std::uint8_t value; };
    constexpr std::array total_zeros_tc1{
        VlcCode{"1", 0}, VlcCode{"011", 1}, VlcCode{"010", 2}, VlcCode{"0011", 3}, VlcCode{"0010", 4},
        VlcCode{"00011", 5}, VlcCode{"00010", 6}, VlcCode{"000011", 7}, VlcCode{"000010", 8},
        VlcCode{"0000011", 9}, VlcCode{"0000010", 10}, VlcCode{"00000011", 11}, VlcCode{"00000010", 12},
        VlcCode{"000000011", 13}, VlcCode{"000000010", 14}, VlcCode{"000000001", 15},
    };
    constexpr std::array total_zeros_tc2{
        VlcCode{"111", 0}, VlcCode{"110", 1}, VlcCode{"101", 2}, VlcCode{"100", 3}, VlcCode{"011", 4},
        VlcCode{"0101", 5}, VlcCode{"0100", 6}, VlcCode{"0011", 7}, VlcCode{"0010", 8}, VlcCode{"00011", 9},
        VlcCode{"00010", 10}, VlcCode{"000011", 11}, VlcCode{"000010", 12}, VlcCode{"000001", 13}, VlcCode{"000000", 14},
    };
    constexpr std::array total_zeros_tc3{
        VlcCode{"111", 1}, VlcCode{"110", 2}, VlcCode{"101", 3}, VlcCode{"100", 6}, VlcCode{"011", 7},
        VlcCode{"0101", 0}, VlcCode{"0100", 4}, VlcCode{"0011", 5}, VlcCode{"0010", 8}, VlcCode{"00011", 9},
        VlcCode{"00010", 10}, VlcCode{"00001", 12}, VlcCode{"000001", 11}, VlcCode{"000000", 13},
    };
    constexpr std::array total_zeros_tc4{
        VlcCode{"111", 1}, VlcCode{"110", 4}, VlcCode{"101", 5}, VlcCode{"100", 6}, VlcCode{"011", 8},
        VlcCode{"0101", 2}, VlcCode{"0100", 3}, VlcCode{"0011", 7}, VlcCode{"0010", 9}, VlcCode{"00011", 0},
        VlcCode{"00010", 10}, VlcCode{"00001", 11}, VlcCode{"00000", 12},
    };
    constexpr std::array total_zeros_tc5{
        VlcCode{"111", 3}, VlcCode{"110", 4}, VlcCode{"101", 5}, VlcCode{"100", 6}, VlcCode{"011", 7},
        VlcCode{"0101", 0}, VlcCode{"0100", 1}, VlcCode{"0011", 2}, VlcCode{"0010", 8}, VlcCode{"0001", 10},
        VlcCode{"00001", 9}, VlcCode{"00000", 11},
    };
    constexpr std::array total_zeros_tc6{
        VlcCode{"111", 2}, VlcCode{"110", 3}, VlcCode{"101", 4}, VlcCode{"100", 5}, VlcCode{"011", 6},
        VlcCode{"010", 7}, VlcCode{"001", 9}, VlcCode{"0001", 8}, VlcCode{"00001", 1}, VlcCode{"000001", 0},
        VlcCode{"000000", 10},
    };
    constexpr std::array total_zeros_tc7{
        VlcCode{"11", 5}, VlcCode{"101", 2}, VlcCode{"100", 3}, VlcCode{"011", 4}, VlcCode{"010", 6},
        VlcCode{"001", 8}, VlcCode{"0001", 7}, VlcCode{"00001", 1}, VlcCode{"000001", 0}, VlcCode{"000000", 9},
    };
    constexpr std::array total_zeros_tc8{
        VlcCode{"11", 4}, VlcCode{"10", 5}, VlcCode{"011", 3}, VlcCode{"010", 6}, VlcCode{"001", 7},
        VlcCode{"0001", 1}, VlcCode{"00001", 2}, VlcCode{"000001", 0}, VlcCode{"000000", 8},
    };
    constexpr std::array total_zeros_tc9{
        VlcCode{"11", 3}, VlcCode{"10", 4}, VlcCode{"01", 6}, VlcCode{"001", 5}, VlcCode{"0001", 2},
        VlcCode{"00001", 7}, VlcCode{"000001", 0}, VlcCode{"000000", 1},
    };
    constexpr std::array total_zeros_tc10{
        VlcCode{"11", 3}, VlcCode{"10", 4}, VlcCode{"01", 5}, VlcCode{"001", 2}, VlcCode{"0001", 6},
        VlcCode{"00001", 0}, VlcCode{"00000", 1},
    };
    constexpr std::array total_zeros_tc11{
        VlcCode{"1", 4}, VlcCode{"001", 2}, VlcCode{"010", 3}, VlcCode{"011", 5}, VlcCode{"0000", 0}, VlcCode{"0001", 1},
    };
    constexpr std::array total_zeros_tc12{
        VlcCode{"1", 3}, VlcCode{"01", 2}, VlcCode{"001", 4}, VlcCode{"0000", 0}, VlcCode{"0001", 1},
    };
    constexpr std::array total_zeros_tc13{
        VlcCode{"1", 2}, VlcCode{"01", 3}, VlcCode{"000", 0}, VlcCode{"001", 1},
    };
    constexpr std::array total_zeros_tc14{VlcCode{"1", 2}, VlcCode{"00", 0}, VlcCode{"01", 1}};
    constexpr std::array total_zeros_tc15{VlcCode{"0", 0}, VlcCode{"1", 1}};
    constexpr std::array run_before_zeros1_codes{
        VlcCode{"1", 0}, VlcCode{"0", 1},
    };
    constexpr std::array run_before_zeros2_codes{
        VlcCode{"1", 0}, VlcCode{"01", 1}, VlcCode{"00", 2},
    };
    constexpr std::array run_before_zeros3_codes{
        VlcCode{"11", 0}, VlcCode{"10", 1}, VlcCode{"01", 2}, VlcCode{"00", 3},
    };
    constexpr std::array run_before_zeros4_codes{
        VlcCode{"11", 0}, VlcCode{"10", 1}, VlcCode{"01", 2}, VlcCode{"001", 3}, VlcCode{"000", 4},
    };
    constexpr std::array run_before_zeros5_codes{
        VlcCode{"11", 0}, VlcCode{"10", 1}, VlcCode{"011", 2}, VlcCode{"010", 3}, VlcCode{"001", 4}, VlcCode{"000", 5},
    };
    constexpr std::array run_before_zeros6_codes{
        VlcCode{"11", 0}, VlcCode{"000", 1}, VlcCode{"001", 2}, VlcCode{"011", 3}, VlcCode{"010", 4}, VlcCode{"101", 5}, VlcCode{"100", 6},
    };
    constexpr std::array run_before_zeros7_plus_codes{
        VlcCode{"111", 0}, VlcCode{"110", 1}, VlcCode{"101", 2}, VlcCode{"100", 3}, VlcCode{"011", 4},
        VlcCode{"010", 5}, VlcCode{"001", 6}, VlcCode{"0001", 7}, VlcCode{"00001", 8}, VlcCode{"000001", 9},
        VlcCode{"0000001", 10}, VlcCode{"00000001", 11}, VlcCode{"000000001", 12}, VlcCode{"0000000001", 13}, VlcCode{"00000000001", 14},
    };
    const auto decode = [](RbspBitReader& reader, const auto& table) -> std::uint32_t {
        std::string bits;
        bits.reserve(14);
        for (std::size_t length = 1; length <= 14; ++length) {
            bits.push_back(reader.read_bit() == 0 ? '0' : '1');
            for (const auto& code : table) {
                if (bits == code.bits) return code.value;
            }
        }
        throw std::invalid_argument("invalid CAVLC tail VLC");
    };
    if (total_coefficients == 0 || total_coefficients > 16) {
        throw std::invalid_argument("luma total_coefficients must be in [1, 16]");
    }
    RbspBitReader reader(rbsp);
    reader.skip_bits(start_bit);
    CavlcResidualTail tail;
    switch (total_coefficients) {
        case 1: tail.total_zeros = decode(reader, total_zeros_tc1); break;
        case 2: tail.total_zeros = decode(reader, total_zeros_tc2); break;
        case 3: tail.total_zeros = decode(reader, total_zeros_tc3); break;
        case 4: tail.total_zeros = decode(reader, total_zeros_tc4); break;
        case 5: tail.total_zeros = decode(reader, total_zeros_tc5); break;
        case 6: tail.total_zeros = decode(reader, total_zeros_tc6); break;
        case 7: tail.total_zeros = decode(reader, total_zeros_tc7); break;
        case 8: tail.total_zeros = decode(reader, total_zeros_tc8); break;
        case 9: tail.total_zeros = decode(reader, total_zeros_tc9); break;
        case 10: tail.total_zeros = decode(reader, total_zeros_tc10); break;
        case 11: tail.total_zeros = decode(reader, total_zeros_tc11); break;
        case 12: tail.total_zeros = decode(reader, total_zeros_tc12); break;
        case 13: tail.total_zeros = decode(reader, total_zeros_tc13); break;
        case 14: tail.total_zeros = decode(reader, total_zeros_tc14); break;
        case 15: tail.total_zeros = decode(reader, total_zeros_tc15); break;
        case 16: break;
        default: throw std::invalid_argument("unsupported luma total_coefficients");
    }
    const auto max_total_zeros = 16U - total_coefficients;
    if (tail.total_zeros > max_total_zeros) {
        throw std::invalid_argument("CAVLC total_zeros exceeds luma block bound");
    }
    auto zeros_left = tail.total_zeros;
    for (std::uint32_t index = 1; index < total_coefficients; ++index) {
        std::uint32_t run = 0;
        if (zeros_left == 1) {
            run = decode(reader, run_before_zeros1_codes);
        } else if (zeros_left == 2) {
            run = decode(reader, run_before_zeros2_codes);
        } else if (zeros_left == 3) {
            run = decode(reader, run_before_zeros3_codes);
        } else if (zeros_left == 4) {
            run = decode(reader, run_before_zeros4_codes);
        } else if (zeros_left == 5) {
            run = decode(reader, run_before_zeros5_codes);
        } else if (zeros_left == 6) {
            run = decode(reader, run_before_zeros6_codes);
        } else if (zeros_left >= 7) {
            run = decode(reader, run_before_zeros7_plus_codes);
        }
        if (run > zeros_left) throw std::invalid_argument("CAVLC run exceeds remaining zeros");
        tail.runs.push_back(run);
        zeros_left -= run;
    }
    tail.runs.push_back(zeros_left);
    tail.next_bit_offset = reader.position();
    return tail;
}

CavlcResidualTail decode_cavlc_chroma_dc_residual_tail(
    const std::vector<std::uint8_t>& rbsp,
    const std::size_t start_bit,
    const std::uint32_t total_coefficients) {
    struct VlcCode { const char* bits; std::uint8_t value; };
    constexpr std::array total_zeros_tc1{
        VlcCode{"1", 0}, VlcCode{"01", 1}, VlcCode{"00", 2}, VlcCode{"000", 3},
    };
    constexpr std::array total_zeros_tc2{
        VlcCode{"1", 0}, VlcCode{"01", 1}, VlcCode{"00", 2},
    };
    constexpr std::array total_zeros_tc3{
        VlcCode{"1", 0}, VlcCode{"0", 1},
    };
    constexpr std::array run_before_zeros1{
        VlcCode{"1", 0}, VlcCode{"0", 1},
    };
    constexpr std::array run_before_zeros2{
        VlcCode{"1", 0}, VlcCode{"01", 1}, VlcCode{"00", 2},
    };
    constexpr std::array run_before_zeros3{
        VlcCode{"11", 0}, VlcCode{"10", 1}, VlcCode{"01", 2}, VlcCode{"00", 3},
    };
    const auto decode = [](RbspBitReader& reader, const auto& table) -> std::uint32_t {
        std::string bits;
        for (std::size_t length = 1; length <= 3; ++length) {
            bits.push_back(reader.read_bit() == 0 ? '0' : '1');
            for (const auto& code : table) {
                if (bits == code.bits) return code.value;
            }
        }
        throw std::invalid_argument("invalid chroma DC CAVLC VLC");
    };
    if (total_coefficients == 0 || total_coefficients > 4) {
        throw std::invalid_argument("chroma DC total_coefficients must be in [1, 4]");
    }
    RbspBitReader reader(rbsp);
    reader.skip_bits(start_bit);
    CavlcResidualTail tail;
    if (total_coefficients == 1) tail.total_zeros = decode(reader, total_zeros_tc1);
    if (total_coefficients == 2) tail.total_zeros = decode(reader, total_zeros_tc2);
    if (total_coefficients == 3) tail.total_zeros = decode(reader, total_zeros_tc3);
    if (tail.total_zeros > 4U - total_coefficients) {
        throw std::invalid_argument("chroma DC total_zeros exceeds block bound");
    }
    auto zeros_left = tail.total_zeros;
    for (std::uint32_t index = 1; index < total_coefficients; ++index) {
        std::uint32_t run = 0;
        if (zeros_left == 1) run = decode(reader, run_before_zeros1);
        if (zeros_left == 2) run = decode(reader, run_before_zeros2);
        if (zeros_left == 3) run = decode(reader, run_before_zeros3);
        if (run > zeros_left) throw std::invalid_argument("chroma DC run exceeds remaining zeros");
        tail.runs.push_back(run);
        zeros_left -= run;
    }
    tail.runs.push_back(zeros_left);
    tail.next_bit_offset = reader.position();
    return tail;
}

CavlcResidualTail decode_cavlc_tail_tc4(
    const std::vector<std::uint8_t>& rbsp,
    const std::size_t start_bit) {
    return decode_cavlc_luma_residual_tail(rbsp, start_bit, 4);
}

CavlcDecodedLumaBlock decode_cavlc_luma_block(
    const std::vector<std::uint8_t>& rbsp,
    const std::size_t start_bit,
    const int n_c) {
    constexpr std::size_t kLumaBlockCoefficients = 16;
    CavlcDecodedLumaBlock block;
    block.token = parse_cavlc_coeff_token(rbsp, start_bit, n_c);
    block.levels = decode_cavlc_non_trailing_levels(rbsp, block.token);
    if (block.token.total_coefficients == 0) {
        block.tail.next_bit_offset = block.levels.next_bit_offset;
    } else {
        block.tail = decode_cavlc_luma_residual_tail(
            rbsp, block.levels.next_bit_offset, block.token.total_coefficients);
    }
    block.coefficients = reconstruct_cavlc_block(
        block.levels, block.tail.runs, kLumaBlockCoefficients);
    return block;
}

CavlcDecodedLumaBlock decode_cavlc_chroma_dc_block(
    const std::vector<std::uint8_t>& rbsp,
    const std::size_t start_bit) {
    CavlcDecodedLumaBlock block;
    block.token = parse_cavlc_coeff_token(rbsp, start_bit, -1);
    block.levels = decode_cavlc_non_trailing_levels(rbsp, block.token);
    if (block.token.total_coefficients == 0) {
        block.tail.next_bit_offset = block.levels.next_bit_offset;
    } else {
        block.tail = decode_cavlc_chroma_dc_residual_tail(
            rbsp, block.levels.next_bit_offset, block.token.total_coefficients);
    }
    block.coefficients = reconstruct_cavlc_block(block.levels, block.tail.runs, 4);
    return block;
}

CavlcDecodedLumaBlock decode_cavlc_chroma_ac_block(
    const std::vector<std::uint8_t>& rbsp,
    const std::size_t start_bit,
    const int n_c) {
    if (n_c < 0) {
        throw std::invalid_argument("chroma AC requires a non-negative nC context");
    }
    constexpr std::size_t kChromaAcCoefficients = 15;
    CavlcDecodedLumaBlock block;
    block.token = parse_cavlc_coeff_token(rbsp, start_bit, n_c);
    block.levels = decode_cavlc_non_trailing_levels(rbsp, block.token);
    if (block.token.total_coefficients == 0) {
        block.tail.next_bit_offset = block.levels.next_bit_offset;
    } else {
        block.tail = decode_cavlc_luma_residual_tail(
            rbsp, block.levels.next_bit_offset, block.token.total_coefficients);
        if (block.tail.total_zeros > kChromaAcCoefficients - block.token.total_coefficients) {
            throw std::invalid_argument("chroma AC total_zeros exceeds block bound");
        }
    }
    block.coefficients = reconstruct_cavlc_block(
        block.levels, block.tail.runs, kChromaAcCoefficients);
    return block;
}

CavlcDecodedLumaMacroblock decode_cavlc_luma_macroblock(
    const std::vector<std::uint8_t>& rbsp,
    const std::size_t start_bit,
    const std::uint32_t coded_block_pattern_luma) {
    // H.264 luma4x4BlkIdx is ordered by 8x8 group, not by 4x4 raster order.
    // residual_block_cavlc() visits each group in index order.  The raster
    // map below is used only for deriving the physical left/top neighbours.
    constexpr std::array<std::array<std::size_t, 4>, 4> kCavlcLumaGroups{{
        {{0, 1, 2, 3}},
        {{4, 5, 6, 7}},
        {{8, 9, 10, 11}},
        {{12, 13, 14, 15}},
    }};
    constexpr std::array<std::array<std::size_t, 4>, 4> kBlockIndexByRaster{{
        {{0, 1, 4, 5}},
        {{2, 3, 6, 7}},
        {{8, 9, 12, 13}},
        {{10, 11, 14, 15}},
    }};
    if (coded_block_pattern_luma > 0x0fU) {
        throw std::invalid_argument("luma coded block pattern must fit four bits");
    }

    CavlcDecodedLumaMacroblock macroblock;
    std::array<std::uint32_t, 16> total_coefficients{};
    auto bit_offset = start_bit;
    for (std::size_t group_index = 0; group_index < kCavlcLumaGroups.size(); ++group_index) {
        if ((coded_block_pattern_luma & (1U << group_index)) == 0U) continue;
        for (const auto block_index : kCavlcLumaGroups[group_index]) {
            std::size_t x = 0;
            std::size_t y = 0;
            for (; y < kBlockIndexByRaster.size(); ++y) {
                for (x = 0; x < kBlockIndexByRaster[y].size(); ++x) {
                    if (kBlockIndexByRaster[y][x] == block_index) break;
                }
                if (x != kBlockIndexByRaster[y].size()) break;
            }
            const auto has_left = x != 0;
            const auto has_top = y != 0;
            const auto n_a = has_left ? total_coefficients[kBlockIndexByRaster[y][x - 1]] : 0U;
            const auto n_b = has_top ? total_coefficients[kBlockIndexByRaster[y - 1][x]] : 0U;
            const auto n_c = has_left && has_top ? static_cast<int>((n_a + n_b + 1U) / 2U)
                           : has_left ? static_cast<int>(n_a)
                           : has_top ? static_cast<int>(n_b)
                                      : 0;
            auto& block = macroblock.blocks[block_index];
            try {
                block = decode_cavlc_luma_block(rbsp, bit_offset, n_c);
            } catch (const std::exception& error) {
                std::string decoded_summary;
                for (std::size_t prior_index = 0; prior_index < macroblock.blocks.size(); ++prior_index) {
                    const auto& prior = macroblock.blocks[prior_index];
                    if (prior.token.level_bit_offset == 0 && prior.tail.next_bit_offset == 0) continue;
                    decoded_summary += " b" + std::to_string(prior_index) +
                        "=TC" + std::to_string(prior.token.total_coefficients) +
                        "/T1" + std::to_string(prior.token.trailing_ones) +
                        "/end" + std::to_string(prior.tail.next_bit_offset);
                }
                throw std::invalid_argument(
                    "CAVLC luma block " + std::to_string(block_index) +
                    " (bit=" + std::to_string(bit_offset) +
                    ", nA=" + std::to_string(n_a) +
                    ", nB=" + std::to_string(n_b) +
                    ", nC=" + std::to_string(n_c) + "): " + error.what() + decoded_summary);
            }
            total_coefficients[block_index] = block.token.total_coefficients;
            bit_offset = block.tail.next_bit_offset;
        }
    }
    macroblock.next_bit_offset = bit_offset;
    return macroblock;
}

std::vector<std::int32_t> reconstruct_cavlc_tc4_no_trailing(
    const std::vector<std::int32_t>& decoded_non_trailing_levels,
    const std::vector<std::uint32_t>& runs) {
    constexpr std::size_t kBlockCoefficients = 16;
    constexpr std::size_t kTotalCoefficients = 4;
    if (decoded_non_trailing_levels.size() != kTotalCoefficients || runs.size() != kTotalCoefficients) {
        throw std::invalid_argument("TC=4 reconstruction requires exactly four levels and runs");
    }
    CavlcDecodedLevels decoded;
    decoded.values = decoded_non_trailing_levels;
    return reconstruct_cavlc_block(decoded, runs, kBlockCoefficients);
}

H264BaselineIMacroblockHeader parse_baseline_i_macroblock_header(
    const std::vector<std::uint8_t>& rbsp,
    const std::size_t start_bit) {
    constexpr std::array<std::uint8_t, 48> intra_cbp_map{
        47, 31, 15, 0, 23, 27, 29, 30, 7, 11, 13, 14, 39, 43, 45, 46,
        16, 3, 5, 10, 12, 19, 21, 26, 28, 35, 37, 42, 44, 1, 2, 4,
        8, 17, 18, 20, 24, 6, 9, 22, 25, 32, 33, 34, 36, 40, 38, 41,
    };
    RbspBitReader reader(rbsp);
    reader.skip_bits(start_bit);
    H264BaselineIMacroblockHeader header;
    header.intra_4x4_prediction_modes.fill(-1);
    header.mb_type = reader.read_ue();
    if (header.mb_type == 25) {
        throw std::invalid_argument("native I macroblock parser does not support I_PCM");
    }
    if (header.mb_type > 25) {
        throw std::invalid_argument("invalid I-slice macroblock type");
    }
    if (header.mb_type == 0) {
        for (std::size_t index = 0; index < header.intra_4x4_prediction_modes.size(); ++index) {
            if (reader.read_bit() == 0) {
                header.intra_4x4_prediction_modes[index] = static_cast<std::int8_t>(reader.read_bits(3));
            }
        }
        const auto chroma_mode = reader.read_ue();
        if (chroma_mode > 3) {
            throw std::invalid_argument("invalid intra chroma prediction mode");
        }
        const auto mapped_cbp = reader.read_ue();
        if (mapped_cbp >= intra_cbp_map.size()) {
            throw std::invalid_argument("invalid intra coded block pattern");
        }
        header.coded_block_pattern = intra_cbp_map[mapped_cbp];
    } else {
        const auto chroma_mode = reader.read_ue();
        if (chroma_mode > 3) {
            throw std::invalid_argument("invalid intra chroma prediction mode");
        }
        const auto type_offset = header.mb_type - 1;
        const auto luma_cbp = type_offset / 12 == 0 ? 0U : 15U;
        const auto chroma_index = (type_offset % 12) / 4;
        const auto chroma_cbp = chroma_index == 0 ? 0U : chroma_index == 1 ? 1U : 3U;
        header.coded_block_pattern = (chroma_cbp << 4U) | luma_cbp;
    }
    if (header.coded_block_pattern != 0 || header.mb_type != 0) {
        header.mb_qp_delta = reader.read_se();
    }
    header.residual_bit_offset = reader.position();
    return header;
}

std::vector<std::uint8_t> ebsp_to_rbsp(const std::vector<std::uint8_t>& ebsp) {
    std::vector<std::uint8_t> rbsp;
    rbsp.reserve(ebsp.size());
    std::size_t zeros = 0;
    for (std::size_t index = 0; index < ebsp.size(); ++index) {
        const auto byte = ebsp[index];
        if (zeros >= 2 && byte == 0x03 && index + 1 < ebsp.size() && ebsp[index + 1] <= 0x03) {
            zeros = 0;
            continue;
        }
        rbsp.push_back(byte);
        zeros = byte == 0 ? zeros + 1 : 0;
    }
    return rbsp;
}

std::vector<std::uint8_t> rbsp_to_ebsp(const std::vector<std::uint8_t>& rbsp) {
    std::vector<std::uint8_t> ebsp;
    ebsp.reserve(rbsp.size() + rbsp.size() / 64);
    std::size_t zeros = 0;
    for (const auto byte : rbsp) {
        if (zeros >= 2 && byte <= 0x03) {
            ebsp.push_back(0x03);
            zeros = 0;
        }
        ebsp.push_back(byte);
        zeros = byte == 0 ? zeros + 1 : 0;
    }
    return ebsp;
}

std::vector<std::uint8_t> AnnexBNalUnit::rbsp() const {
    return ebsp_to_rbsp(payload);
}

std::vector<AnnexBNalUnit> split_annex_b(const std::vector<std::uint8_t>& annex_b) {
    std::vector<AnnexBNalUnit> units;
    std::size_t cursor = 0;
    while (cursor < annex_b.size()) {
        const auto marker_length = start_code_length_at(annex_b, cursor);
        if (marker_length == 0) {
            ++cursor;
            continue;
        }
        const auto start = cursor;
        const auto header_offset = cursor + marker_length;
        if (header_offset >= annex_b.size()) break;
        cursor = header_offset + 1;
        while (cursor < annex_b.size() && start_code_length_at(annex_b, cursor) == 0) ++cursor;

        const auto header = annex_b[header_offset];
        AnnexBNalUnit unit;
        unit.start_offset = start;
        unit.start_code_size = marker_length;
        unit.forbidden_zero_bit = static_cast<std::uint8_t>((header >> 7) & 0x01);
        unit.nal_ref_idc = static_cast<std::uint8_t>((header >> 5) & 0x03);
        unit.nal_unit_type = static_cast<std::uint8_t>(header & 0x1f);
        unit.payload.assign(annex_b.begin() + static_cast<std::ptrdiff_t>(header_offset + 1),
                            annex_b.begin() + static_cast<std::ptrdiff_t>(cursor));
        units.push_back(std::move(unit));
    }
    return units;
}

std::vector<H264BaselineIdrNalHeader> inspect_baseline_idr_headers(
    const std::vector<std::uint8_t>& annex_b) {
    std::unordered_map<std::uint32_t, H264BaselineSps> sps_by_id;
    std::unordered_map<std::uint32_t, H264BaselinePps> pps_by_id;
    std::vector<H264BaselineIdrNalHeader> inspected;
    const auto units = split_annex_b(annex_b);

    for (std::size_t nal_index = 0; nal_index < units.size(); ++nal_index) {
        const auto& nal = units[nal_index];
        const auto rbsp = nal.rbsp();
        if (nal.nal_unit_type == 7) {
            const auto sps = parse_baseline_sps(rbsp);
            sps_by_id.insert_or_assign(sps.sequence_parameter_set_id, sps);
            continue;
        }
        if (nal.nal_unit_type == 8) {
            const auto pps = parse_baseline_pps(rbsp);
            pps_by_id.insert_or_assign(pps.pic_parameter_set_id, pps);
            continue;
        }
        if (!nal.is_idr()) {
            continue;
        }

        // The PPS id is the third Exp-Golomb field in every slice header and
        // can be read before selecting its SPS-dependent frame-number width.
        RbspBitReader prefix_reader(rbsp);
        static_cast<void>(prefix_reader.read_ue());  // first_mb_in_slice
        static_cast<void>(prefix_reader.read_ue());  // slice_type
        const auto pps_id = prefix_reader.read_ue();
        const auto pps_it = pps_by_id.find(pps_id);
        if (pps_it == pps_by_id.end()) {
            throw std::invalid_argument("IDR references an unavailable PPS");
        }
        const auto sps_it = sps_by_id.find(pps_it->second.sequence_parameter_set_id);
        if (sps_it == sps_by_id.end()) {
            throw std::invalid_argument("PPS references an unavailable SPS");
        }
        const auto slice_header = parse_baseline_idr_slice_header(rbsp, sps_it->second, pps_it->second);
        const auto first_macroblock = parse_baseline_i_macroblock_header(rbsp, slice_header.data_bit_offset);
        inspected.push_back(H264BaselineIdrNalHeader{
            nal_index,
            slice_header,
            first_macroblock,
            decode_cavlc_luma_block(rbsp, first_macroblock.residual_bit_offset, 0),
        });
    }
    return inspected;
}

std::vector<std::uint8_t> assemble_annex_b(const std::vector<AnnexBNalUnit>& units) {
    std::size_t total_size = 0;
    for (const auto& unit : units) {
        if (unit.start_code_size != 3 && unit.start_code_size != 4) {
            throw std::invalid_argument("Annex-B NAL start code must be three or four bytes");
        }
        if (unit.forbidden_zero_bit > 1 || unit.nal_ref_idc > 3 || unit.nal_unit_type > 31) {
            throw std::invalid_argument("Annex-B NAL header fields are out of range");
        }
        total_size += unit.start_code_size + 1 + unit.payload.size();
    }

    std::vector<std::uint8_t> annex_b;
    annex_b.reserve(total_size);
    for (const auto& unit : units) {
        annex_b.insert(annex_b.end(), unit.start_code_size - 1, 0x00);
        annex_b.push_back(0x01);
        const auto header = static_cast<std::uint8_t>(
            (unit.forbidden_zero_bit << 7) | (unit.nal_ref_idc << 5) | unit.nal_unit_type);
        annex_b.push_back(header);
        annex_b.insert(annex_b.end(), unit.payload.begin(), unit.payload.end());
    }
    return annex_b;
}

std::vector<std::uint8_t> apply_fixed_length_patches(
    const std::vector<std::uint8_t>& source,
    const std::vector<FixedLengthBitPatch>& patches) {
    auto output = source;
    const auto total_bits = output.size() * 8;
    for (const auto& patch : patches) {
        if (patch.bit_offset > total_bits || patch.bits.size() > total_bits - patch.bit_offset) {
            throw std::out_of_range("CAVLC bit patch is outside RBSP bounds");
        }
        for (std::size_t index = 0; index < patch.bits.size(); ++index) {
            if (patch.bits[index] > 1) throw std::invalid_argument("CAVLC patch bits must be zero or one");
            const auto absolute = patch.bit_offset + index;
            const auto byte_index = absolute / 8;
            const auto mask = static_cast<std::uint8_t>(1U << (7 - (absolute % 8)));
            if (patch.bits[index]) output[byte_index] |= mask;
            else output[byte_index] &= static_cast<std::uint8_t>(~mask);
        }
    }
    return output;
}

std::vector<std::uint8_t> patch_annex_b_nal_rbsp(
    const std::vector<std::uint8_t>& annex_b,
    const std::size_t nal_index,
    const std::vector<FixedLengthBitPatch>& patches) {
    auto units = split_annex_b(annex_b);
    if (nal_index >= units.size()) {
        throw std::out_of_range("Annex-B NAL index is outside the segment");
    }
    auto rbsp = units[nal_index].rbsp();
    rbsp = apply_fixed_length_patches(rbsp, patches);
    units[nal_index].payload = rbsp_to_ebsp(rbsp);
    return assemble_annex_b(units);
}

std::vector<std::uint8_t> patch_annex_b_rbsp_plan(
    const std::vector<std::uint8_t>& annex_b,
    const std::vector<AnnexBRbspPatchPlan>& plan) {
    auto units = split_annex_b(annex_b);
    std::vector<bool> touched(units.size(), false);
    for (const auto& entry : plan) {
        if (entry.nal_index >= units.size()) {
            throw std::out_of_range("Annex-B patch plan NAL index is outside the segment");
        }
        auto rbsp = touched[entry.nal_index]
            ? ebsp_to_rbsp(units[entry.nal_index].payload)
            : units[entry.nal_index].rbsp();
        units[entry.nal_index].payload = rbsp_to_ebsp(apply_fixed_length_patches(rbsp, entry.patches));
        touched[entry.nal_index] = true;
    }
    return assemble_annex_b(units);
}

}  // namespace zkstego
