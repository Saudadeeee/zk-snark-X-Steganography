#pragma once

#include <cstddef>
#include <cstdint>
#include <vector>

namespace zkstego {

struct FixedLengthBitPatch {
    std::size_t bit_offset;
    std::vector<std::uint8_t> bits;
};

std::vector<std::uint8_t> ebsp_to_rbsp(const std::vector<std::uint8_t>& ebsp);
std::vector<std::uint8_t> rbsp_to_ebsp(const std::vector<std::uint8_t>& rbsp);
std::vector<std::uint8_t> apply_fixed_length_patches(
    const std::vector<std::uint8_t>& source,
    const std::vector<FixedLengthBitPatch>& patches);

}  // namespace zkstego
