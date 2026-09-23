#pragma once

#include <cstddef>
#include <cstdint>
#include <array>
#include <stdexcept>
#include <utility>
#include <vector>

namespace zkstego {

class RbspBitReader {
public:
    explicit RbspBitReader(std::vector<std::uint8_t> bytes) : bytes_(std::move(bytes)) {}
    [[nodiscard]] std::size_t position() const noexcept { return position_; }
    [[nodiscard]] std::size_t remaining_bits() const noexcept { return bytes_.size() * 8 - position_; }
    void skip_bits(std::size_t count) {
        if (count > remaining_bits()) throw std::out_of_range("RBSP bit skip past end");
        position_ += count;
    }
    [[nodiscard]] std::uint8_t read_bit() {
        if (position_ >= bytes_.size() * 8) throw std::out_of_range("RBSP bit read past end");
        const auto bit = static_cast<std::uint8_t>((bytes_[position_ / 8] >> (7 - position_ % 8)) & 1U);
        ++position_;
        return bit;
    }
    [[nodiscard]] std::uint32_t read_bits(std::size_t count) {
        if (count > 32) throw std::invalid_argument("RBSP read_bits count exceeds 32");
        std::uint32_t value = 0;
        for (std::size_t i = 0; i < count; ++i) value = (value << 1U) | read_bit();
        return value;
    }
    [[nodiscard]] std::uint32_t read_ue() {
        std::size_t zeros = 0;
        while (read_bit() == 0) { if (++zeros > 31) throw std::invalid_argument("invalid RBSP ue(v)"); }
        return zeros == 0 ? 0 : ((1U << zeros) - 1U + read_bits(zeros));
    }
    [[nodiscard]] std::int32_t read_se() {
        const auto code_num = read_ue();
        if ((code_num & 1U) != 0U) {
            return static_cast<std::int32_t>((code_num + 1U) / 2U);
        }
        return -static_cast<std::int32_t>(code_num / 2U);
    }
private:
    std::vector<std::uint8_t> bytes_;
    std::size_t position_{};
};

struct FixedLengthBitPatch {
    std::size_t bit_offset;
    std::vector<std::uint8_t> bits;
};

struct AnnexBRbspPatchPlan {
    std::size_t nal_index;
    std::vector<FixedLengthBitPatch> patches;
};

struct H264BaselineSps {
    std::uint8_t profile_idc{};
    std::uint8_t level_idc{};
    std::uint32_t sequence_parameter_set_id{};
    std::uint32_t log2_max_frame_num_minus4{};
    std::uint32_t pic_order_cnt_type{};
    std::uint32_t log2_max_pic_order_cnt_lsb_minus4{};
    bool frame_mbs_only_flag{};
    std::uint32_t pic_width_in_mbs_minus1{};
    std::uint32_t pic_height_in_map_units_minus1{};
};

struct H264BaselinePps {
    std::uint32_t pic_parameter_set_id{};
    std::uint32_t sequence_parameter_set_id{};
    bool entropy_coding_mode_flag{};
    std::uint32_t num_slice_groups_minus1{};
    std::uint32_t num_ref_idx_l0_default_active_minus1{};
    std::uint32_t num_ref_idx_l1_default_active_minus1{};
    std::int32_t pic_init_qp_minus26{};
    bool deblocking_filter_control_present_flag{};
    bool redundant_pic_cnt_present_flag{};
};

struct H264BaselineIdrSliceHeader {
    std::uint32_t first_mb_in_slice{};
    std::uint32_t slice_type{};
    std::uint32_t pic_parameter_set_id{};
    std::uint32_t frame_num{};
    std::uint32_t idr_pic_id{};
    std::uint32_t pic_order_cnt_lsb{};
    std::int32_t slice_qp_delta{};
    std::size_t data_bit_offset{};
};

struct CavlcCoeffToken {
    std::uint32_t total_coefficients{};
    std::uint32_t trailing_ones{};
    std::vector<std::size_t> sign_bit_offsets;
    std::size_t level_bit_offset{};
};

struct CavlcDecodedLevels {
    // CAVLC signals trailing-one signs before the remaining levels, in reverse scan order.
    std::vector<std::int32_t> trailing_one_values;
    std::vector<std::int32_t> values;
    std::size_t next_bit_offset{};
};

struct CavlcResidualTail {
    std::uint32_t total_zeros{};
    std::vector<std::uint32_t> runs;
    std::size_t next_bit_offset{};
};

struct CavlcDecodedLumaBlock {
    CavlcCoeffToken token;
    CavlcDecodedLevels levels;
    CavlcResidualTail tail;
    std::vector<std::int32_t> coefficients;
};

struct CavlcDecodedLumaMacroblock {
    std::array<CavlcDecodedLumaBlock, 16> blocks;
    std::size_t next_bit_offset{};
};

struct CavlcLumaNeighbourCounts {
    // Valid only for the locked progressive, single-slice raster profile.
    // Callers must derive availability from the slice, not merely from frame
    // position; FMO and MBAFF are intentionally outside this primitive.
    bool left_available{};
    bool top_available{};
    // TotalCoeff values at the left MB's x=3 edge and top MB's y=3 edge,
    // indexed by luma 4x4 raster coordinate. Values must be in [0, 16].
    std::array<std::uint32_t, 4> left{};
    std::array<std::uint32_t, 4> top{};
};

struct H264BaselineIMacroblockHeader {
    std::uint32_t mb_type{};
    std::uint32_t coded_block_pattern{};
    std::int32_t mb_qp_delta{};
    std::array<std::int8_t, 16> intra_4x4_prediction_modes{};
    std::size_t residual_bit_offset{};
};

struct CavlcDecodedIMacroblock {
    std::uint32_t address{};
    H264BaselineIMacroblockHeader header;
    // Parsed only for I16x16. Its nC context follows the normal luma
    // block-zero neighbour mapping used by CAVLC decoders.
    CavlcDecodedLumaBlock luma_dc;
    CavlcDecodedLumaMacroblock luma;
    std::array<CavlcDecodedLumaBlock, 2> chroma_dc;
    std::array<CavlcDecodedLumaBlock, 8> chroma_ac;
    std::size_t next_bit_offset{};
};

struct CavlcDecodedIdrSlice {
    std::size_t nal_index{};
    H264BaselineSps sps;
    H264BaselinePps pps;
    H264BaselineIdrSliceHeader header;
    std::vector<CavlcDecodedIMacroblock> macroblocks;
    std::size_t rbsp_trailing_bit_offset{};
};

enum class CavlcResidualCategory : std::uint8_t {
    LumaDc,
    Luma4x4,
    ChromaDc,
    ChromaAc,
};

// A trailing-one sign bit is a bit-exact, length-invariant CAVLC candidate:
// flipping it changes only coefficient sign, never coeff_token or residual
// block length. One candidate is emitted per residual block.
struct CavlcSignCandidate {
    std::size_t nal_index{};
    std::uint32_t macroblock_address{};
    CavlcResidualCategory category{};
    std::uint8_t block_index{};
    std::size_t rbsp_bit_offset{};
};

struct H264BaselineIdrNalHeader {
    std::size_t nal_index{};
    H264BaselineIdrSliceHeader slice_header;
    H264BaselineIMacroblockHeader first_macroblock;
    CavlcDecodedLumaBlock first_luma_block;
};

struct AnnexBNalUnit {
    std::size_t start_offset{};
    std::size_t start_code_size{};
    std::uint8_t forbidden_zero_bit{};
    std::uint8_t nal_ref_idc{};
    std::uint8_t nal_unit_type{};
    std::vector<std::uint8_t> payload;

