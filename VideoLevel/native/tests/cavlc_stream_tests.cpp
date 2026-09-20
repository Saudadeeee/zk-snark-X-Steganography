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

    const std::vector<std::uint8_t> annex_b{
        0x00, 0x00, 0x00, 0x01, 0x67, 0x42, 0x00, 0x1e,
        0x00, 0x00, 0x01, 0x68, 0xce, 0x06,
        0x00, 0x00, 0x01, 0x65, 0x88, 0x00, 0x00, 0x03, 0x01,
    };
    const auto nals = zkstego::split_annex_b(annex_b);
    assert(nals.size() == 3);
    assert(nals[0].nal_unit_type == 7 && nals[0].payload == std::vector<std::uint8_t>({0x42, 0x00, 0x1e}));
    assert(nals[1].nal_unit_type == 8);
    assert(nals[2].is_idr());
    assert(nals[2].rbsp() == std::vector<std::uint8_t>({0x88, 0x00, 0x00, 0x01}));
    assert(zkstego::assemble_annex_b(nals) == annex_b);

    const auto patched_annex_b = zkstego::patch_annex_b_nal_rbsp(
        annex_b,
        2,
        {{8, {1, 1, 1, 1, 1, 1, 1, 1}}});
    const auto patched_nals = zkstego::split_annex_b(patched_annex_b);
    assert(patched_nals.size() == 3);
    assert(patched_nals[0].payload == nals[0].payload);
    assert(patched_nals[1].payload == nals[1].payload);
    assert(patched_nals[2].rbsp() == std::vector<std::uint8_t>({0x88, 0xff, 0x00, 0x01}));

    const auto patched_segment = zkstego::patch_annex_b_rbsp_plan(
        annex_b,
        {{0, {{0, {1}}}}, {2, {{8, {1, 1, 1, 1, 1, 1, 1, 1}}}}});
    const auto segment_nals = zkstego::split_annex_b(patched_segment);
    assert(segment_nals[0].rbsp() == std::vector<std::uint8_t>({0xc2, 0x00, 0x1e}));
    assert(segment_nals[1].payload == nals[1].payload);
    assert(segment_nals[2].rbsp() == std::vector<std::uint8_t>({0x88, 0xff, 0x00, 0x01}));
}
