#include "zkstego/cavlc_stream.hpp"

#include <cstdint>
#include <vector>

#define CHECK(condition) do { if (!(condition)) return __LINE__; } while (false)

int main() {
    zkstego::RbspBitReader reader({0b10100110});
    CHECK(reader.read_bits(3) == 0b101);
    CHECK(reader.position() == 3);
    CHECK(reader.remaining_bits() == 5);
    CHECK(reader.read_bit() == 0);
    CHECK(reader.read_ue() == 2);  // remaining bits: 0110 -> ue(v)=2
    CHECK(reader.remaining_bits() == 1);

    zkstego::RbspBitReader skipping_reader({0b10100110});
    skipping_reader.skip_bits(5);
    CHECK(skipping_reader.position() == 5);
    CHECK(skipping_reader.read_bits(3) == 0b110);

    zkstego::RbspBitReader signed_reader({0b01100000});
    CHECK(signed_reader.read_se() == -1);  // ue(v)=2 maps to se(v)=-1

    zkstego::RbspBitReader signed_minimum_reader({0x00, 0x00, 0x00, 0x01, 0xff, 0xff, 0xff, 0xff});
    CHECK(signed_minimum_reader.read_se() == -2147483647);

    const auto sps = zkstego::parse_baseline_sps({
        0x42, 0xc0, 0x0d, 0xdc, 0x16, 0x09, 0x6f, 0xfc,
        0x02, 0x00, 0x01, 0xd4, 0x40, 0x00, 0x00, 0xfa,
        0x40, 0x00, 0x3a, 0x98, 0x03, 0xc5, 0x0a, 0xe0,
    });
    CHECK(sps.profile_idc == 66);
    CHECK(sps.log2_max_frame_num_minus4 == 0);
    CHECK(sps.pic_order_cnt_type == 2);
    CHECK(sps.frame_mbs_only_flag);
    CHECK(sps.pic_width_in_mbs_minus1 == 21);
    CHECK(sps.pic_height_in_map_units_minus1 == 17);

    const std::vector<std::uint8_t> ebsp{0x12, 0x00, 0x00, 0x03, 0x01, 0x34};
    const auto rbsp = zkstego::ebsp_to_rbsp(ebsp);
    CHECK((rbsp == std::vector<std::uint8_t>{0x12, 0x00, 0x00, 0x01, 0x34}));
    CHECK(zkstego::rbsp_to_ebsp(rbsp) == ebsp);

    const std::vector<std::uint8_t> source{0b10110000};
    const auto patched = zkstego::apply_fixed_length_patches(source, {{2, {0, 1, 1}}});
    CHECK(patched.size() == source.size());
    CHECK(patched[0] == 0b10011000);

    const std::vector<std::uint8_t> annex_b{
        0x00, 0x00, 0x00, 0x01, 0x67, 0x42, 0x00, 0x1e,
        0x00, 0x00, 0x01, 0x68, 0xce, 0x06,
        0x00, 0x00, 0x01, 0x65, 0x88, 0x00, 0x00, 0x03, 0x01,
    };
    const auto nals = zkstego::split_annex_b(annex_b);
    CHECK(nals.size() == 3);
    CHECK(nals[0].nal_unit_type == 7 && nals[0].payload == std::vector<std::uint8_t>({0x42, 0x00, 0x1e}));
    CHECK(nals[1].nal_unit_type == 8);
    CHECK(nals[2].is_idr());
    CHECK(nals[2].rbsp() == std::vector<std::uint8_t>({0x88, 0x00, 0x00, 0x01}));
    CHECK(zkstego::assemble_annex_b(nals) == annex_b);

    const auto patched_annex_b = zkstego::patch_annex_b_nal_rbsp(
        annex_b,
        2,
        {{8, {1, 1, 1, 1, 1, 1, 1, 1}}});
    const auto patched_nals = zkstego::split_annex_b(patched_annex_b);
    CHECK(patched_nals.size() == 3);
    CHECK(patched_nals[0].payload == nals[0].payload);
    CHECK(patched_nals[1].payload == nals[1].payload);
    CHECK(patched_nals[2].rbsp() == std::vector<std::uint8_t>({0x88, 0xff, 0x00, 0x01}));

    const auto patched_segment = zkstego::patch_annex_b_rbsp_plan(
        annex_b,
        {{0, {{0, {1}}}}, {2, {{8, {1, 1, 1, 1, 1, 1, 1, 1}}}}});
    const auto segment_nals = zkstego::split_annex_b(patched_segment);
    CHECK(segment_nals[0].rbsp() == std::vector<std::uint8_t>({0xc2, 0x00, 0x1e}));
    CHECK(segment_nals[1].payload == nals[1].payload);
    CHECK(segment_nals[2].rbsp() == std::vector<std::uint8_t>({0x88, 0xff, 0x00, 0x01}));
}