    [[nodiscard]] bool is_idr() const noexcept { return nal_unit_type == 5; }
    [[nodiscard]] std::vector<std::uint8_t> rbsp() const;
};

std::vector<std::uint8_t> ebsp_to_rbsp(const std::vector<std::uint8_t>& ebsp);
std::vector<std::uint8_t> rbsp_to_ebsp(const std::vector<std::uint8_t>& rbsp);
H264BaselineSps parse_baseline_sps(const std::vector<std::uint8_t>& rbsp);
H264BaselinePps parse_baseline_pps(const std::vector<std::uint8_t>& rbsp);
H264BaselineIdrSliceHeader parse_baseline_idr_slice_header(
    const std::vector<std::uint8_t>& rbsp,
    const H264BaselineSps& sps,
    const H264BaselinePps& pps);
CavlcCoeffToken parse_cavlc_coeff_token(
    const std::vector<std::uint8_t>& rbsp,
    std::size_t start_bit,
    int n_c);
CavlcDecodedLevels decode_cavlc_non_trailing_levels(
    const std::vector<std::uint8_t>& rbsp,
    const CavlcCoeffToken& token);
std::vector<std::int32_t> reconstruct_cavlc_block(
    const CavlcDecodedLevels& decoded_levels,
    const std::vector<std::uint32_t>& runs,
    std::size_t max_num_coefficients);
CavlcResidualTail decode_cavlc_tail_tc4(
    const std::vector<std::uint8_t>& rbsp,
    std::size_t start_bit);
CavlcResidualTail decode_cavlc_residual_tail(
    const std::vector<std::uint8_t>& rbsp,
    std::size_t start_bit,
    std::uint32_t total_coefficients,
    std::size_t max_num_coefficients);
CavlcResidualTail decode_cavlc_luma_residual_tail(
    const std::vector<std::uint8_t>& rbsp,
    std::size_t start_bit,
    std::uint32_t total_coefficients);
CavlcResidualTail decode_cavlc_chroma_dc_residual_tail(
    const std::vector<std::uint8_t>& rbsp,
    std::size_t start_bit,
    std::uint32_t total_coefficients);
CavlcDecodedLumaBlock decode_cavlc_luma_block(
    const std::vector<std::uint8_t>& rbsp,
    std::size_t start_bit,
    int n_c);
CavlcDecodedLumaBlock decode_cavlc_luma_ac_block(
    const std::vector<std::uint8_t>& rbsp,
    std::size_t start_bit,
    int n_c);
CavlcDecodedLumaBlock decode_cavlc_chroma_dc_block(
    const std::vector<std::uint8_t>& rbsp,
    std::size_t start_bit);
CavlcDecodedLumaBlock decode_cavlc_chroma_ac_block(
    const std::vector<std::uint8_t>& rbsp,
    std::size_t start_bit,
    int n_c);
CavlcDecodedLumaMacroblock decode_cavlc_luma_macroblock(
    const std::vector<std::uint8_t>& rbsp,
    std::size_t start_bit,
    std::uint32_t coded_block_pattern_luma);
CavlcDecodedLumaMacroblock decode_cavlc_luma_macroblock(
    const std::vector<std::uint8_t>& rbsp,
    std::size_t start_bit,
    std::uint32_t coded_block_pattern_luma,
    const CavlcLumaNeighbourCounts& neighbours);
CavlcDecodedLumaMacroblock decode_cavlc_luma_ac_macroblock(
    const std::vector<std::uint8_t>& rbsp,
    std::size_t start_bit,
    std::uint32_t coded_block_pattern_luma,
    const CavlcLumaNeighbourCounts& neighbours);
CavlcDecodedIdrSlice decode_baseline_i_idr_slice(
    const std::vector<std::uint8_t>& rbsp,
    const H264BaselineSps& sps,
    const H264BaselinePps& pps);
std::vector<CavlcDecodedIdrSlice> decode_baseline_i_idr_slices(
    const std::vector<std::uint8_t>& annex_b);
std::vector<CavlcSignCandidate> collect_cavlc_trailing_one_sign_candidates(
    const std::vector<CavlcDecodedIdrSlice>& slices);
std::string serialize_cavlc_sign_candidate(const CavlcSignCandidate& candidate);
std::array<std::uint8_t, 32> score_keyed_cavlc_sign_candidate(
    const CavlcSignCandidate& candidate,
    const std::vector<std::uint8_t>& secret_key);
std::vector<CavlcSignCandidate> select_keyed_cavlc_sign_candidates(
    const std::vector<CavlcSignCandidate>& candidates,
    const std::vector<std::uint8_t>& secret_key,
    std::size_t required_bits);
std::vector<std::uint8_t> embed_keyed_cavlc_sign_bits(
    const std::vector<std::uint8_t>& annex_b,
    const std::vector<std::uint8_t>& secret_key,
    const std::vector<std::uint8_t>& payload_bits);
std::vector<std::uint8_t> extract_keyed_cavlc_sign_bits(
    const std::vector<std::uint8_t>& annex_b,
    const std::vector<std::uint8_t>& secret_key,
    std::size_t payload_bit_count);
std::vector<std::int32_t> reconstruct_cavlc_tc4_no_trailing(
    const std::vector<std::int32_t>& decoded_non_trailing_levels,
    const std::vector<std::uint32_t>& runs);
H264BaselineIMacroblockHeader parse_baseline_i_macroblock_header(
    const std::vector<std::uint8_t>& rbsp,
    std::size_t start_bit);
std::vector<H264BaselineIdrNalHeader> inspect_baseline_idr_headers(
    const std::vector<std::uint8_t>& annex_b);
std::vector<AnnexBNalUnit> split_annex_b(const std::vector<std::uint8_t>& annex_b);
std::vector<std::uint8_t> assemble_annex_b(const std::vector<AnnexBNalUnit>& units);
std::vector<std::uint8_t> apply_fixed_length_patches(
    const std::vector<std::uint8_t>& source,
    const std::vector<FixedLengthBitPatch>& patches);
std::vector<std::uint8_t> patch_annex_b_nal_rbsp(
    const std::vector<std::uint8_t>& annex_b,
    std::size_t nal_index,
    const std::vector<FixedLengthBitPatch>& patches);
std::vector<std::uint8_t> patch_annex_b_rbsp_plan(
    const std::vector<std::uint8_t>& annex_b,
    const std::vector<AnnexBRbspPatchPlan>& plan);

}  // namespace zkstego
