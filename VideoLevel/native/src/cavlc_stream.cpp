#include "zkstego/cavlc_stream.hpp"

#include <stdexcept>

namespace zkstego {

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

}  // namespace zkstego
