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

    const auto pps = zkstego::parse_baseline_pps({0xce, 0x04, 0xcb, 0x20});
    CHECK(pps.pic_parameter_set_id == 0);
    CHECK(pps.sequence_parameter_set_id == 0);
    CHECK(!pps.entropy_coding_mode_flag);
    CHECK(pps.num_slice_groups_minus1 == 0);
    CHECK(pps.pic_init_qp_minus26 == -4);
    CHECK(pps.deblocking_filter_control_present_flag);

    const auto idr_header = zkstego::parse_baseline_idr_slice_header(
        {0x88, 0x84, 0x3f, 0xe0, 0xb8, 0x60, 0x1e, 0x5c}, sps, pps);
    CHECK(idr_header.first_mb_in_slice == 0);
    CHECK(idr_header.slice_type == 2);
    CHECK(idr_header.pic_parameter_set_id == 0);
    CHECK(idr_header.frame_num == 0);
    CHECK(idr_header.idr_pic_id == 0);
    CHECK(idr_header.slice_qp_delta == -3);
    CHECK(idr_header.data_bit_offset == 24);

    const auto macroblock = zkstego::parse_baseline_i_macroblock_header(
        {0x88, 0x84, 0x3f, 0xe0, 0xb8, 0x60, 0x1e, 0x5c}, idr_header.data_bit_offset);
    CHECK(macroblock.mb_type == 0);
    CHECK(macroblock.coded_block_pattern == 47);
    CHECK(macroblock.mb_qp_delta == 0);
    CHECK(macroblock.residual_bit_offset == 62);
    const auto first_luma_token = zkstego::parse_cavlc_coeff_token(
        {0x88, 0x84, 0x3f, 0xe0, 0xb8, 0x60, 0x1e, 0x5c,
         0x07, 0x29, 0x80, 0x00, 0x80, 0x8a, 0x64, 0x50},
        macroblock.residual_bit_offset,
        0);
    CHECK(first_luma_token.total_coefficients == 4);
    CHECK(first_luma_token.trailing_ones == 0);
    CHECK(first_luma_token.level_bit_offset == 72);
    const auto first_luma_levels = zkstego::decode_cavlc_non_trailing_levels(
        {0x88, 0x84, 0x3f, 0xe0, 0xb8, 0x60, 0x1e, 0x5c,
         0x07, 0x29, 0x80, 0x00, 0x80, 0x8a, 0x64, 0x50},
        first_luma_token);
    CHECK((first_luma_levels.values == std::vector<std::int32_t>{2, 2, -2, -24}));
    CHECK(first_luma_levels.next_bit_offset == 109);
    const auto first_luma_tail = zkstego::decode_cavlc_tail_tc4(
        {0x88, 0x84, 0x3f, 0xe0, 0xb8, 0x60, 0x1e, 0x5c,
         0x07, 0x29, 0x80, 0x00, 0x80, 0x8a, 0x64, 0x50},
        first_luma_levels.next_bit_offset);
    CHECK(first_luma_tail.total_zeros == 3);
    CHECK((first_luma_tail.runs == std::vector<std::uint32_t>{0, 3, 0, 0}));
    CHECK(first_luma_tail.next_bit_offset == 117);

    const auto token = zkstego::parse_cavlc_coeff_token({0x41, 0x80}, 0, 0);
    CHECK(token.total_coefficients == 1);
    CHECK(token.trailing_ones == 1);
    CHECK(token.sign_bit_offsets == std::vector<std::size_t>{2});
    CHECK(token.level_bit_offset == 3);

    const auto n2_token = zkstego::parse_cavlc_coeff_token({0xa1, 0x80}, 0, 2);
    CHECK(n2_token.total_coefficients == 1);
    CHECK(n2_token.trailing_ones == 1);
    CHECK(n2_token.sign_bit_offsets == std::vector<std::size_t>{2});

    const auto n4_token = zkstego::parse_cavlc_coeff_token({0xe8, 0x00}, 0, 4);
    CHECK(n4_token.total_coefficients == 1);
    CHECK(n4_token.trailing_ones == 1);
    CHECK(n4_token.sign_bit_offsets == std::vector<std::size_t>{4});

    const auto n6_token = zkstego::parse_cavlc_coeff_token({0xe8, 0x00}, 0, 6);
    CHECK(n6_token.total_coefficients == 1);
    CHECK(n6_token.trailing_ones == 1);
    CHECK(n6_token.sign_bit_offsets == std::vector<std::size_t>{4});

    const auto chroma_dc_token = zkstego::parse_cavlc_coeff_token({0x80}, 0, -1);
    CHECK(chroma_dc_token.total_coefficients == 1);
    CHECK(chroma_dc_token.trailing_ones == 1);
    CHECK(chroma_dc_token.sign_bit_offsets == std::vector<std::size_t>{1});

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
