#include "zkstego/cavlc_stream.hpp"


#include <array>
#include <algorithm>
#include <iterator>
#include <limits>
#include <stdexcept>
#include <string>
#include <string_view>
#include <unordered_map>
#include <unordered_set>

#ifdef _WIN32
#ifndef NOMINMAX
#define NOMINMAX
#endif
#ifndef WIN32_LEAN_AND_MEAN
#define WIN32_LEAN_AND_MEAN
#endif
#include <windows.h>
#include <bcrypt.h>
#else
#include <openssl/crypto.h>
#include <openssl/evp.h>
#include <openssl/hmac.h>
#endif

namespace zkstego {

namespace {

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
    CoeffTokenCode{"00000111", 2, 0}, CoeffTokenCode{"000100", 2, 1}, CoeffTokenCode{"001", 2, 2},
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
    CoeffTokenCode{"0000000000001111", 13, 0}, CoeffTokenCode{"000000000000001", 13, 1}, CoeffTokenCode{"000000000001001", 13, 2}, CoeffTokenCode{"000000000001100", 13, 3},
    CoeffTokenCode{"0000000000001011", 14, 0}, CoeffTokenCode{"0000000000001110", 14, 1}, CoeffTokenCode{"0000000000001101", 14, 2}, CoeffTokenCode{"000000000001000", 14, 3},
    CoeffTokenCode{"0000000000000111", 15, 0}, CoeffTokenCode{"0000000000001010", 15, 1}, CoeffTokenCode{"0000000000001001", 15, 2}, CoeffTokenCode{"0000000000001100", 15, 3},
    CoeffTokenCode{"0000000000000100", 16, 0}, CoeffTokenCode{"0000000000000110", 16, 1}, CoeffTokenCode{"0000000000000101", 16, 2}, CoeffTokenCode{"0000000000001000", 16, 3},
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
    static_cast<void>(validated_picture_macroblock_count(sps));
    return sps;
}

std::size_t validated_picture_macroblock_count(const H264BaselineSps& sps) {
    // Field/MBAFF pictures double the map-unit height; they are rejected by
    // the slice parser but are bounded here as frames for a safe estimate.
    const auto width = static_cast<std::size_t>(sps.pic_width_in_mbs_minus1) + 1U;
    const auto map_units = static_cast<std::size_t>(sps.pic_height_in_map_units_minus1) + 1U;
    const auto height = sps.frame_mbs_only_flag ? map_units : map_units * 2U;
    if (width > kMaxPictureDimensionMbs || height > kMaxPictureDimensionMbs ||
        width * height > kMaxPictureMacroblocks) {
        throw std::invalid_argument(
            "SPS picture size exceeds the native decoder bound of " +
            std::to_string(kMaxPictureMacroblocks) + " macroblocks");
    }
    return width * height;
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
    pps.bottom_field_pic_order_in_frame_present_flag = reader.read_bit() != 0;
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
        // field_pic_flag is absent (inferred 0) because frame_mbs_only_flag
        // is required above, so the bottom-field delta is present whenever
        // the PPS flag is set. pic_order_cnt_type 1 (delta_pic_order_cnt[])
        // is rejected by both the SPS and this parser.
        if (pps.bottom_field_pic_order_in_frame_present_flag) {
            header.delta_pic_order_cnt_bottom = reader.read_se();
        }
    }
    if (pps.redundant_pic_cnt_present_flag) {
        static_cast<void>(reader.read_ue());
    }
    const auto slice_type_modulo = header.slice_type % 5;
    if (slice_type_modulo != 2) {
        throw std::invalid_argument("native IDR parser requires I-slice macroblock syntax");
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
    // nC == -1 selects the 4:2:0 ChromaDC table. nC == -2 (4:2:2 ChromaDC)
    // and anything lower are outside the supported baseline 4:2:0 profile.
    if (n_c < -1) {
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
            token.total_coefficients = (code >> 2U) + 1U;
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
        token.start_bit_offset = start_bit;
        token.n_c = n_c;
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
        token.start_bit_offset = start_bit;
        token.n_c = n_c;
        return token;
    }
    throw std::invalid_argument("invalid CAVLC coeff_token for nC " + std::to_string(n_c));
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

// The VLC tables below are shared by luma 4x4 and ChromaAC.  The latter has
// maxNumCoeff=15 because its DC coefficient is carried separately, so the
// presence rule for total_zeros must be parameterized.
CavlcResidualTail decode_cavlc_residual_tail(
    const std::vector<std::uint8_t>& rbsp,
    const std::size_t start_bit,
    const std::uint32_t total_coefficients,
    const std::size_t max_num_coefficients) {
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
    if (max_num_coefficients == 0 || max_num_coefficients > 16 ||
        total_coefficients == 0 || total_coefficients > max_num_coefficients) {
        throw std::invalid_argument("CAVLC total_coefficients exceeds residual block bound");
    }
    RbspBitReader reader(rbsp);
    reader.skip_bits(start_bit);
    CavlcResidualTail tail;
    if (total_coefficients < max_num_coefficients) {
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
            default: throw std::invalid_argument("unsupported CAVLC total_coefficients");
        }
    }
    const auto max_total_zeros = static_cast<std::uint32_t>(max_num_coefficients) - total_coefficients;
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

CavlcResidualTail decode_cavlc_luma_residual_tail(
    const std::vector<std::uint8_t>& rbsp,
    const std::size_t start_bit,
    const std::uint32_t total_coefficients) {
    return decode_cavlc_residual_tail(rbsp, start_bit, total_coefficients, 16);
}

CavlcResidualTail decode_cavlc_chroma_dc_residual_tail(
    const std::vector<std::uint8_t>& rbsp,
    const std::size_t start_bit,
    const std::uint32_t total_coefficients) {
    struct VlcCode { const char* bits; std::uint8_t value; };
    constexpr std::array total_zeros_tc1{
        VlcCode{"1", 0}, VlcCode{"01", 1}, VlcCode{"001", 2}, VlcCode{"000", 3},
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

CavlcDecodedLumaBlock decode_cavlc_luma_ac_block(
    const std::vector<std::uint8_t>& rbsp,
    const std::size_t start_bit,
    const int n_c) {
    if (n_c < 0) {
        throw std::invalid_argument("luma AC requires a non-negative nC context");
    }
    constexpr std::size_t kLumaAcCoefficients = 15;
    CavlcDecodedLumaBlock block;
    block.token = parse_cavlc_coeff_token(rbsp, start_bit, n_c);
    block.levels = decode_cavlc_non_trailing_levels(rbsp, block.token);
    if (block.token.total_coefficients == 0) {
        block.tail.next_bit_offset = block.levels.next_bit_offset;
    } else {
        block.tail = decode_cavlc_residual_tail(
            rbsp, block.levels.next_bit_offset, block.token.total_coefficients, kLumaAcCoefficients);
    }
    block.coefficients = reconstruct_cavlc_block(
        block.levels, block.tail.runs, kLumaAcCoefficients);
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
        block.tail = decode_cavlc_residual_tail(
            rbsp, block.levels.next_bit_offset, block.token.total_coefficients, kChromaAcCoefficients);
    }
    block.coefficients = reconstruct_cavlc_block(
        block.levels, block.tail.runs, kChromaAcCoefficients);
    return block;
}

namespace {

CavlcDecodedLumaMacroblock decode_cavlc_luma_macroblock_impl(
    const std::vector<std::uint8_t>& rbsp,
    const std::size_t start_bit,
    const std::uint32_t coded_block_pattern_luma,
    const CavlcLumaNeighbourCounts& neighbours,
    const bool ac_only) {
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
    // A CAVLC TotalCoeff is bounded by the 16 coefficients in a luma 4x4
    // block. Validate externally persisted state before it participates in
    // the nC average: apart from rejecting corrupt traversal state, this also
    // prevents overflow in nA + nB below.
    const auto validate_neighbour_counts = [](const std::array<std::uint32_t, 4>& counts,
                                               const char* direction) {
        for (const auto count : counts) {
            if (count > 16U) {
                throw std::invalid_argument(
                    std::string("luma ") + direction + " neighbour TotalCoeff exceeds 16");
            }
        }
    };
    if (neighbours.left_available) validate_neighbour_counts(neighbours.left, "left");
    if (neighbours.top_available) validate_neighbour_counts(neighbours.top, "top");

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
            const auto has_left = x != 0 || neighbours.left_available;
            const auto has_top = y != 0 || neighbours.top_available;
            const auto n_a = x != 0 ? total_coefficients[kBlockIndexByRaster[y][x - 1]]
                                    : neighbours.left[y];
            const auto n_b = y != 0 ? total_coefficients[kBlockIndexByRaster[y - 1][x]]
                                    : neighbours.top[x];
            const auto n_c = has_left && has_top ? static_cast<int>((n_a + n_b + 1U) / 2U)
                           : has_left ? static_cast<int>(n_a)
                           : has_top ? static_cast<int>(n_b)
                                      : 0;
            auto& block = macroblock.blocks[block_index];
            try {
                block = ac_only ? decode_cavlc_luma_ac_block(rbsp, bit_offset, n_c)
                                : decode_cavlc_luma_block(rbsp, bit_offset, n_c);
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

}  // namespace

CavlcDecodedLumaMacroblock decode_cavlc_luma_macroblock(
    const std::vector<std::uint8_t>& rbsp,
    const std::size_t start_bit,
    const std::uint32_t coded_block_pattern_luma,
    const CavlcLumaNeighbourCounts& neighbours) {
    return decode_cavlc_luma_macroblock_impl(
        rbsp, start_bit, coded_block_pattern_luma, neighbours, false);
}

CavlcDecodedLumaMacroblock decode_cavlc_luma_macroblock(
    const std::vector<std::uint8_t>& rbsp,
    const std::size_t start_bit,
    const std::uint32_t coded_block_pattern_luma) {
    return decode_cavlc_luma_macroblock(
        rbsp, start_bit, coded_block_pattern_luma, CavlcLumaNeighbourCounts{});
}

CavlcDecodedLumaMacroblock decode_cavlc_luma_ac_macroblock(
    const std::vector<std::uint8_t>& rbsp,
    const std::size_t start_bit,
    const std::uint32_t coded_block_pattern_luma,
    const CavlcLumaNeighbourCounts& neighbours) {
    return decode_cavlc_luma_macroblock_impl(
        rbsp, start_bit, coded_block_pattern_luma, neighbours, true);
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

CavlcDecodedIdrSlice decode_baseline_i_idr_slice(
    const std::vector<std::uint8_t>& rbsp,
    const H264BaselineSps& sps,
    const H264BaselinePps& pps) {
    // This is deliberately a narrow traversal contract. parse_baseline_* has
    // already rejected CABAC, FMO, and field pictures; requiring one complete
    // raster slice additionally makes the macroblock-neighbour state explicit
    // and prevents silently applying it to arbitrary multi-slice streams.
    const auto slice_header = parse_baseline_idr_slice_header(rbsp, sps, pps);
    if (slice_header.first_mb_in_slice != 0U) {
        throw std::invalid_argument("native I-slice traversal requires a slice starting at macroblock zero");
    }
    // The SPS struct is public and may be constructed directly, so bound the
    // picture again here before any per-macroblock allocation.
    const auto macroblock_count = validated_picture_macroblock_count(sps);
    const auto width = static_cast<std::size_t>(sps.pic_width_in_mbs_minus1) + 1U;
    if (macroblock_count > rbsp.size() * 8U) {
        throw std::invalid_argument("declared macroblock count exceeds available RBSP bits");
    }

    CavlcDecodedIdrSlice decoded;
    decoded.sps = sps;
    decoded.pps = pps;
    decoded.header = slice_header;
    // Reserve only a modest prefix: a slice that fails early must not have
    // already committed memory for every declared macroblock.
    constexpr std::size_t kMacroblockReserveHint = 8160U;  // 1920x1088
    decoded.macroblocks.reserve(std::min(macroblock_count, kMacroblockReserveHint));
    auto bit_offset = slice_header.data_bit_offset;

    constexpr std::array<std::size_t, 4> kLumaRightEdge{{5, 7, 13, 15}};
    constexpr std::array<std::size_t, 4> kLumaBottomEdge{{10, 11, 14, 15}};
    for (std::size_t address = 0; address < macroblock_count; ++address) {
        CavlcDecodedIMacroblock macroblock;
        macroblock.address = static_cast<std::uint32_t>(address);
        try {
            macroblock.header = parse_baseline_i_macroblock_header(rbsp, bit_offset);
            const auto is_i16x16 = macroblock.header.mb_type >= 1U && macroblock.header.mb_type <= 24U;

            CavlcLumaNeighbourCounts luma_neighbours;
            const auto x = address % width;
            const auto y = address / width;
            luma_neighbours.left_available = x != 0U;
            luma_neighbours.top_available = y != 0U;
            if (luma_neighbours.left_available) {
                const auto& left = decoded.macroblocks.at(address - 1U).luma.blocks;
                for (std::size_t edge = 0; edge < kLumaRightEdge.size(); ++edge) {
                    luma_neighbours.left[edge] = left[kLumaRightEdge[edge]].token.total_coefficients;
                }
            }
            if (luma_neighbours.top_available) {
                const auto& top = decoded.macroblocks.at(address - width).luma.blocks;
                for (std::size_t edge = 0; edge < kLumaBottomEdge.size(); ++edge) {
                    luma_neighbours.top[edge] = top[kLumaBottomEdge[edge]].token.total_coefficients;
                }
            }
            if (is_i16x16) {
                // FFmpeg's CAVLC decoder predicts I16x16 DC through the
                // normal luma block-zero neighbourhood (LUMA_DC maps to
                // index zero for pred_non_zero_count), rather than a
                // separately persisted DC grid.
                const auto left_dc = luma_neighbours.left[0];
                const auto top_dc = luma_neighbours.top[0];
                const auto dc_n_c = luma_neighbours.left_available && luma_neighbours.top_available
                    ? static_cast<int>((left_dc + top_dc + 1U) / 2U)
                    : luma_neighbours.left_available ? static_cast<int>(left_dc)
                    : luma_neighbours.top_available ? static_cast<int>(top_dc)
                    : 0;
                macroblock.luma_dc = decode_cavlc_luma_block(
                    rbsp, macroblock.header.residual_bit_offset, dc_n_c);
                bit_offset = macroblock.luma_dc.tail.next_bit_offset;
                if ((macroblock.header.coded_block_pattern & 0x0fU) != 0U) {
                    macroblock.luma = decode_cavlc_luma_ac_macroblock(
                        rbsp, bit_offset, macroblock.header.coded_block_pattern & 0x0fU, luma_neighbours);
                    bit_offset = macroblock.luma.next_bit_offset;
                } else {
                    macroblock.luma.next_bit_offset = bit_offset;
                }
            } else {
                macroblock.luma = decode_cavlc_luma_macroblock(
                    rbsp, macroblock.header.residual_bit_offset,
                    macroblock.header.coded_block_pattern & 0x0fU, luma_neighbours);
                bit_offset = macroblock.luma.next_bit_offset;
            }

            const auto chroma_coded_block_pattern = (macroblock.header.coded_block_pattern >> 4U) & 0x03U;
            if (chroma_coded_block_pattern >= 1U) {
                macroblock.chroma_dc[0] = decode_cavlc_chroma_dc_block(rbsp, bit_offset);
                bit_offset = macroblock.chroma_dc[0].tail.next_bit_offset;
                macroblock.chroma_dc[1] = decode_cavlc_chroma_dc_block(rbsp, bit_offset);
                bit_offset = macroblock.chroma_dc[1].tail.next_bit_offset;
            }
            if (chroma_coded_block_pattern >= 2U) {
                for (std::size_t component = 0; component < 2; ++component) {
                    for (std::size_t local = 0; local < 4; ++local) {
                        const auto chroma_x = local % 2U;
                        const auto chroma_y = local / 2U;
                        const auto current = component * 4U + local;
                        const auto has_left = chroma_x != 0U || luma_neighbours.left_available;
                        const auto has_top = chroma_y != 0U || luma_neighbours.top_available;
                        const auto n_a = chroma_x != 0U
                            ? macroblock.chroma_ac[current - 1U].token.total_coefficients
                            : (luma_neighbours.left_available
                                ? decoded.macroblocks.at(address - 1U).chroma_ac[component * 4U + chroma_y * 2U + 1U].token.total_coefficients
                                : 0U);
                        const auto n_b = chroma_y != 0U
                            ? macroblock.chroma_ac[current - 2U].token.total_coefficients
                            : (luma_neighbours.top_available
                                ? decoded.macroblocks.at(address - width).chroma_ac[component * 4U + 2U + chroma_x].token.total_coefficients
                                : 0U);
                        const auto n_c = has_left && has_top ? static_cast<int>((n_a + n_b + 1U) / 2U)
                            : has_left ? static_cast<int>(n_a)
                            : has_top ? static_cast<int>(n_b)
                            : 0;
                        macroblock.chroma_ac[current] = decode_cavlc_chroma_ac_block(rbsp, bit_offset, n_c);
                        bit_offset = macroblock.chroma_ac[current].tail.next_bit_offset;
                    }
                }
            }
            macroblock.next_bit_offset = bit_offset;
        } catch (const std::exception& error) {
            throw std::invalid_argument(
                "native I-slice traversal failed at macroblock " + std::to_string(address) +
                " (bit=" + std::to_string(bit_offset) + "): " + error.what());
        }
        decoded.macroblocks.push_back(std::move(macroblock));
    }

    if (bit_offset >= rbsp.size() * 8U || ((rbsp[bit_offset / 8U] >> (7U - bit_offset % 8U)) & 1U) == 0U) {
        throw std::invalid_argument("native I-slice traversal did not reach rbsp_stop_one_bit");
    }
    for (auto trailing = bit_offset + 1U; trailing < rbsp.size() * 8U; ++trailing) {
        if (((rbsp[trailing / 8U] >> (7U - trailing % 8U)) & 1U) != 0U) {
            throw std::invalid_argument("native I-slice traversal found non-zero rbsp trailing alignment bit");
        }
    }
    decoded.rbsp_trailing_bit_offset = bit_offset;
    return decoded;
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

std::uint32_t parameter_set_id(const AnnexBNalUnit& unit) {
    // Only the leading syntax is needed; an SPS id follows three fixed bytes.
    const std::vector<std::uint8_t> prefix(
        unit.payload.begin(),
        unit.payload.begin() + static_cast<std::ptrdiff_t>(std::min<std::size_t>(unit.payload.size(), 32U)));
    const auto rbsp = ebsp_to_rbsp(prefix);
    RbspBitReader reader(rbsp);
    if (unit.nal_unit_type == 7U) {
        reader.skip_bits(24U);  // profile_idc, constraint flags, level_idc
        const auto id = reader.read_ue();
        if (id > 31U) throw std::invalid_argument("SPS id exceeds 31");
        return id;
    }
    if (unit.nal_unit_type == 8U) {
        const auto id = reader.read_ue();
        if (id > 255U) throw std::invalid_argument("PPS id exceeds 255");
        return id;
    }
    throw std::invalid_argument("NAL unit is not an SPS or PPS");
}

void update_parameter_set_context(std::vector<AnnexBNalUnit>& parameter_sets, const AnnexBNalUnit& unit) {
    const auto existing = std::find_if(parameter_sets.begin(), parameter_sets.end(), [&](const auto& item) {
        return item.nal_unit_type == unit.nal_unit_type;
    });
    if (existing == parameter_sets.end()) {
        static_cast<void>(parameter_set_id(unit));
        parameter_sets.push_back(unit);
        return;
    }
    if (parameter_set_id(*existing) != parameter_set_id(unit)) {
        throw std::invalid_argument(unit.nal_unit_type == 7U
            ? "native stream supports a single SPS id; a second SPS id appeared"
            : "native stream supports a single PPS id; a second PPS id appeared");
    }
    *existing = unit;
}

AnnexBNalStreamReader::AnnexBNalStreamReader(
    std::istream& input,
    const std::size_t maximum_nal_bytes)
    : input_(input), maximum_nal_bytes_(maximum_nal_bytes) {
    if (maximum_nal_bytes_ < 5U) {
        throw std::invalid_argument("maximum Annex-B NAL size must be at least five bytes");
    }
    if (maximum_nal_bytes_ > std::numeric_limits<std::size_t>::max() - 65536U) {
        throw std::invalid_argument("maximum Annex-B NAL size is out of range");
    }
    buffer_.reserve(std::min<std::size_t>(maximum_nal_bytes_, 1024U * 1024U));
}

void AnnexBNalStreamReader::compact() {
    if (head_ == 0U) return;
    buffer_.erase(buffer_.begin(), buffer_.begin() + static_cast<std::ptrdiff_t>(head_));
    scan_ = scan_ > head_ ? scan_ - head_ : 0U;
    head_ = 0U;
}

void AnnexBNalStreamReader::read_more() {
    if (eof_) return;
    // Drop already-returned bytes at most once per returned NAL.
    compact();
    auto* source = input_.rdbuf();
    if (source == nullptr) throw std::invalid_argument("Annex-B input stream is unavailable");
    constexpr std::streamsize chunk_size = 64 * 1024;
    // Only request what the stream buffer promises it can deliver without
    // blocking (in_avail), so a live pipe never waits to fill a whole chunk.
    const auto append_available = [&](const std::streamsize limit) {
        const auto available = source->in_avail();
        if (available <= 0 || limit <= 0) return;
        const auto requested = std::min(available, limit);
        const auto old_size = buffer_.size();
        buffer_.resize(old_size + static_cast<std::size_t>(requested));
        const auto received = source->sgetn(
            reinterpret_cast<char*>(buffer_.data() + old_size), requested);
        // in_avail() promised `requested` bytes; anything else is a stream
        // fault, and accepting zero here could spin forever.
        if (received <= 0 || received > requested) {
            buffer_.resize(old_size);
            throw std::invalid_argument("failed while reading Annex-B input stream");
        }
        buffer_.resize(old_size + static_cast<std::size_t>(received));
    };
    if (source->in_avail() > 0) {
        append_available(chunk_size);
        return;
    }
    // Nothing buffered: block for a single byte, then drain anything that
    // arrived with it.
    const auto next = source->sbumpc();
    if (std::char_traits<char>::eq_int_type(next, std::char_traits<char>::eof())) {
        eof_ = true;
        return;
    }
    buffer_.push_back(static_cast<std::uint8_t>(std::char_traits<char>::to_char_type(next)));
    append_available(chunk_size - 1);
}

bool AnnexBNalStreamReader::read_next(std::vector<std::uint8_t>& nal_bytes) {
    nal_bytes.clear();
    const auto marker_at = [](const std::vector<std::uint8_t>& bytes, const std::size_t offset) {
        if (offset + 4U <= bytes.size() && bytes[offset] == 0U && bytes[offset + 1U] == 0U &&
            bytes[offset + 2U] == 0U && bytes[offset + 3U] == 1U) return std::size_t{4U};
        if (offset + 3U <= bytes.size() && bytes[offset] == 0U && bytes[offset + 1U] == 0U &&
            bytes[offset + 2U] == 1U) return std::size_t{3U};
        return std::size_t{0U};
    };

    while (true) {
        if (!started_) {
            // Before the first start code the buffer is trimmed to at most
            // three carried bytes plus one read, so this rescan is bounded.
            compact();
            std::size_t start = 0U;
            while (start < buffer_.size() && marker_at(buffer_, start) == 0U) ++start;
            if (start < buffer_.size()) {
                if (std::any_of(buffer_.begin(), buffer_.begin() + static_cast<std::ptrdiff_t>(start),
                        [](const std::uint8_t byte) { return byte != 0U; })) {
                    throw std::invalid_argument("nonzero bytes precede the first Annex-B start code");
                }
                if (start > 0U) buffer_.erase(buffer_.begin(), buffer_.begin() + static_cast<std::ptrdiff_t>(start));
                started_ = true;
                scan_ = 0U;
            } else {
                if (eof_) {
                    if (buffer_.empty()) return false;
                    throw std::invalid_argument("Annex-B input ended before a start code");
                }
                if (buffer_.size() > 3U) {
                    const auto discard_end = buffer_.end() - 3;
                    if (std::any_of(buffer_.begin(), discard_end,
                            [](const std::uint8_t byte) { return byte != 0U; })) {
                        throw std::invalid_argument("nonzero bytes precede the first Annex-B start code");
                    }
                    buffer_.erase(buffer_.begin(), discard_end);
                }
                read_more();
                continue;
            }
        }

        const auto first_marker_size = marker_at(buffer_, head_);
        if (first_marker_size == 0U) throw std::invalid_argument("Annex-B start code was corrupted");
        // Offsets below scan_ were fully decided by an earlier pass; resume
        // there instead of rescanning the pending NAL from its start.
        scan_ = std::max(scan_, head_ + first_marker_size);
        while (scan_ + 3U <= buffer_.size()) {
            if (marker_at(buffer_, scan_) != 0U) {
                if (scan_ - head_ > maximum_nal_bytes_) {
                    throw std::invalid_argument("Annex-B NAL exceeds configured size limit");
                }
                nal_bytes.assign(buffer_.begin() + static_cast<std::ptrdiff_t>(head_),
                                 buffer_.begin() + static_cast<std::ptrdiff_t>(scan_));
                head_ = scan_;
                return true;
            }
            // 00 00 00 with the fourth byte still unread may become a
            // four-byte start code; leave that offset undecided.
            if (!eof_ && scan_ + 4U > buffer_.size()) break;
            ++scan_;
        }
        if (eof_) {
            const auto pending = buffer_.size() - head_;
            if (pending > maximum_nal_bytes_) throw std::invalid_argument("Annex-B NAL exceeds configured size limit");
            if (pending == 0U) return false;
            nal_bytes.assign(buffer_.begin() + static_cast<std::ptrdiff_t>(head_), buffer_.end());
            buffer_.clear();
            head_ = 0U;
            scan_ = 0U;
            started_ = false;
            return true;
        }
        if (buffer_.size() - head_ > maximum_nal_bytes_ + 3U) {
            throw std::invalid_argument("Annex-B NAL exceeds configured size limit");
        }
        read_more();
    }
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

std::vector<CavlcDecodedIdrSlice> decode_baseline_i_idr_slices(
    const std::vector<std::uint8_t>& annex_b) {
    std::unordered_map<std::uint32_t, H264BaselineSps> sps_by_id;
    std::unordered_map<std::uint32_t, H264BaselinePps> pps_by_id;
    std::vector<CavlcDecodedIdrSlice> decoded_slices;
    const auto units = split_annex_b(annex_b);
    for (std::size_t nal_index = 0; nal_index < units.size(); ++nal_index) {
        const auto& nal = units[nal_index];
        const auto rbsp = nal.rbsp();
        if (nal.nal_unit_type == 7U) {
            const auto sps = parse_baseline_sps(rbsp);
            sps_by_id.insert_or_assign(sps.sequence_parameter_set_id, sps);
            continue;
        }
        if (nal.nal_unit_type == 8U) {
            const auto pps = parse_baseline_pps(rbsp);
            pps_by_id.insert_or_assign(pps.pic_parameter_set_id, pps);
            continue;
        }
        if (!nal.is_idr()) continue;

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
        auto decoded = decode_baseline_i_idr_slice(rbsp, sps_it->second, pps_it->second);
        decoded.nal_index = nal_index;
        decoded_slices.push_back(std::move(decoded));
    }
    return decoded_slices;
}

std::vector<CavlcSignCandidate> collect_cavlc_trailing_one_sign_candidates(
    const std::vector<CavlcDecodedIdrSlice>& slices) {
    std::vector<CavlcSignCandidate> candidates;
    for (const auto& slice : slices) {
        for (const auto& macroblock : slice.macroblocks) {
            const auto append = [&](const CavlcDecodedLumaBlock& block,
                                    const CavlcResidualCategory category,
                                    const std::uint8_t block_index) {
                if (block.token.sign_bit_offsets.empty()) return;
                candidates.push_back(CavlcSignCandidate{
                    slice.nal_index,
                    macroblock.address,
                    category,
                    block_index,
                    block.token.sign_bit_offsets.front(),
                });
            };
            if (macroblock.header.mb_type >= 1U && macroblock.header.mb_type <= 24U) {
                append(macroblock.luma_dc, CavlcResidualCategory::LumaDc, 0U);
            }
            for (std::size_t block_index = 0; block_index < macroblock.luma.blocks.size(); ++block_index) {
                append(macroblock.luma.blocks[block_index], CavlcResidualCategory::Luma4x4,
                       static_cast<std::uint8_t>(block_index));
            }
            for (std::size_t component = 0; component < macroblock.chroma_dc.size(); ++component) {
                append(macroblock.chroma_dc[component], CavlcResidualCategory::ChromaDc,
                       static_cast<std::uint8_t>(component));
            }
            for (std::size_t block_index = 0; block_index < macroblock.chroma_ac.size(); ++block_index) {
                append(macroblock.chroma_ac[block_index], CavlcResidualCategory::ChromaAc,
                       static_cast<std::uint8_t>(block_index));
            }
        }
    }
    return candidates;
}

std::string serialize_cavlc_sign_candidate(const CavlcSignCandidate& candidate) {
    return std::to_string(candidate.nal_index) + ":" +
        std::to_string(candidate.macroblock_address) + ":" +
        std::to_string(static_cast<std::uint8_t>(candidate.category)) + ":" +
        std::to_string(candidate.block_index) + ":" +
        std::to_string(candidate.rbsp_bit_offset);
}

namespace {

void secure_wipe(std::uint8_t* data, const std::size_t size) noexcept {
    if (data == nullptr || size == 0U) return;
#ifdef _WIN32
    SecureZeroMemory(data, size);
#else
    OPENSSL_cleanse(data, size);
#endif
}

class SensitiveBytes {
public:
    explicit SensitiveBytes(std::vector<std::uint8_t> value) : value_(std::move(value)) {}
    SensitiveBytes(const SensitiveBytes&) = delete;
    SensitiveBytes& operator=(const SensitiveBytes&) = delete;
    ~SensitiveBytes() noexcept { secure_wipe(value_.data(), value_.size()); }
    const std::vector<std::uint8_t>& value() const noexcept { return value_; }
    std::vector<std::uint8_t>& value() noexcept { return value_; }

private:
    std::vector<std::uint8_t> value_;
};

void validate_blind_schedule_candidate(const CavlcSignCandidate& candidate) {
    const auto category = static_cast<std::uint8_t>(candidate.category);
    const auto valid_block = (category == 0U && candidate.block_index == 0U) ||
        (category == 1U && candidate.block_index < 16U) ||
        (category == 2U && candidate.block_index < 2U) ||
        (category == 3U && candidate.block_index < 8U);
    if (!valid_block) throw std::invalid_argument("blind schedule candidate category or block index is invalid");
}

#ifdef _WIN32
class CngHashHandle {
public:
    CngHashHandle() = default;
    CngHashHandle(const CngHashHandle&) = delete;
    CngHashHandle& operator=(const CngHashHandle&) = delete;
    CngHashHandle(CngHashHandle&&) = delete;
    CngHashHandle& operator=(CngHashHandle&&) = delete;
    ~CngHashHandle() noexcept {
        if (value != nullptr) static_cast<void>(BCryptDestroyHash(value));
    }
    BCRYPT_HASH_HANDLE value{};
};

// Opening a CNG algorithm provider is far more expensive than one HMAC, so a
// single process-wide provider is opened once (thread-safe static init) and
// intentionally kept for the process lifetime. CNG provider handles may be
// shared between threads; hash objects are per HmacSha256 instance.
struct CngHmacProvider {
    BCRYPT_ALG_HANDLE handle{};
    DWORD object_size{};
    bool reusable{};
};

const CngHmacProvider& cng_hmac_provider() {
    static const CngHmacProvider provider = [] {
        CngHmacProvider opened;
        // BCRYPT_HASH_REUSABLE_FLAG (Windows 8+) lets one keyed hash object
        // be finished and reused; fall back to per-digest hash objects.
        if (BCryptOpenAlgorithmProvider(&opened.handle, BCRYPT_SHA256_ALGORITHM, nullptr,
                BCRYPT_ALG_HANDLE_HMAC_FLAG | BCRYPT_HASH_REUSABLE_FLAG) >= 0) {
            opened.reusable = true;
        } else if (BCryptOpenAlgorithmProvider(&opened.handle, BCRYPT_SHA256_ALGORITHM, nullptr,
                       BCRYPT_ALG_HANDLE_HMAC_FLAG) < 0) {
            throw std::runtime_error("cannot initialize Windows CNG HMAC-SHA-256");
        }
        DWORD result_size = 0;
        const auto status = BCryptGetProperty(
            opened.handle, BCRYPT_OBJECT_LENGTH, reinterpret_cast<PUCHAR>(&opened.object_size),
            sizeof(opened.object_size), &result_size, 0);
        if (status < 0 || result_size != sizeof(opened.object_size)) {
            static_cast<void>(BCryptCloseAlgorithmProvider(opened.handle, 0));
            throw std::runtime_error("cannot query Windows CNG HMAC object length");
        }
        return opened;
    }();
    return provider;
}
#endif

// Keyed HMAC-SHA-256 that amortizes key setup across many messages. Output
// is identical to a one-shot HMAC over the same key and message.
class HmacSha256 {
public:
    explicit HmacSha256(const std::vector<std::uint8_t>& key) : key_(key) {
#ifdef _WIN32
        if (cng_hmac_provider().reusable) create_hash(object_, hash_);
#endif
    }
    HmacSha256(const HmacSha256&) = delete;
    HmacSha256& operator=(const HmacSha256&) = delete;
    HmacSha256(HmacSha256&&) = delete;
    HmacSha256& operator=(HmacSha256&&) = delete;
    ~HmacSha256() = default;

    std::array<std::uint8_t, 32> digest(const std::string_view message) {
        std::array<std::uint8_t, 32> output{};
#ifdef _WIN32
        if (cng_hmac_provider().reusable) {
            finish(hash_.value, message, output);
        } else {
            SensitiveBytes object{std::vector<std::uint8_t>{}};
            CngHashHandle hash;
            create_hash(object, hash);
            finish(hash.value, message, output);
        }
#else
        unsigned int digest_size = 0;
        if (HMAC(EVP_sha256(), key_.value().data(), static_cast<int>(key_.value().size()),
                 reinterpret_cast<const unsigned char*>(message.data()), message.size(),
                 output.data(), &digest_size) == nullptr || digest_size != output.size()) {
            throw std::runtime_error("OpenSSL HMAC-SHA-256 failed");
        }
#endif
        return output;
    }

private:
    SensitiveBytes key_;
#ifdef _WIN32
    // CNG retains the object buffer until BCryptDestroyHash. Declare it
    // before the handle so reverse destruction releases the handle first.
    SensitiveBytes object_{std::vector<std::uint8_t>{}};
    CngHashHandle hash_;

    void create_hash(SensitiveBytes& object, CngHashHandle& hash) const {
        const auto& provider = cng_hmac_provider();
        object.value().resize(provider.object_size);
        const auto status = BCryptCreateHash(
            provider.handle, &hash.value, object.value().data(), static_cast<ULONG>(object.value().size()),
            const_cast<PUCHAR>(key_.value().data()), static_cast<ULONG>(key_.value().size()),
            provider.reusable ? BCRYPT_HASH_REUSABLE_FLAG : 0);
        if (status < 0) throw std::runtime_error("cannot create Windows CNG HMAC");
    }

    static void finish(const BCRYPT_HASH_HANDLE hash, const std::string_view message,
                       std::array<std::uint8_t, 32>& output) {
        const auto data_status = BCryptHashData(
            hash, reinterpret_cast<PUCHAR>(const_cast<char*>(message.data())),
            static_cast<ULONG>(message.size()), 0);
        const auto finish_status = data_status < 0 ? data_status : BCryptFinishHash(
            hash, output.data(), static_cast<ULONG>(output.size()), 0);
        if (finish_status < 0) throw std::runtime_error("Windows CNG HMAC-SHA-256 failed");
    }
#endif
};

// ---- Blind channel protocol v3: HKDF key separation and whitening. The frame
// carries no MAC: the payload's Groth16 proof is what a verifier checks.

constexpr std::size_t kSubkeyBytes = 32U;
constexpr std::size_t kFrameHeaderBytes = 3U;
constexpr std::size_t kKeystreamBlockBits = 256U;
// Key-derivation labels are unchanged from v2, so v3 schedules and keystreams
// equal the v2 ones for the same secret.
constexpr std::string_view kHkdfSalt{"zkstego-cavlc-v2-salt"};
constexpr std::string_view kScheduleInfo{"zkstego/cavlc/v2/schedule"};
constexpr std::string_view kWhiteningInfo{"zkstego/cavlc/v2/whitening"};

std::string_view byte_view(const std::vector<std::uint8_t>& bytes) noexcept {
    return {reinterpret_cast<const char*>(bytes.data()), bytes.size()};
}

// RFC 5869 HKDF-Extract. The returned PRK is secret: callers own and wipe it.
std::vector<std::uint8_t> hkdf_sha256_extract(
    const std::vector<std::uint8_t>& salt,
    const std::vector<std::uint8_t>& input_key_material) {
    const std::vector<std::uint8_t> zero_salt(32U, 0U);
    HmacSha256 hmac(salt.empty() ? zero_salt : salt);
    auto digest = hmac.digest(byte_view(input_key_material));
    std::vector<std::uint8_t> prk(digest.begin(), digest.end());
    secure_wipe(digest.data(), digest.size());
    return prk;
}

// RFC 5869 HKDF-Expand. Every intermediate block is wiped; the returned OKM
// is owned (and wiped) by the caller.
std::vector<std::uint8_t> hkdf_sha256_expand(
    const std::vector<std::uint8_t>& prk,
    const std::string_view info,
    const std::size_t length) {
    if (prk.size() < 32U) throw std::invalid_argument("HKDF pseudorandom key must be at least 32 bytes");
    if (length > 255U * 32U) throw std::invalid_argument("HKDF output length exceeds 255 SHA-256 blocks");
    HmacSha256 hmac(prk);
    std::vector<std::uint8_t> output;
    output.reserve(length + 32U);
    SensitiveBytes block_input(std::vector<std::uint8_t>{});
    block_input.value().reserve(32U + info.size() + 1U);
    std::array<std::uint8_t, 32> block{};
    for (std::size_t counter = 1U; output.size() < length; ++counter) {
        block_input.value().clear();
        if (counter > 1U) block_input.value().insert(block_input.value().end(), block.begin(), block.end());
        block_input.value().insert(block_input.value().end(), info.begin(), info.end());
        block_input.value().push_back(static_cast<std::uint8_t>(counter));
        block = hmac.digest(byte_view(block_input.value()));
        output.insert(output.end(), block.begin(), block.end());
    }
    secure_wipe(block.data(), block.size());
    secure_wipe(output.data() + length, output.size() - length);
    output.resize(length);
    return output;
}

// One v2 subkey of a 32-byte channel secret. The caller wipes the result.
std::vector<std::uint8_t> derive_cavlc_subkey(
    const std::vector<std::uint8_t>& secret_key,
    const std::string_view info) {
    if (secret_key.size() != 32U) throw std::invalid_argument("native CAVLC key must be 32 bytes");
    SensitiveBytes prk(hkdf_sha256_extract(
        std::vector<std::uint8_t>(kHkdfSalt.begin(), kHkdfSalt.end()), secret_key));
    return hkdf_sha256_expand(prk.value(), info, kSubkeyBytes);
}

std::vector<std::uint8_t> bytes_to_msb_bits(const std::vector<std::uint8_t>& bytes) {
    std::vector<std::uint8_t> bits;
    bits.reserve(bytes.size() * 8U);
    for (const auto byte : bytes) {
        for (std::uint8_t shift = 8U; shift-- > 0U;) bits.push_back((byte >> shift) & 1U);
    }
    return bits;
}

std::vector<std::uint8_t> msb_bits_to_bytes(const std::vector<std::uint8_t>& bits) {
    if (bits.size() % 8U != 0U) throw std::invalid_argument("CAVLC frame bits must be byte-aligned");
    std::vector<std::uint8_t> bytes;
    bytes.reserve(bits.size() / 8U);
    for (std::size_t index = 0; index < bits.size(); index += 8U) {
        std::uint8_t byte = 0;
        for (std::size_t offset = 0; offset < 8U; ++offset) {
            if (bits[index + offset] > 1U) throw std::invalid_argument("CAVLC frame bit is invalid");
            byte = static_cast<std::uint8_t>((byte << 1U) | bits[index + offset]);
        }
        bytes.push_back(byte);
    }
    return bytes;
}

// Keystream block j = HMAC-SHA256(whitening_key, uint64_be(j)).
std::array<std::uint8_t, 32> whitening_block(HmacSha256& hmac, const std::uint64_t block_index) {
    std::array<char, 8> counter{};
    for (std::size_t index = 0; index < counter.size(); ++index) {
        counter[index] = static_cast<char>((block_index >> (56U - 8U * index)) & 0xffU);
    }
    return hmac.digest(std::string_view(counter.data(), counter.size()));
}

// Returns bits[i] XOR keystream bit (first_bit_index + i). The bit index is
// global to one frame, so a stream session whitens each segment by passing
// the number of frame bits already carried by earlier segments. XOR is an
// involution: the same call un-whitens extracted bits.
std::vector<std::uint8_t> whiten_cavlc_frame_bits(
    const std::vector<std::uint8_t>& bits,
    const std::vector<std::uint8_t>& whitening_key,
    const std::size_t first_bit_index) {
    std::vector<std::uint8_t> output;
    output.reserve(bits.size());
    if (bits.empty()) return output;
    HmacSha256 hmac(whitening_key);
    std::array<std::uint8_t, 32> block{};
    std::uint64_t loaded_block = 0;
    bool block_loaded = false;
    for (std::size_t index = 0; index < bits.size(); ++index) {
        if (bits[index] > 1U) throw std::invalid_argument("CAVLC frame bit is invalid");
        const auto global_bit = static_cast<std::uint64_t>(first_bit_index) + index;
        const auto block_index = global_bit / kKeystreamBlockBits;
        if (!block_loaded || block_index != loaded_block) {
            block = whitening_block(hmac, block_index);
            loaded_block = block_index;
            block_loaded = true;
        }
        const auto bit_in_block = static_cast<std::size_t>(global_bit % kKeystreamBlockBits);
        const auto key_bit = static_cast<std::uint8_t>((block[bit_in_block / 8U] >> (7U - bit_in_block % 8U)) & 1U);
        output.push_back(static_cast<std::uint8_t>(bits[index] ^ key_bit));
    }
    secure_wipe(block.data(), block.size());
    return output;
}

std::vector<std::uint8_t> pack_frame(const std::vector<std::uint8_t>& payload) {
    if (payload.size() > std::numeric_limits<std::uint16_t>::max()) {
        throw std::invalid_argument("CAVLC payload exceeds 65535 bytes");
    }
    std::vector<std::uint8_t> frame;
    frame.reserve(kFrameHeaderBytes + payload.size());
    frame.push_back(kCavlcFrameVersion);
    frame.push_back(static_cast<std::uint8_t>(payload.size() >> 8U));
    frame.push_back(static_cast<std::uint8_t>(payload.size()));
    frame.insert(frame.end(), payload.begin(), payload.end());
    return frame;
}

std::vector<std::uint8_t> unpack_frame(
    const std::vector<std::uint8_t>& frame,
    const std::size_t maximum_payload_bytes) {
    if (maximum_payload_bytes > std::numeric_limits<std::uint16_t>::max()) {
        throw std::invalid_argument("CAVLC payload maximum exceeds 65535 bytes");
    }
    if (frame.size() < kFrameHeaderBytes || frame[0] != kCavlcFrameVersion) {
        throw std::invalid_argument("CAVLC frame version is invalid");
    }
    const auto payload_size = (static_cast<std::size_t>(frame[1]) << 8U) | frame[2];
    if (payload_size > maximum_payload_bytes || frame.size() != kFrameHeaderBytes + payload_size) {
        throw std::invalid_argument("CAVLC frame length is invalid");
    }
    return {frame.begin() + static_cast<std::ptrdiff_t>(kFrameHeaderBytes), frame.end()};
}

std::vector<CavlcSignCandidate> select_with_schedule_key(
    const std::vector<CavlcSignCandidate>& candidates,
    const std::vector<std::uint8_t>& schedule_key,
    const std::size_t required_bits) {
    if (required_bits > candidates.size()) throw std::invalid_argument("blind schedule capacity is insufficient");
    struct ScoredCandidate { std::array<std::uint8_t, 32> score; std::string identity; CavlcSignCandidate candidate; };
    std::vector<ScoredCandidate> scored;
    scored.reserve(candidates.size());
    std::unordered_set<std::string> identities;
    std::unordered_set<std::string> physical_targets;
    // One keyed HMAC context scores every candidate; each digest equals
    // score_keyed_cavlc_sign_candidate() for the same candidate and secret.
    HmacSha256 ordering_hmac(schedule_key);
    for (const auto& candidate : candidates) {
        validate_blind_schedule_candidate(candidate);
        auto identity = serialize_cavlc_sign_candidate(candidate);
        if (!identities.insert(identity).second) {
            throw std::invalid_argument("blind schedule candidate identity is duplicated");
        }
        const auto physical_target = std::to_string(candidate.nal_index) + ":" +
            std::to_string(candidate.rbsp_bit_offset);
        if (!physical_targets.insert(physical_target).second) {
            throw std::invalid_argument("blind schedule candidate patch target is duplicated");
        }
        const auto score = ordering_hmac.digest(identity);
        scored.push_back({score, std::move(identity), candidate});
    }
    // (score, identity) is a strict total order because identities are unique
    // (checked above), so partially sorting the lowest required_bits yields
    // exactly the same prefix, in the same order, as a full sort.
    std::partial_sort(scored.begin(), scored.begin() + static_cast<std::ptrdiff_t>(required_bits), scored.end(),
        [](const auto& left, const auto& right) {
            return left.score != right.score ? left.score < right.score : left.identity < right.identity;
        });
    std::vector<CavlcSignCandidate> selected;
    selected.reserve(required_bits);
    for (std::size_t index = 0; index < required_bits; ++index) selected.push_back(scored[index].candidate);
    return selected;
}

}  // namespace

std::vector<std::uint8_t> hkdf_sha256(
    const std::vector<std::uint8_t>& salt,
    const std::vector<std::uint8_t>& input_key_material,
    const std::vector<std::uint8_t>& info,
    const std::size_t length) {
    SensitiveBytes prk(hkdf_sha256_extract(salt, input_key_material));
    return hkdf_sha256_expand(prk.value(), byte_view(info), length);
}

std::vector<std::uint8_t> cavlc_whitening_keystream(
    const std::vector<std::uint8_t>& secret_key,
    const std::size_t byte_count) {
    SensitiveBytes whitening_key(derive_cavlc_subkey(secret_key, kWhiteningInfo));
    HmacSha256 hmac(whitening_key.value());
    std::vector<std::uint8_t> keystream;
    keystream.reserve(byte_count + 32U);
    for (std::uint64_t block_index = 0; keystream.size() < byte_count; ++block_index) {
        auto block = whitening_block(hmac, block_index);
        keystream.insert(keystream.end(), block.begin(), block.end());
        secure_wipe(block.data(), block.size());
    }
    secure_wipe(keystream.data() + byte_count, keystream.size() - byte_count);
    keystream.resize(byte_count);
    return keystream;
}

std::array<std::uint8_t, 32> score_keyed_cavlc_sign_candidate(
    const CavlcSignCandidate& candidate,
    const std::vector<std::uint8_t>& secret_key) {
    if (secret_key.size() != 32U) throw std::invalid_argument("blind schedule key must be exactly 32 bytes");
    validate_blind_schedule_candidate(candidate);
    SensitiveBytes schedule_key(derive_cavlc_subkey(secret_key, kScheduleInfo));
    HmacSha256 hmac(schedule_key.value());
    return hmac.digest(serialize_cavlc_sign_candidate(candidate));
}

std::vector<CavlcSignCandidate> select_keyed_cavlc_sign_candidates(
    const std::vector<CavlcSignCandidate>& candidates,
    const std::vector<std::uint8_t>& secret_key,
    const std::size_t required_bits) {
    if (secret_key.size() != 32U) throw std::invalid_argument("blind schedule key must be exactly 32 bytes");
    if (required_bits > candidates.size()) throw std::invalid_argument("blind schedule capacity is insufficient");
    SensitiveBytes schedule_key(derive_cavlc_subkey(secret_key, kScheduleInfo));
    return select_with_schedule_key(candidates, schedule_key.value(), required_bits);
}

std::vector<std::uint8_t> pack_cavlc_frame(const std::vector<std::uint8_t>& payload) {
    return pack_frame(payload);
}

std::vector<std::uint8_t> unpack_cavlc_frame(
    const std::vector<std::uint8_t>& frame,
    const std::size_t maximum_payload_bytes) {
    return unpack_frame(frame, maximum_payload_bytes);
}

namespace {

void wipe_stream_secret(std::vector<std::uint8_t>& value) noexcept {
    volatile auto* bytes = value.data();
    for (std::size_t index = 0; index < value.size(); ++index) bytes[index] = 0U;
}

struct PreparedCavlcStreamSegment {
    std::vector<std::uint8_t> analysis_input;
    std::vector<AnnexBNalUnit> parameter_sets;
    std::vector<CavlcSignCandidate> candidates;
    std::size_t context_nal_count{};
};

PreparedCavlcStreamSegment prepare_cavlc_stream_segment(
    const std::vector<std::uint8_t>& annex_b_segment,
    const std::vector<AnnexBNalUnit>& previous_parameter_sets) {
    const auto units = split_annex_b(annex_b_segment);
    const auto idr_count = std::count_if(units.begin(), units.end(), [](const auto& unit) {
        return unit.is_idr();
    });
    if (idr_count != 1U || std::any_of(units.begin(), units.end(), [](const auto& unit) {
            return unit.nal_unit_type == 1U;
        })) {
        throw std::invalid_argument("stream segment must contain exactly one IDR picture and no P-slices");
    }
    auto parameter_sets = previous_parameter_sets;
    bool saw_idr = false;
    for (const auto& unit : units) {
        if (unit.is_idr()) {
            saw_idr = true;
        } else if (unit.nal_unit_type == 7U || unit.nal_unit_type == 8U) {
            if (saw_idr) throw std::invalid_argument("stream parameter sets must precede the IDR slice");
            update_parameter_set_context(parameter_sets, unit);
        }
    }
    const auto has_parameter_set = [&](const std::uint8_t type) {
        return std::any_of(parameter_sets.begin(), parameter_sets.end(), [&](const auto& item) {
            return item.nal_unit_type == type;
        });
    };
    if (!has_parameter_set(7U) || !has_parameter_set(8U)) {
        throw std::invalid_argument("stream IDR requires SPS/PPS in-band or from prior stream segments");
    }
    auto analysis_units = parameter_sets;
    analysis_units.insert(analysis_units.end(), units.begin(), units.end());
    auto analysis_input = assemble_annex_b(analysis_units);
    const auto slices = decode_baseline_i_idr_slices(analysis_input);
    if (slices.size() != 1U) {
        throw std::invalid_argument("stream segment must contain exactly one supported IDR slice");
    }
    auto candidates = collect_cavlc_trailing_one_sign_candidates(slices);
    return {std::move(analysis_input), std::move(parameter_sets), std::move(candidates),
            analysis_units.size() - units.size()};
}

std::vector<std::uint8_t> extract_keyed_bits_from_candidates(
    const std::vector<std::uint8_t>& annex_b,
    const std::vector<std::uint8_t>& schedule_key,
    const std::vector<CavlcSignCandidate>& candidates,
    const std::size_t payload_bit_count) {
    const auto selected = select_with_schedule_key(candidates, schedule_key, payload_bit_count);
    const auto units = split_annex_b(annex_b);
    std::vector<std::uint8_t> payload_bits;
    payload_bits.reserve(selected.size());
    for (const auto& candidate : selected) {
        if (candidate.nal_index >= units.size()) {
            throw std::invalid_argument("blind schedule candidate NAL is outside the segment");
        }
        const auto rbsp = units[candidate.nal_index].rbsp();
        if (candidate.rbsp_bit_offset >= rbsp.size() * 8U) {
            throw std::invalid_argument("blind schedule candidate bit is outside RBSP");
        }
        payload_bits.push_back(static_cast<std::uint8_t>(
            (rbsp[candidate.rbsp_bit_offset / 8U] >>
             (7U - candidate.rbsp_bit_offset % 8U)) & 1U));
    }
    return payload_bits;
}

std::vector<std::uint8_t> remove_stream_context_prefix(
    const std::vector<std::uint8_t>& annex_b_with_context,
    const std::size_t context_nal_count) {
    auto units = split_annex_b(annex_b_with_context);
    if (context_nal_count > units.size()) {
        throw std::logic_error("stream parameter-set context exceeded patched segment");
    }
    units.erase(units.begin(), units.begin() + static_cast<std::ptrdiff_t>(context_nal_count));
    return assemble_annex_b(units);
}

}  // namespace

CavlcStreamEncoder::CavlcStreamEncoder(
    std::vector<std::uint8_t> secret_key,
    const std::vector<std::uint8_t>& payload,
    const std::size_t maximum_bits_per_segment)
    : maximum_bits_per_segment_(maximum_bits_per_segment) {
    // The caller's secret is wiped as soon as the subkeys exist. The
    // destructor does not run when a constructor throws, so wipe the derived
    // schedule key and any frame material before rethrowing.
    SensitiveBytes secret(std::move(secret_key));
    try {
        if (maximum_bits_per_segment_ == 0U) {
            throw std::invalid_argument("maximum stream bits per segment must be positive");
        }
        if (secret.value().size() != 32U) {
            throw std::invalid_argument("native CAVLC key must be 32 bytes");
        }
        schedule_key_ = derive_cavlc_subkey(secret.value(), kScheduleInfo);
        SensitiveBytes whitening_key(derive_cavlc_subkey(secret.value(), kWhiteningInfo));
        SensitiveBytes frame(pack_frame(payload));
        SensitiveBytes plain_bits(bytes_to_msb_bits(frame.value()));
        frame_bits_ = whiten_cavlc_frame_bits(plain_bits.value(), whitening_key.value(), 0U);
    } catch (...) {
        wipe_stream_secret(schedule_key_);
        wipe_stream_secret(frame_bits_);
        throw;
    }
}

CavlcStreamEncoder::~CavlcStreamEncoder() noexcept {
    wipe_stream_secret(schedule_key_);
    wipe_stream_secret(frame_bits_);
}

CavlcStreamSegment CavlcStreamEncoder::process_segment(
    const std::vector<std::uint8_t>& annex_b_segment) {
    if (complete()) return {annex_b_segment, 0U, 0U, true};
    auto prepared = prepare_cavlc_stream_segment(annex_b_segment, parameter_sets_);
    parameter_sets_ = std::move(prepared.parameter_sets);
    const auto& candidates = prepared.candidates;
    const auto segment_capacity = std::min(maximum_bits_per_segment_, candidates.size());
    if (segment_capacity == 0U) return {annex_b_segment, 0U, 0U, false};

    // The decoder reads all segment_capacity scheduled positions, so the
    // schedule size must stay segment_capacity. Only the first bits_embedded
    // positions carry (whitened) frame bits; positions past the frame end in
    // the final segment keep their cover sign instead of a forced constant.
    const auto bits_embedded = std::min(segment_capacity, remaining_bits());
    const auto selected = select_with_schedule_key(candidates, schedule_key_, segment_capacity);
    auto units = split_annex_b(prepared.analysis_input);
    std::vector<std::vector<FixedLengthBitPatch>> patches_by_nal(units.size());
    for (std::size_t index = 0; index < bits_embedded; ++index) {
        patches_by_nal[selected[index].nal_index].push_back(
            {selected[index].rbsp_bit_offset, {frame_bits_[next_bit_ + index]}});
    }
    std::vector<AnnexBRbspPatchPlan> plan;
    for (std::size_t index = 0; index < patches_by_nal.size(); ++index) {
        if (!patches_by_nal[index].empty()) plan.push_back({index, std::move(patches_by_nal[index])});
    }
    auto patched = patch_annex_b_rbsp_plan(prepared.analysis_input, plan);
    auto output = remove_stream_context_prefix(patched, prepared.context_nal_count);
    next_bit_ += bits_embedded;
    return {std::move(output), segment_capacity, bits_embedded, complete()};
}

bool CavlcStreamEncoder::complete() const noexcept {
    return next_bit_ == frame_bits_.size();
}

std::size_t CavlcStreamEncoder::remaining_bits() const noexcept {
    return frame_bits_.size() - next_bit_;
}

CavlcStreamDecoder::CavlcStreamDecoder(
    std::vector<std::uint8_t> secret_key,
    const std::size_t maximum_payload_bytes,
    const std::size_t maximum_bits_per_segment)
    : maximum_payload_bytes_(maximum_payload_bytes),
      maximum_bits_per_segment_(maximum_bits_per_segment) {
    // The caller's secret is wiped when this scope ends (also on throw); only
    // the derived subkeys are retained.
    SensitiveBytes secret(std::move(secret_key));
    if (secret.value().size() != 32U) throw std::invalid_argument("native CAVLC key must be 32 bytes");
    if (maximum_payload_bytes_ > std::numeric_limits<std::uint16_t>::max()) {
        throw std::invalid_argument("CAVLC payload maximum exceeds 65535 bytes");
    }
    if (maximum_bits_per_segment_ == 0U) {
        throw std::invalid_argument("maximum stream bits per segment must be positive");
    }
    try {
        schedule_key_ = derive_cavlc_subkey(secret.value(), kScheduleInfo);
        whitening_key_ = derive_cavlc_subkey(secret.value(), kWhiteningInfo);
    } catch (...) {
        wipe_stream_secret(schedule_key_);
        wipe_stream_secret(whitening_key_);
        throw;
    }
}

CavlcStreamDecoder::~CavlcStreamDecoder() noexcept {
    wipe_stream_secret(schedule_key_);
    wipe_stream_secret(whitening_key_);
    wipe_stream_secret(collected_bits_);
    if (payload_.has_value()) wipe_stream_secret(*payload_);
}

void CavlcStreamDecoder::consume_segment(
    const std::vector<std::uint8_t>& annex_b_segment) {
    if (complete()) return;
    if (failed_) throw std::invalid_argument(failure_reason_);
    try {
        auto prepared = prepare_cavlc_stream_segment(annex_b_segment, parameter_sets_);
        parameter_sets_ = std::move(prepared.parameter_sets);
        const auto& candidates = prepared.candidates;
        const auto segment_bit_count = std::min(maximum_bits_per_segment_, candidates.size());
        if (segment_bit_count == 0U) return;
        // Un-whiten with the global frame bit index (bits already collected
        // from earlier segments), so the 24-bit header below is parsed from
        // plaintext; a wrong key yields a keystream-random version byte.
        SensitiveBytes segment_bits(whiten_cavlc_frame_bits(
            extract_keyed_bits_from_candidates(prepared.analysis_input, schedule_key_, candidates, segment_bit_count),
            whitening_key_, collected_bits_.size()));
        for (const auto bit : segment_bits.value()) {
            if (expected_frame_bits_.has_value() && collected_bits_.size() >= *expected_frame_bits_) break;
            collected_bits_.push_back(bit);
            if (!expected_frame_bits_.has_value() && collected_bits_.size() == kFrameHeaderBytes * 8U) {
                const auto header = msb_bits_to_bytes(collected_bits_);
                if (header[0] != kCavlcFrameVersion) {
                    throw std::invalid_argument("CAVLC stream version is invalid");
                }
                const auto payload_size = (static_cast<std::size_t>(header[1]) << 8U) | header[2];
                if (payload_size > maximum_payload_bytes_) {
                    throw std::invalid_argument("CAVLC stream length exceeds configured maximum");
                }
                expected_frame_bits_ = (kFrameHeaderBytes + payload_size) * 8U;
            }
            if (expected_frame_bits_.has_value() && collected_bits_.size() == *expected_frame_bits_) {
                payload_ = unpack_frame(msb_bits_to_bytes(collected_bits_), maximum_payload_bytes_);
                break;
            }
        }
    } catch (const std::exception& error) {
        failed_ = true;
        failure_reason_ = error.what();
        wipe_stream_secret(collected_bits_);
        collected_bits_.clear();
        expected_frame_bits_.reset();
        parameter_sets_.clear();
        throw;
    }
}

const std::vector<std::uint8_t>& CavlcStreamDecoder::payload() const {
    if (!payload_.has_value()) throw std::logic_error("CAVLC stream is incomplete");
    return *payload_;
}

std::vector<std::uint8_t> assemble_cavlc_stream_segment(
    const std::vector<AnnexBNalUnit>& parameter_sets,
    const AnnexBNalUnit& idr) {
    if (!idr.is_idr()) throw std::invalid_argument("stream segment must end with an IDR slice");
    auto units = parameter_sets;
    units.push_back(idr);
    return assemble_annex_b(units);
}

namespace {

// Walks a whole Annex-B file in segment-protocol order. visit(file_index, unit,
// segment, context) runs for every NAL unit; segment is the assembled
// SPS/PPS-context + IDR stream segment for IDR units and null otherwise, and
// context is the parameter-set context it was assembled from. Returning false
// stops the walk. Returns the number of IDR segments visited.
template <class Visitor>
std::size_t visit_cavlc_stream_file(const std::vector<std::uint8_t>& annex_b, Visitor&& visit) {
    const auto units = split_annex_b(annex_b);
    if (units.empty()) throw std::invalid_argument("input contains no Annex-B NAL units");
    std::vector<AnnexBNalUnit> parameter_sets;
    std::size_t idr_count = 0;
    for (std::size_t index = 0; index < units.size(); ++index) {
        const auto& unit = units[index];
        if (unit.nal_unit_type == 7U || unit.nal_unit_type == 8U) {
            update_parameter_set_context(parameter_sets, unit);
        }
        if (!unit.is_idr()) {
            if (!visit(index, unit, static_cast<const std::vector<std::uint8_t>*>(nullptr), parameter_sets)) break;
            continue;
        }
        ++idr_count;
        const auto segment = assemble_cavlc_stream_segment(parameter_sets, unit);
        if (!visit(index, unit, &segment, parameter_sets)) break;
    }
    return idr_count;
}

std::vector<std::uint8_t> single_idr_payload(const std::vector<std::uint8_t>& patched_segment) {
    const auto units = split_annex_b(patched_segment);
    const auto is_idr = [](const AnnexBNalUnit& unit) { return unit.is_idr(); };
    const auto idr = std::find_if(units.begin(), units.end(), is_idr);
    if (idr == units.end() || std::find_if(std::next(idr), units.end(), is_idr) != units.end()) {
        throw std::invalid_argument("native stream patch did not return exactly one IDR slice");
    }
    return idr->payload;
}

}  // namespace

std::vector<std::uint8_t> embed_cavlc_stream_file(
    const std::vector<std::uint8_t>& annex_b,
    const std::vector<std::uint8_t>& secret_key,
    const std::vector<std::uint8_t>& payload,
    const std::size_t maximum_bits_per_segment) {
    CavlcStreamEncoder encoder(secret_key, payload, maximum_bits_per_segment);
    std::vector<AnnexBNalUnit> output_units;
    const auto idr_count = visit_cavlc_stream_file(annex_b,
        [&](std::size_t, const AnnexBNalUnit& unit, const std::vector<std::uint8_t>* segment,
            const std::vector<AnnexBNalUnit>&) {
            if (segment == nullptr || encoder.complete()) {
                output_units.push_back(unit);
                return true;
            }
            auto output_idr = unit;
            output_idr.payload = single_idr_payload(encoder.process_segment(*segment).output);
            output_units.push_back(std::move(output_idr));
            return true;
        });
    if (idr_count == 0U) throw std::invalid_argument("input contains no IDR slices");
    if (!encoder.complete()) throw std::invalid_argument("IDR stream capacity is insufficient for payload");
    return assemble_annex_b(output_units);
}

std::vector<std::uint8_t> extract_cavlc_stream_file(
    const std::vector<std::uint8_t>& annex_b,
    const std::vector<std::uint8_t>& secret_key,
    const std::size_t maximum_payload_bytes,
    const std::size_t maximum_bits_per_segment) {
    CavlcStreamDecoder decoder(secret_key, maximum_payload_bytes, maximum_bits_per_segment);
    const auto idr_count = visit_cavlc_stream_file(annex_b,
        [&](std::size_t, const AnnexBNalUnit&, const std::vector<std::uint8_t>* segment,
            const std::vector<AnnexBNalUnit>&) {
            if (segment != nullptr) decoder.consume_segment(*segment);
            return !decoder.complete();
        });
    if (idr_count == 0U) throw std::invalid_argument("input contains no IDR slices");
    if (!decoder.complete()) throw std::invalid_argument("IDR stream ended before payload was complete");
    return decoder.payload();
}

std::vector<CavlcStreamSegmentCandidates> analyze_cavlc_stream_file(
    const std::vector<std::uint8_t>& annex_b) {
    // Mirrors CavlcStreamEncoder::process_segment: the codec keeps
    // its own parameter-set context and prepares each segment identically.
    std::vector<AnnexBNalUnit> codec_parameter_sets;
    std::vector<CavlcStreamSegmentCandidates> segments;
    const auto idr_count = visit_cavlc_stream_file(annex_b,
        [&](const std::size_t file_index, const AnnexBNalUnit&, const std::vector<std::uint8_t>* segment,
            const std::vector<AnnexBNalUnit>& context) {
            if (segment == nullptr) return true;
            auto prepared = prepare_cavlc_stream_segment(*segment, codec_parameter_sets);
            codec_parameter_sets = std::move(prepared.parameter_sets);
            // The segment is context + IDR, and the analysis input prepends
            // context_nal_count stored parameter sets to the segment.
            const auto analysis_nal_index = prepared.context_nal_count + context.size();
            for (const auto& candidate : prepared.candidates) {
                if (candidate.nal_index != analysis_nal_index) {
                    throw std::logic_error("stream segment candidate is outside the segment IDR");
                }
            }
            segments.push_back({file_index, analysis_nal_index, std::move(prepared.candidates)});
            return true;
        });
    if (idr_count == 0U) throw std::invalid_argument("input contains no IDR slices");
    return segments;
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
