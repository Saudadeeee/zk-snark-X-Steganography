#pragma once

#include <cstddef>
#include <cstdint>
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
    std::int32_t slice_qp_delta{};
    std::size_t data_bit_offset{};
};

struct CavlcCoeffToken {
    std::uint32_t total_coefficients{};
    std::uint32_t trailing_ones{};
    std::vector<std::size_t> sign_bit_offsets;
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
