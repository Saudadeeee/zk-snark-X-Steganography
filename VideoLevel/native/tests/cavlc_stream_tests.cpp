#include "zkstego/cavlc_stream.hpp"

#include <cassert>
#include <cstdint>
#include <vector>

int main() {
    const std::vector<std::uint8_t> ebsp{0x12, 0x00, 0x00, 0x03, 0x01, 0x34};
    const auto rbsp = zkstego::ebsp_to_rbsp(ebsp);
    assert((rbsp == std::vector<std::uint8_t>{0x12, 0x00, 0x00, 0x01, 0x34}));
    assert(zkstego::rbsp_to_ebsp(rbsp) == ebsp);

    const std::vector<std::uint8_t> source{0b10110000};
    const auto patched = zkstego::apply_fixed_length_patches(source, {{2, {0, 1, 1}}});
    assert(patched.size() == source.size());
    assert(patched[0] == 0b10011000);
}
