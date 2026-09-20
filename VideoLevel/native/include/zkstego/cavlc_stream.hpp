#pragma once

#include <cstddef>
#include <cstdint>
#include <vector>

namespace zkstego {

struct FixedLengthBitPatch {
    std::size_t bit_offset;
    std::vector<std::uint8_t> bits;
};

struct AnnexBNalUnit {
    std::size_t start_offset{};
    std::uint8_t nal_ref_idc{};
    std::uint8_t nal_unit_type{};
    std::vector<std::uint8_t> payload;

    [[nodiscard]] bool is_idr() const noexcept { return nal_unit_type == 5; }
    [[nodiscard]] std::vector<std::uint8_t> rbsp() const;
};

std::vector<std::uint8_t> ebsp_to_rbsp(const std::vector<std::uint8_t>& ebsp);
std::vector<std::uint8_t> rbsp_to_ebsp(const std::vector<std::uint8_t>& rbsp);
std::vector<AnnexBNalUnit> split_annex_b(const std::vector<std::uint8_t>& annex_b);
std::vector<std::uint8_t> apply_fixed_length_patches(
    const std::vector<std::uint8_t>& source,
    const std::vector<FixedLengthBitPatch>& patches);

}  // namespace zkstego
