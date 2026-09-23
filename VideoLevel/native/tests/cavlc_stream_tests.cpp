#include "zkstego/cavlc_stream.hpp"

#include <algorithm>
#include <array>
#include <cstdint>
#include <fstream>
#include <iterator>
#include <numeric>
#include <stdexcept>
#include <string>
#include <string_view>
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

    // FFmpeg's canonical Table 9-5(a) mappings for nC=0/1. These
    // regression cases cover the formerly malformed TC=2 and high-TC rows.
    const auto n0_tc2_t2 = zkstego::parse_cavlc_coeff_token({0x20, 0x00, 0x00}, 0, 0);
    CHECK(n0_tc2_t2.total_coefficients == 2);
    CHECK(n0_tc2_t2.trailing_ones == 2);
    CHECK(n0_tc2_t2.level_bit_offset == 5);
    const auto n0_tc13_t0 = zkstego::parse_cavlc_coeff_token({0x00, 0x0f, 0x00}, 0, 0);
    CHECK(n0_tc13_t0.total_coefficients == 13);
    CHECK(n0_tc13_t0.trailing_ones == 0);
    CHECK(n0_tc13_t0.level_bit_offset == 16);
    const auto bits_to_bytes = [](const std::string_view bits) {
        std::vector<std::uint8_t> bytes;
        std::uint8_t value = 0;
        std::size_t count = 0;
        for (const char bit : bits) {
            value = static_cast<std::uint8_t>((value << 1U) | (bit == '1' ? 1U : 0U));
            if (++count == 8U) {
                bytes.push_back(value);
                value = 0;
                count = 0;
            }
        }
        if (count != 0U) bytes.push_back(static_cast<std::uint8_t>(value << (8U - count)));
        return bytes;
    };
    struct CoeffTokenCase { std::string_view bits; std::uint32_t total_coefficients; std::uint32_t trailing_ones; };
    constexpr std::array canonical_high_n0_1_tokens{
        CoeffTokenCase{"0000000000001111", 13, 0}, CoeffTokenCase{"000000000000001", 13, 1},
        CoeffTokenCase{"000000000001001", 13, 2}, CoeffTokenCase{"000000000001100", 13, 3},
        CoeffTokenCase{"0000000000001011", 14, 0}, CoeffTokenCase{"0000000000001110", 14, 1},
        CoeffTokenCase{"0000000000001101", 14, 2}, CoeffTokenCase{"000000000001000", 14, 3},
        CoeffTokenCase{"0000000000000111", 15, 0}, CoeffTokenCase{"0000000000001010", 15, 1},
        CoeffTokenCase{"0000000000001001", 15, 2}, CoeffTokenCase{"0000000000001100", 15, 3},
        CoeffTokenCase{"0000000000000100", 16, 0}, CoeffTokenCase{"0000000000000110", 16, 1},
        CoeffTokenCase{"0000000000000101", 16, 2}, CoeffTokenCase{"0000000000001000", 16, 3},
    };
    for (const auto& test_case : canonical_high_n0_1_tokens) {
        const auto token = zkstego::parse_cavlc_coeff_token(bits_to_bytes(test_case.bits), 0, 0);
        CHECK(token.total_coefficients == test_case.total_coefficients);
        CHECK(token.trailing_ones == test_case.trailing_ones);
        CHECK(token.level_bit_offset == test_case.bits.size() + test_case.trailing_ones);
    }

    zkstego::RbspBitReader skipping_reader({0b10100110});
    skipping_reader.skip_bits(5);
    CHECK(skipping_reader.position() == 5);
    CHECK(skipping_reader.read_bits(3) == 0b110);

    zkstego::RbspBitReader signed_reader({0b01100000});
    CHECK(signed_reader.read_se() == -1);  // ue(v)=2 maps to se(v)=-1

    zkstego::RbspBitReader signed_minimum_reader({0x00, 0x00, 0x00, 0x01, 0xff, 0xff, 0xff, 0xff});
    CHECK(signed_minimum_reader.read_se() == -2147483647);

    // Cross-language schedule vector: these candidates and the 00..1f key
    // are scored by Python's hmac.new(..., hashlib.sha256) under the exact
    // canonical domain key. The expected order is fixed by those digests.
    std::vector<std::uint8_t> blind_key(32);
    std::iota(blind_key.begin(), blind_key.end(), static_cast<std::uint8_t>(0));
    const std::vector<zkstego::CavlcSignCandidate> schedule_vector{
        {7, 11, zkstego::CavlcResidualCategory::Luma4x4, 3, 91},
        {3, 2, zkstego::CavlcResidualCategory::ChromaAc, 0, 12},
        {7, 11, zkstego::CavlcResidualCategory::Luma4x4, 2, 90},
    };
    CHECK(zkstego::serialize_cavlc_sign_candidate(schedule_vector[0]) == "7:11:1:3:91");
    CHECK(zkstego::serialize_cavlc_sign_candidate(schedule_vector[1]) == "3:2:3:0:12");
    const auto expected_first_score = std::array<std::uint8_t, 32>{
        0x87, 0x78, 0xf4, 0xc4, 0xc4, 0x55, 0xd7, 0x5b,
        0x5f, 0x8f, 0x6e, 0x7a, 0xae, 0x77, 0x65, 0xb1,
        0xf5, 0x86, 0x58, 0x5e, 0x4e, 0x82, 0x04, 0x7f,
        0xb2, 0xc5, 0xeb, 0x9e, 0xce, 0xaf, 0x33, 0xf3,
    };
    CHECK(zkstego::score_keyed_cavlc_sign_candidate(schedule_vector[0], blind_key) == expected_first_score);
    const auto keyed_schedule = zkstego::select_keyed_cavlc_sign_candidates(
        schedule_vector, blind_key, schedule_vector.size());
    CHECK(keyed_schedule[0].nal_index == 3 && keyed_schedule[0].macroblock_address == 2);
    CHECK(keyed_schedule[0].category == zkstego::CavlcResidualCategory::ChromaAc);
    CHECK(keyed_schedule[1].nal_index == 7 && keyed_schedule[1].block_index == 2);
    CHECK(keyed_schedule[2].nal_index == 7 && keyed_schedule[2].block_index == 3);
    auto wrong_key = blind_key;
    std::fill(wrong_key.begin(), wrong_key.end(), 0x01U);
    const auto wrong_key_schedule = zkstego::select_keyed_cavlc_sign_candidates(
        schedule_vector, wrong_key, 1);
    CHECK(wrong_key_schedule[0].nal_index == 7 && wrong_key_schedule[0].macroblock_address == 11);
    CHECK(wrong_key_schedule[0].category == zkstego::CavlcResidualCategory::Luma4x4);
    CHECK(wrong_key_schedule[0].block_index == 3 && wrong_key_schedule[0].rbsp_bit_offset == 91);
    const auto throws_invalid_argument = [](const auto& operation) {
        try { operation(); } catch (const std::invalid_argument&) { return true; }
        return false;
    };
    CHECK(throws_invalid_argument([&] {
        static_cast<void>(zkstego::score_keyed_cavlc_sign_candidate(schedule_vector[0], {0}));
    }));
    CHECK(throws_invalid_argument([&] {
        static_cast<void>(zkstego::select_keyed_cavlc_sign_candidates(schedule_vector, blind_key, 4));
    }));
    auto duplicate_schedule = schedule_vector;
    duplicate_schedule.push_back(schedule_vector[0]);
    CHECK(throws_invalid_argument([&] {
        static_cast<void>(zkstego::select_keyed_cavlc_sign_candidates(duplicate_schedule, blind_key, 1));
    }));
    auto aliased_schedule = schedule_vector;
    aliased_schedule[1].nal_index = schedule_vector[0].nal_index;
    aliased_schedule[1].rbsp_bit_offset = schedule_vector[0].rbsp_bit_offset;
    CHECK(throws_invalid_argument([&] {
        static_cast<void>(zkstego::select_keyed_cavlc_sign_candidates(aliased_schedule, blind_key, 1));
    }));
    auto malformed_candidate = schedule_vector[0];
    malformed_candidate.category = static_cast<zkstego::CavlcResidualCategory>(9);
    CHECK(throws_invalid_argument([&] {
        static_cast<void>(zkstego::score_keyed_cavlc_sign_candidate(malformed_candidate, blind_key));
    }));

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

    // The native macroblock traversal implements I syntax only. An SI slice
    // must be rejected at the header boundary, never interpreted as I data.
    bool si_slice_rejected = false;
    try {
        static_cast<void>(zkstego::parse_baseline_idr_slice_header({0x96, 0x10}, sps, pps));
    } catch (const std::invalid_argument&) {
        si_slice_rejected = true;
    }
    CHECK(si_slice_rejected);

    zkstego::H264BaselineSps poc_type_zero_sps;
    poc_type_zero_sps.frame_mbs_only_flag = true;
    poc_type_zero_sps.pic_order_cnt_type = 0;
    poc_type_zero_sps.log2_max_frame_num_minus4 = 0;
    poc_type_zero_sps.log2_max_pic_order_cnt_lsb_minus4 = 0;
    zkstego::H264BaselinePps poc_type_zero_pps;
    const auto poc_type_zero_header = zkstego::parse_baseline_idr_slice_header(
        {0xb9, 0xd4, 0x80}, poc_type_zero_sps, poc_type_zero_pps);
    CHECK(poc_type_zero_header.frame_num == 3);
    CHECK(poc_type_zero_header.idr_pic_id == 0);
    CHECK(poc_type_zero_header.pic_order_cnt_lsb == 5);
    CHECK(poc_type_zero_header.slice_qp_delta == 0);
    CHECK(poc_type_zero_header.data_bit_offset == 17);

    const std::vector<std::uint8_t> inspectable_annex_b{
        0x00, 0x00, 0x00, 0x01, 0x67,
        0x42, 0xc0, 0x0d, 0xdc, 0x16, 0x09, 0x6f, 0xfc,
        0x02, 0x00, 0x01, 0xd4, 0x40, 0x00, 0x00, 0xfa,
        0x40, 0x00, 0x3a, 0x98, 0x03, 0xc5, 0x0a, 0xe0,
        0x00, 0x00, 0x00, 0x01, 0x68, 0xce, 0x04, 0xcb, 0x20,
        0x00, 0x00, 0x00, 0x01, 0x65,
        0x88, 0x84, 0x3f, 0xe0, 0xb8, 0x60, 0x1e, 0x5c,
        0x07, 0x29, 0x80, 0x00, 0x80, 0x8a, 0x64, 0x50,
    };
    const auto inspected_idrs = zkstego::inspect_baseline_idr_headers(inspectable_annex_b);
    CHECK(inspected_idrs.size() == 1);
    CHECK(inspected_idrs[0].nal_index == 2);
    CHECK(inspected_idrs[0].slice_header.data_bit_offset == 24);
    CHECK(inspected_idrs[0].first_macroblock.mb_type == 0);
    CHECK(inspected_idrs[0].first_macroblock.residual_bit_offset == 62);
    CHECK(inspected_idrs[0].first_luma_block.token.total_coefficients == 4);
    CHECK(inspected_idrs[0].first_luma_block.tail.next_bit_offset == 117);

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
    CHECK((first_luma_levels.values == std::vector<std::int32_t>{3, 2, -2, -24}));
    CHECK(first_luma_levels.next_bit_offset == 109);
    const auto first_luma_tail = zkstego::decode_cavlc_tail_tc4(
        {0x88, 0x84, 0x3f, 0xe0, 0xb8, 0x60, 0x1e, 0x5c,
         0x07, 0x29, 0x80, 0x00, 0x80, 0x8a, 0x64, 0x50},
        first_luma_levels.next_bit_offset);
    CHECK(first_luma_tail.total_zeros == 3);
    CHECK((first_luma_tail.runs == std::vector<std::uint32_t>{0, 3, 0, 0}));
    CHECK(first_luma_tail.next_bit_offset == 117);
    const auto first_luma_generic_tail = zkstego::decode_cavlc_luma_residual_tail(
        {0x88, 0x84, 0x3f, 0xe0, 0xb8, 0x60, 0x1e, 0x5c,
         0x07, 0x29, 0x80, 0x00, 0x80, 0x8a, 0x64, 0x50},
        first_luma_levels.next_bit_offset,
        first_luma_token.total_coefficients);
    CHECK(first_luma_generic_tail.total_zeros == first_luma_tail.total_zeros);
    CHECK(first_luma_generic_tail.runs == first_luma_tail.runs);
    CHECK(first_luma_generic_tail.next_bit_offset == first_luma_tail.next_bit_offset);
    const auto first_luma_block = zkstego::decode_cavlc_luma_block(
        {0x88, 0x84, 0x3f, 0xe0, 0xb8, 0x60, 0x1e, 0x5c,
         0x07, 0x29, 0x80, 0x00, 0x80, 0x8a, 0x64, 0x50},
        macroblock.residual_bit_offset,
        0);
    CHECK(first_luma_block.token.total_coefficients == 4);
    CHECK((first_luma_block.levels.values == std::vector<std::int32_t>{3, 2, -2, -24}));
    CHECK((first_luma_block.tail.runs == std::vector<std::uint32_t>{0, 3, 0, 0}));
    CHECK(first_luma_block.tail.next_bit_offset == 117);
    CHECK((first_luma_block.coefficients == std::vector<std::int32_t>{
        -24, -2, 0, 0, 0, 2, 3, 0, 0, 0, 0, 0, 0, 0, 0, 0}));
    zkstego::CavlcCoeffToken long_prefix_token;
    long_prefix_token.total_coefficients = 1;
    long_prefix_token.level_bit_offset = 0;
    const auto long_prefix_levels = zkstego::decode_cavlc_non_trailing_levels(
        {0x00, 0x02, 0x00}, long_prefix_token);
    CHECK((long_prefix_levels.values == std::vector<std::int32_t>{9}));
    CHECK(long_prefix_levels.next_bit_offset == 19);

    // H.264 9.2.2: the first non-trailing level receives the levelCode += 2
    // adjustment when TrailingOnes is less than three.  A level_prefix of zero
    // therefore decodes to +2, not +1.
    zkstego::CavlcCoeffToken first_level_adjustment_token;
    first_level_adjustment_token.total_coefficients = 1;
    first_level_adjustment_token.level_bit_offset = 0;
    const auto first_level_adjustment = zkstego::decode_cavlc_non_trailing_levels(
        {0x80}, first_level_adjustment_token);
    CHECK((first_level_adjustment.values == std::vector<std::int32_t>{2}));
    CHECK(first_level_adjustment.next_bit_offset == 1);
    const auto empty_luma_macroblock = zkstego::decode_cavlc_luma_macroblock({0xf0}, 0, 1);
    CHECK(empty_luma_macroblock.next_bit_offset == 4);
    CHECK(empty_luma_macroblock.blocks[0].token.total_coefficients == 0);
    CHECK(empty_luma_macroblock.blocks[1].token.total_coefficients == 0);
    CHECK(empty_luma_macroblock.blocks[4].token.total_coefficients == 0);
    CHECK(empty_luma_macroblock.blocks[5].token.total_coefficients == 0);

    // The first block of a non-left-edge macroblock must select its
    // coeff_token table from persisted left-neighbour state.  nC=2 encodes
    // an empty block as "11"; each following locally zero-context block is
    // the nC=0/1 code "1", so the complete 16-block span is 17 bits.
    zkstego::CavlcLumaNeighbourCounts luma_left_neighbour;
    luma_left_neighbour.left_available = true;
    luma_left_neighbour.left[0] = 2;
    const auto contextual_empty_luma_macroblock = zkstego::decode_cavlc_luma_macroblock(
        {0xff, 0xff, 0x80}, 0, 15, luma_left_neighbour);
    CHECK(contextual_empty_luma_macroblock.next_bit_offset == 17);
    CHECK(contextual_empty_luma_macroblock.blocks[0].token.total_coefficients == 0);
    CHECK(contextual_empty_luma_macroblock.blocks[1].token.total_coefficients == 0);

    // Top-edge state uses the same nC=2 token for block (0, 0).
    zkstego::CavlcLumaNeighbourCounts luma_top_neighbour;
    luma_top_neighbour.top_available = true;
    luma_top_neighbour.top[0] = 2;
    CHECK(zkstego::decode_cavlc_luma_macroblock(
              {0xff, 0xff, 0x80}, 0, 15, luma_top_neighbour).next_bit_offset == 17);

    // nC is ceil((nA + nB) / 2), including when both external neighbours
    // are available.  1 and 2 must therefore choose the nC=2 table.
    zkstego::CavlcLumaNeighbourCounts luma_both_neighbours;
    luma_both_neighbours.left_available = true;
    luma_both_neighbours.top_available = true;
    luma_both_neighbours.left[0] = 1;
    luma_both_neighbours.top[0] = 2;
    CHECK(zkstego::decode_cavlc_luma_macroblock(
              {0xff, 0xff, 0x80}, 0, 15, luma_both_neighbours).next_bit_offset == 17);

    // State behind an unavailable edge is ignored.  This models the first
    // macroblock of a locked raster slice without trusting stale buffers.
    zkstego::CavlcLumaNeighbourCounts unavailable_neighbours;
    unavailable_neighbours.left[0] = 16;
    unavailable_neighbours.top[0] = 16;
    CHECK(zkstego::decode_cavlc_luma_macroblock(
              {0xff, 0xff}, 0, 15, unavailable_neighbours).next_bit_offset == 16);

    // External context is addressed in physical 4x4 raster coordinates, not
    // in CAVLC group order: block 4 is (2, 0), and block 8 is (0, 2).  Each
    // needs a value of four because its other, in-MB neighbour is zero and
    // nC is the rounded-up average.
    zkstego::CavlcLumaNeighbourCounts indexed_top_neighbour;
    indexed_top_neighbour.top_available = true;
    indexed_top_neighbour.top[2] = 4;
    CHECK(zkstego::decode_cavlc_luma_macroblock(
              {0xf8}, 0, 2, indexed_top_neighbour).next_bit_offset == 5);
    zkstego::CavlcLumaNeighbourCounts indexed_left_neighbour;
    indexed_left_neighbour.left_available = true;
    indexed_left_neighbour.left[2] = 4;
    CHECK(zkstego::decode_cavlc_luma_macroblock(
              {0xf8}, 0, 4, indexed_left_neighbour).next_bit_offset == 5);

    zkstego::CavlcLumaNeighbourCounts invalid_left_neighbour;
    invalid_left_neighbour.left_available = true;
    invalid_left_neighbour.left[0] = 17;
    bool invalid_neighbour_rejected = false;
    try {
        static_cast<void>(zkstego::decode_cavlc_luma_macroblock(
            {0x80}, 0, 1, invalid_left_neighbour));
    } catch (const std::invalid_argument&) {
        invalid_neighbour_rejected = true;
    }
    CHECK(invalid_neighbour_rejected);

    // Acceptance regression for the locked camera profile: every IDR must
    // traverse every macroblock and land precisely at rbsp_trailing_bits.
    // This exercises mixed I4x4/I16x16 luma, CAVLC AC/DC, and 4:2:0 chroma
    // neighbour contexts over the whole 300-frame fixture, not just a prefix.
    const std::string fixture_path = std::string{ZKSTEGO_PROJECT_SOURCE_DIR} +
        "/data/encoded/foreman_cif_q18_g1_300f.h264";
    std::ifstream fixture(fixture_path, std::ios::binary);
    CHECK(static_cast<bool>(fixture));
    const std::vector<std::uint8_t> fixture_bytes{
        std::istreambuf_iterator<char>(fixture), std::istreambuf_iterator<char>()};
    CHECK(fixture_bytes.size() == 3551610);
    const auto decoded_fixture = zkstego::decode_baseline_i_idr_slices(fixture_bytes);
    CHECK(decoded_fixture.size() == 300);
    std::size_t i16x16_macroblocks = 0;
    std::size_t chroma_dc_macroblocks = 0;
    std::size_t chroma_ac_macroblocks = 0;
    for (const auto& slice : decoded_fixture) {
        CHECK(slice.macroblocks.size() == 396);
        CHECK(slice.rbsp_trailing_bit_offset > slice.header.data_bit_offset);
        for (const auto& macroblock : slice.macroblocks) {
            if (macroblock.header.mb_type >= 1U && macroblock.header.mb_type <= 24U) {
                ++i16x16_macroblocks;
            }
            const auto chroma_coded_block_pattern = (macroblock.header.coded_block_pattern >> 4U) & 0x03U;
            if (chroma_coded_block_pattern >= 1U) ++chroma_dc_macroblocks;
            if (chroma_coded_block_pattern >= 2U) ++chroma_ac_macroblocks;
        }
    }
    CHECK(i16x16_macroblocks > 0U);
    CHECK(chroma_dc_macroblocks > 0U);
    CHECK(chroma_ac_macroblocks > 0U);

    // A trailing-one sign edit must preserve the blind candidate map because
    // it cannot change CAVLC codeword length or the number of trailing ones.
    const auto candidates = zkstego::collect_cavlc_trailing_one_sign_candidates(decoded_fixture);
    CHECK(!candidates.empty());
    const auto selected_candidate = candidates.front();
    const auto fixture_units = zkstego::split_annex_b(fixture_bytes);
    const auto selected_rbsp = fixture_units.at(selected_candidate.nal_index).rbsp();
    const auto selected_original_bit = static_cast<std::uint8_t>(
        (selected_rbsp[selected_candidate.rbsp_bit_offset / 8U] >>
         (7U - selected_candidate.rbsp_bit_offset % 8U)) & 1U);
    const auto patched_fixture = zkstego::patch_annex_b_rbsp_plan(fixture_bytes, {
        {selected_candidate.nal_index, {{selected_candidate.rbsp_bit_offset, {static_cast<std::uint8_t>(1U - selected_original_bit)}}}},
    });
    const auto patched_rbsp = zkstego::split_annex_b(patched_fixture)
        .at(selected_candidate.nal_index).rbsp();
    const auto selected_patched_bit = static_cast<std::uint8_t>(
        (patched_rbsp[selected_candidate.rbsp_bit_offset / 8U] >>
         (7U - selected_candidate.rbsp_bit_offset % 8U)) & 1U);
    CHECK(selected_patched_bit == 1U - selected_original_bit);
    const auto reparsed_candidates = zkstego::collect_cavlc_trailing_one_sign_candidates(
        zkstego::decode_baseline_i_idr_slices(patched_fixture));
    const auto matching_candidate = std::find_if(
        reparsed_candidates.begin(), reparsed_candidates.end(), [&](const auto& candidate) {
            return candidate.nal_index == selected_candidate.nal_index &&
                candidate.macroblock_address == selected_candidate.macroblock_address &&
                candidate.category == selected_candidate.category &&
                candidate.block_index == selected_candidate.block_index &&
                candidate.rbsp_bit_offset == selected_candidate.rbsp_bit_offset;
        });
    CHECK(matching_candidate != reparsed_candidates.end());
    CHECK(reparsed_candidates.size() == candidates.size());
    for (std::size_t index = 0; index < candidates.size(); ++index) {
        const auto& before = candidates[index];
        const auto& after = reparsed_candidates[index];
        CHECK(before.nal_index == after.nal_index);
        CHECK(before.macroblock_address == after.macroblock_address);
        CHECK(before.category == after.category);
        CHECK(before.block_index == after.block_index);
        CHECK(before.rbsp_bit_offset == after.rbsp_bit_offset);
    }
    const std::vector<std::uint8_t> blind_payload_bits{
        1, 0, 1, 1, 0, 0, 1, 0, 1, 0, 0, 1, 1, 1, 0, 0,
        0, 1, 1, 0, 1, 1, 1, 0, 0, 0, 1, 0, 1, 0, 1, 1,
    };
    const auto blind_stego_fixture = zkstego::embed_keyed_cavlc_sign_bits(
        fixture_bytes, blind_key, blind_payload_bits);
    const auto blind_stego_candidates = zkstego::collect_cavlc_trailing_one_sign_candidates(
        zkstego::decode_baseline_i_idr_slices(blind_stego_fixture));
    CHECK(blind_stego_candidates.size() == candidates.size());
    for (std::size_t index = 0; index < candidates.size(); ++index) {
        CHECK(zkstego::serialize_cavlc_sign_candidate(blind_stego_candidates[index]) ==
            zkstego::serialize_cavlc_sign_candidate(candidates[index]));
    }
    CHECK(zkstego::extract_keyed_cavlc_sign_bits(
        blind_stego_fixture, blind_key, blind_payload_bits.size()) == blind_payload_bits);
    CHECK(zkstego::extract_keyed_cavlc_sign_bits(
        blind_stego_fixture, wrong_key, blind_payload_bits.size()) != blind_payload_bits);
    CHECK(throws_invalid_argument([&] {
        static_cast<void>(zkstego::embed_keyed_cavlc_sign_bits(fixture_bytes, blind_key, {2}));
    }));
    CHECK(zkstego::embed_keyed_cavlc_sign_bits(fixture_bytes, blind_key, {}) == fixture_bytes);
    CHECK(throws_invalid_argument([&] {
        static_cast<void>(zkstego::embed_keyed_cavlc_sign_bits(fixture_bytes, {0}, blind_payload_bits));
    }));
    CHECK(throws_invalid_argument([&] {
        static_cast<void>(zkstego::extract_keyed_cavlc_sign_bits(fixture_bytes, {0}, 1));
    }));
    CHECK(throws_invalid_argument([&] {
        static_cast<void>(zkstego::extract_keyed_cavlc_sign_bits(fixture_bytes, blind_key, candidates.size() + 1U));
    }));
    const std::vector<std::uint8_t> authenticated_payload{0x70, 0x72, 0x6f, 0x6f, 0x66};
    const auto authenticated_stego = zkstego::embed_authenticated_cavlc_payload(
        fixture_bytes, blind_key, authenticated_payload);
    CHECK(zkstego::extract_authenticated_cavlc_payload(
        authenticated_stego, blind_key, 32) == authenticated_payload);
    CHECK(throws_invalid_argument([&] {
        static_cast<void>(zkstego::extract_authenticated_cavlc_payload(authenticated_stego, wrong_key, 32));
    }));
    const auto authenticated_candidates = zkstego::select_keyed_cavlc_sign_candidates(
        zkstego::collect_cavlc_trailing_one_sign_candidates(
            zkstego::decode_baseline_i_idr_slices(authenticated_stego)),
        blind_key, (3U + authenticated_payload.size() + 16U) * 8U);
    const auto tamper_target = authenticated_candidates[24];
    const auto tamper_rbsp = zkstego::split_annex_b(authenticated_stego)
        .at(tamper_target.nal_index).rbsp();
    const auto tamper_bit = static_cast<std::uint8_t>(
        (tamper_rbsp[tamper_target.rbsp_bit_offset / 8U] >>
         (7U - tamper_target.rbsp_bit_offset % 8U)) & 1U);
    const auto tampered_authenticated_stego = zkstego::patch_annex_b_rbsp_plan(authenticated_stego, {
        {tamper_target.nal_index, {{tamper_target.rbsp_bit_offset, {static_cast<std::uint8_t>(1U - tamper_bit)}}}},
    });
    CHECK(throws_invalid_argument([&] {
        static_cast<void>(zkstego::extract_authenticated_cavlc_payload(tampered_authenticated_stego, blind_key, 32));
    }));
    const auto empty_luma_block = zkstego::decode_cavlc_luma_block({0x80}, 0, 0);
    CHECK(empty_luma_block.token.total_coefficients == 0);
    CHECK(empty_luma_block.tail.runs.empty());
    CHECK(empty_luma_block.tail.next_bit_offset == 1);
    CHECK(empty_luma_block.coefficients == std::vector<std::int32_t>(16, 0));
    const auto first_luma_coefficients = zkstego::reconstruct_cavlc_tc4_no_trailing(
        first_luma_levels.values, first_luma_tail.runs);
    CHECK((first_luma_coefficients == std::vector<std::int32_t>{
        -24, -2, 0, 0, 0, 2, 3, 0, 0, 0, 0, 0, 0, 0, 0, 0}));

    const auto varied_runs_tail = zkstego::decode_cavlc_tail_tc4({0xd9, 0x80}, 0);
    CHECK(varied_runs_tail.total_zeros == 4);
    CHECK((varied_runs_tail.runs == std::vector<std::uint32_t>{0, 3, 0, 1}));
    CHECK(varied_runs_tail.next_bit_offset == 9);

    const auto real_tc9_tail = zkstego::decode_cavlc_luma_residual_tail({0x3b, 0xe8}, 0, 9);
    CHECK(real_tc9_tail.total_zeros == 5);
    CHECK((real_tc9_tail.runs == std::vector<std::uint32_t>{0, 2, 0, 1, 0, 2, 0, 0, 0}));
    CHECK(real_tc9_tail.next_bit_offset == 15);

    struct TotalZerosCase {
        std::uint32_t total_coefficients;
        std::uint8_t encoded_byte;
        std::size_t encoded_bits;
    };
    const std::vector<TotalZerosCase> total_zeros_zero_cases{
        {1, 0x80, 1}, {2, 0xe0, 3}, {3, 0x50, 4}, {4, 0x18, 5},
        {5, 0x50, 4}, {6, 0x04, 6}, {7, 0x04, 6}, {8, 0x04, 6},
        {9, 0x04, 6}, {10, 0x08, 5}, {11, 0x00, 4}, {12, 0x00, 4},
        {13, 0x00, 3}, {14, 0x00, 2}, {15, 0x00, 1},
    };
    for (const auto& test_case : total_zeros_zero_cases) {
        const auto tail = zkstego::decode_cavlc_luma_residual_tail(
            {test_case.encoded_byte}, 0, test_case.total_coefficients);
        CHECK(tail.total_zeros == 0);
        CHECK(tail.runs == std::vector<std::uint32_t>(test_case.total_coefficients, 0));
        CHECK(tail.next_bit_offset == test_case.encoded_bits);
    }
    const auto tc1_maximum_zeros_tail = zkstego::decode_cavlc_luma_residual_tail({0x00, 0x80}, 0, 1);
    CHECK(tc1_maximum_zeros_tail.total_zeros == 15);
    CHECK((tc1_maximum_zeros_tail.runs == std::vector<std::uint32_t>{15}));
    CHECK(tc1_maximum_zeros_tail.next_bit_offset == 9);
    const auto tc16_tail = zkstego::decode_cavlc_luma_residual_tail({0xff}, 0, 16);
    CHECK(tc16_tail.total_zeros == 0);
    CHECK(tc16_tail.runs == std::vector<std::uint32_t>(16, 0));
    CHECK(tc16_tail.next_bit_offset == 0);

    // Chroma AC has maxNumCoeff=15.  Its TotalCoeff=15 case has no
    // total_zeros syntax; consuming the luma TC=15 VLC here would shift the
    // following residual block by one bit.
    const auto chroma_ac_full_tail = zkstego::decode_cavlc_residual_tail({}, 0, 15, 15);
    CHECK(chroma_ac_full_tail.total_zeros == 0);
    CHECK(chroma_ac_full_tail.runs == std::vector<std::uint32_t>(15, 0));
    CHECK(chroma_ac_full_tail.next_bit_offset == 0);

    const auto token = zkstego::parse_cavlc_coeff_token({0x41, 0x80}, 0, 0);
    CHECK(token.total_coefficients == 1);
    CHECK(token.trailing_ones == 1);
    CHECK(token.sign_bit_offsets == std::vector<std::size_t>{2});
    CHECK(token.level_bit_offset == 3);
    const auto trailing_one_levels = zkstego::decode_cavlc_non_trailing_levels({0x41, 0x80}, token);
    CHECK(trailing_one_levels.values.empty());
    CHECK((trailing_one_levels.trailing_one_values == std::vector<std::int32_t>{1}));
    CHECK(trailing_one_levels.next_bit_offset == 3);
    const auto trailing_one_coefficients = zkstego::reconstruct_cavlc_block(
        trailing_one_levels, {0}, 16);
    CHECK((trailing_one_coefficients == std::vector<std::int32_t>{
        1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0}));

    const auto n2_token = zkstego::parse_cavlc_coeff_token({0xa1, 0x80}, 0, 2);
    CHECK(n2_token.total_coefficients == 1);
    CHECK(n2_token.trailing_ones == 1);
    CHECK(n2_token.sign_bit_offsets == std::vector<std::size_t>{2});

    const auto n4_token = zkstego::parse_cavlc_coeff_token({0xe8, 0x00}, 0, 4);
    CHECK(n4_token.total_coefficients == 1);
    CHECK(n4_token.trailing_ones == 1);
    CHECK(n4_token.sign_bit_offsets == std::vector<std::size_t>{4});

    // Table 9-5(c), nC=4..7: 1111 is the valid empty-block token.
    const auto n4_empty_token = zkstego::parse_cavlc_coeff_token({0xf0}, 0, 4);
    CHECK(n4_empty_token.total_coefficients == 0);
    CHECK(n4_empty_token.trailing_ones == 0);
    CHECK(n4_empty_token.level_bit_offset == 4);

    // Representative entries from every TotalCoeff row of H.264 Table 9-5(c)
    // (nC=4..7).  The table is variable length, so a six-bit-only decoder is
    // not sufficient here.
    struct N4TokenCase {
        std::string_view bits;
        std::uint32_t total_coefficients;
        std::uint32_t trailing_ones;
    };
    const std::vector<N4TokenCase> n4_token_cases{
        {"1111", 0, 0}, {"001111", 1, 0}, {"001011", 2, 0},
        {"001000", 3, 0}, {"0001111", 4, 0}, {"0001011", 5, 0},
        {"0001001", 6, 0}, {"0001000", 7, 0}, {"00001111", 8, 0},
        {"00001011", 9, 0}, {"000001111", 10, 0}, {"000001011", 11, 0},
        {"000001000", 12, 0}, {"0000001101", 13, 0}, {"0000001001", 14, 0},
        {"0000000101", 15, 0}, {"0000000001", 16, 0},
        {"1110", 1, 1}, {"1101", 2, 2}, {"1100", 3, 3},
    };
    for (const auto& test_case : n4_token_cases) {
        const auto parsed = zkstego::parse_cavlc_coeff_token(bits_to_bytes(test_case.bits), 0, 4);
        CHECK(parsed.total_coefficients == test_case.total_coefficients);
        CHECK(parsed.trailing_ones == test_case.trailing_ones);
        CHECK(parsed.level_bit_offset == test_case.bits.size() + test_case.trailing_ones);
    }

    const auto n4_long_token = zkstego::parse_cavlc_coeff_token({0x00, 0x80}, 0, 4);
    CHECK(n4_long_token.total_coefficients == 16);
    CHECK(n4_long_token.trailing_ones == 3);
    CHECK(n4_long_token.level_bit_offset == 13);

    const auto n6_token = zkstego::parse_cavlc_coeff_token({0xe8, 0x00}, 0, 6);
    CHECK(n6_token.total_coefficients == 1);
    CHECK(n6_token.trailing_ones == 1);
    CHECK(n6_token.sign_bit_offsets == std::vector<std::size_t>{4});

    const auto n8_empty_token = zkstego::parse_cavlc_coeff_token({0x0c}, 0, 8);
    CHECK(n8_empty_token.total_coefficients == 0);
    CHECK(n8_empty_token.trailing_ones == 0);
    const auto n8_one_token = zkstego::parse_cavlc_coeff_token({0x00}, 0, 8);
    CHECK(n8_one_token.total_coefficients == 1);
    CHECK(n8_one_token.trailing_ones == 0);
    const auto n8_token = zkstego::parse_cavlc_coeff_token({0x14, 0x00}, 0, 8);
    CHECK(n8_token.total_coefficients == 2);
    CHECK(n8_token.trailing_ones == 1);
    CHECK(n8_token.sign_bit_offsets == std::vector<std::size_t>{6});
    CHECK(n8_token.level_bit_offset == 7);
    const auto n8_tc14_token = zkstego::parse_cavlc_coeff_token({0xe0}, 0, 8);
    CHECK(n8_tc14_token.total_coefficients == 15);
    CHECK(n8_tc14_token.trailing_ones == 0);
    CHECK(n8_tc14_token.level_bit_offset == 6);

    const auto chroma_dc_token = zkstego::parse_cavlc_coeff_token({0x80}, 0, -1);
    CHECK(chroma_dc_token.total_coefficients == 1);
    CHECK(chroma_dc_token.trailing_ones == 1);
    CHECK(chroma_dc_token.sign_bit_offsets == std::vector<std::size_t>{1});
    const auto chroma_dc_block = zkstego::decode_cavlc_chroma_dc_block({0xa0}, 0);
    CHECK(chroma_dc_block.token.total_coefficients == 1);
    CHECK(chroma_dc_block.levels.trailing_one_values == std::vector<std::int32_t>{1});
    CHECK(chroma_dc_block.tail.total_zeros == 0);
    CHECK(chroma_dc_block.tail.runs == std::vector<std::uint32_t>{0});
    CHECK(chroma_dc_block.tail.next_bit_offset == 3);
    CHECK(chroma_dc_block.coefficients == std::vector<std::int32_t>({1, 0, 0, 0}));
    // Table 9-8, ChromaDC TotalCoeff=1: total_zeros=2 is 001, not 00.
    // Treating 00 as a complete code makes it a prefix of the 000 code and
    // shifts every following residual block.
    const auto chroma_dc_one_zero_tail = zkstego::decode_cavlc_chroma_dc_residual_tail({0x40}, 0, 1);
    CHECK(chroma_dc_one_zero_tail.total_zeros == 1);
    CHECK(chroma_dc_one_zero_tail.runs == std::vector<std::uint32_t>({1}));
    CHECK(chroma_dc_one_zero_tail.next_bit_offset == 2);
    const auto chroma_dc_two_zeros_tail = zkstego::decode_cavlc_chroma_dc_residual_tail({0x20}, 0, 1);
    CHECK(chroma_dc_two_zeros_tail.total_zeros == 2);
    CHECK(chroma_dc_two_zeros_tail.runs == std::vector<std::uint32_t>({2}));
    CHECK(chroma_dc_two_zeros_tail.next_bit_offset == 3);
    const auto chroma_dc_three_zeros_tail = zkstego::decode_cavlc_chroma_dc_residual_tail({0x00}, 0, 1);
    CHECK(chroma_dc_three_zeros_tail.total_zeros == 3);
    CHECK(chroma_dc_three_zeros_tail.runs == std::vector<std::uint32_t>({3}));
    CHECK(chroma_dc_three_zeros_tail.next_bit_offset == 3);
    const auto chroma_ac_block = zkstego::decode_cavlc_chroma_ac_block({0x50}, 0, 0);
    CHECK(chroma_ac_block.token.total_coefficients == 1);
    CHECK(chroma_ac_block.levels.trailing_one_values == std::vector<std::int32_t>{1});
    CHECK(chroma_ac_block.tail.total_zeros == 0);
    CHECK(chroma_ac_block.tail.next_bit_offset == 4);
    CHECK(chroma_ac_block.coefficients == std::vector<std::int32_t>(
        {1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0}));

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
