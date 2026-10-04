#include "zkstego/cavlc_stream.hpp"

#include <algorithm>
#include <array>
#include <chrono>
#include <cstdint>
#include <filesystem>
#include <fstream>
#include <istream>
#include <iterator>
#include <numeric>
#include <sstream>
#include <stdexcept>
#include <string>
#include <streambuf>
#include <string_view>
#include <utility>
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

    // HKDF-SHA-256 primitive: RFC 5869 Appendix A.1 (test case 1).
    const std::vector<std::uint8_t> rfc5869_ikm(22U, 0x0bU);
    std::vector<std::uint8_t> rfc5869_salt(13U);
    std::iota(rfc5869_salt.begin(), rfc5869_salt.end(), static_cast<std::uint8_t>(0x00U));
    std::vector<std::uint8_t> rfc5869_info(10U);
    std::iota(rfc5869_info.begin(), rfc5869_info.end(), static_cast<std::uint8_t>(0xf0U));
    const std::vector<std::uint8_t> rfc5869_okm{
        0x3c, 0xb2, 0x5f, 0x25, 0xfa, 0xac, 0xd5, 0x7a,
        0x90, 0x43, 0x4f, 0x64, 0xd0, 0x36, 0x2f, 0x2a,
        0x2d, 0x2d, 0x0a, 0x90, 0xcf, 0x1a, 0x5a, 0x4c,
        0x5d, 0xb0, 0x2d, 0x56, 0xec, 0xc4, 0xc5, 0xbf,
        0x34, 0x00, 0x72, 0x08, 0xd5, 0xb8, 0x87, 0x18,
        0x58, 0x65,
    };
    CHECK(zkstego::hkdf_sha256(rfc5869_salt, rfc5869_ikm, rfc5869_info, 42U) == rfc5869_okm);

    // Protocol v3 vectors (key derivation, schedule and keystream equal v2). Every value is generated by and asserted in
    // src/native_blind_contract.py / src/runtest/test_native_blind_contract.py.
    const auto expected_first_score = std::array<std::uint8_t, 32>{
        0xbf, 0x5e, 0x31, 0x2d, 0xf3, 0xc9, 0xd8, 0x5b,
        0xfb, 0xbc, 0xaa, 0x20, 0xbb, 0xc6, 0x05, 0xfd,
        0xcc, 0xda, 0xa9, 0xce, 0x1d, 0x5f, 0x9b, 0x16,
        0xea, 0x68, 0xac, 0xee, 0xd4, 0x07, 0xd8, 0x3b,
    };
    CHECK(zkstego::score_keyed_cavlc_sign_candidate(schedule_vector[0], blind_key) == expected_first_score);
    const auto keyed_schedule = zkstego::select_keyed_cavlc_sign_candidates(
        schedule_vector, blind_key, schedule_vector.size());
    CHECK(keyed_schedule[0].nal_index == 3 && keyed_schedule[0].macroblock_address == 2);
    CHECK(keyed_schedule[0].category == zkstego::CavlcResidualCategory::ChromaAc);
    CHECK(keyed_schedule[1].nal_index == 7 && keyed_schedule[1].block_index == 3);
    CHECK(keyed_schedule[2].nal_index == 7 && keyed_schedule[2].block_index == 2);
    auto wrong_key = blind_key;
    std::fill(wrong_key.begin(), wrong_key.end(), static_cast<std::uint8_t>(0x01U));
    // v3 frame: [version 0x03][length BE16][payload], no MAC.
    const std::vector<std::uint8_t> expected_frame{0x03, 0x00, 0x05, 0x70, 0x72, 0x6f, 0x6f, 0x66};
    static_assert(zkstego::kCavlcFrameVersion == 3U);
    CHECK(zkstego::pack_cavlc_frame({0x70, 0x72, 0x6f, 0x6f, 0x66}) == expected_frame);
    CHECK(zkstego::unpack_cavlc_frame(expected_frame, 32) ==
        std::vector<std::uint8_t>({0x70, 0x72, 0x6f, 0x6f, 0x66}));
    const std::vector<std::uint8_t> expected_keystream_40{
        0x4b, 0x7a, 0x98, 0xc6, 0xd0, 0x78, 0x7a, 0x38,
        0x1b, 0xbb, 0xb8, 0x61, 0xc9, 0xa1, 0x24, 0xaf,
        0x09, 0x0c, 0xdb, 0x9b, 0x18, 0x70, 0xd7, 0xee,
        0x14, 0xf7, 0x4a, 0x01, 0x63, 0x54, 0x01, 0xe6,
        0x86, 0x60, 0xdf, 0xf9, 0x7f, 0x10, 0x00, 0x7b,
    };
    CHECK(zkstego::cavlc_whitening_keystream(blind_key, 40U) == expected_keystream_40);
    CHECK(zkstego::cavlc_whitening_keystream(blind_key, 0U).empty());
    const std::vector<std::uint8_t> expected_whitened_frame{0x48, 0x7a, 0x9d, 0xb6, 0xa2, 0x17, 0x15, 0x5e};
    for (std::size_t index = 0; index < expected_whitened_frame.size(); ++index) {
        CHECK(static_cast<std::uint8_t>(expected_frame[index] ^ expected_keystream_40[index]) ==
            expected_whitened_frame[index]);
    }
    // Different payloads under one key share the keystream, so the embedded
    // version byte is keystream-masked (not the constant 0x03) and a
    // different key masks the whole header differently.
    CHECK(expected_whitened_frame[0] != zkstego::kCavlcFrameVersion);
    const auto wrong_key_keystream = zkstego::cavlc_whitening_keystream(wrong_key, 3U);
    CHECK(wrong_key_keystream != std::vector<std::uint8_t>(expected_keystream_40.begin(), expected_keystream_40.begin() + 3));
    const auto wrong_key_schedule = zkstego::select_keyed_cavlc_sign_candidates(
        schedule_vector, wrong_key, 1);
    CHECK(wrong_key_schedule[0].nal_index == 7 && wrong_key_schedule[0].macroblock_address == 11);
    CHECK(wrong_key_schedule[0].category == zkstego::CavlcResidualCategory::Luma4x4);
    CHECK(wrong_key_schedule[0].block_index == 2 && wrong_key_schedule[0].rbsp_bit_offset == 90);
    const auto throws_invalid_argument = [](const auto& operation) {
        try { operation(); } catch (const std::invalid_argument&) { return true; }
        return false;
    };
    CHECK(throws_invalid_argument([&] {
        static_cast<void>(zkstego::cavlc_whitening_keystream({0}, 1U));
    }));
    // A v2 frame (version 0x02), a still-whitened frame, a payload longer than
    // the maximum and a length that disagrees with the frame size are refused.
    CHECK(throws_invalid_argument([&] {
        static_cast<void>(zkstego::unpack_cavlc_frame({0x02, 0x00, 0x05, 0x70, 0x72, 0x6f, 0x6f, 0x66}, 32));
    }));
    CHECK(throws_invalid_argument([&] {
        static_cast<void>(zkstego::unpack_cavlc_frame(expected_whitened_frame, 32));
    }));
    CHECK(throws_invalid_argument([&] {
        static_cast<void>(zkstego::unpack_cavlc_frame(expected_frame, 4));
    }));
    CHECK(throws_invalid_argument([&] {
        static_cast<void>(zkstego::unpack_cavlc_frame({0x03, 0x00, 0x06, 0x70, 0x72, 0x6f, 0x6f, 0x66}, 32));
    }));
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
    // The source-dir literal is UTF-8 (/utf-8 on MSVC) and the repository
    // path is not ASCII, so open it through a UTF-8 filesystem path.
    const std::string fixture_path = std::string{ZKSTEGO_PROJECT_SOURCE_DIR} +
        "/data/encoded/foreman_cif_q18_g1_300f.h264";
    std::ifstream fixture(std::filesystem::path(std::u8string(
        reinterpret_cast<const char8_t*>(fixture_path.data()), fixture_path.size())), std::ios::binary);
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
        for (const auto& decoded_macroblock : slice.macroblocks) {
            if (decoded_macroblock.header.mb_type >= 1U && decoded_macroblock.header.mb_type <= 24U) {
                ++i16x16_macroblocks;
            }
            const auto chroma_coded_block_pattern = (decoded_macroblock.header.coded_block_pattern >> 4U) & 0x03U;
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
    // File-mode segment protocol on the real carrier: every IDR is one
    // segment (stored SPS/PPS + IDR) carrying at most 64 scheduled signs.
    constexpr std::size_t kFileBitsPerIdr = 64U;
    const std::vector<std::uint8_t> file_payload{0x70, 0x72, 0x6f, 0x6f, 0x66};
    const auto file_stego = zkstego::embed_cavlc_stream_file(
        fixture_bytes, blind_key, file_payload, kFileBitsPerIdr);
    CHECK(zkstego::extract_cavlc_stream_file(
        file_stego, blind_key, 32, kFileBitsPerIdr) == file_payload);
    CHECK(throws_invalid_argument([&] {
        static_cast<void>(zkstego::extract_cavlc_stream_file(
            file_stego, wrong_key, 32, kFileBitsPerIdr));
    }));
    // The per-IDR cap is part of the schedule: a different cap reads other
    // positions and cannot reproduce the payload. A smaller cap selects the
    // lowest-scored subset of the same segment, so the header may still pass;
    // only the payload's Groth16 proof can then tell it apart.
    const auto wrong_cap_misses_payload = [&] {
        try {
            return zkstego::extract_cavlc_stream_file(file_stego, blind_key, 32, kFileBitsPerIdr / 2U) != file_payload;
        } catch (const std::invalid_argument&) {
            return true;
        }
    }();
    CHECK(wrong_cap_misses_payload);
    CHECK(throws_invalid_argument([&] {
        static_cast<void>(zkstego::embed_cavlc_stream_file(
            fixture_bytes, blind_key, file_payload, 0U));
    }));
    CHECK(throws_invalid_argument([&] {
        static_cast<void>(zkstego::embed_cavlc_stream_file(
            fixture_bytes, {0}, file_payload, kFileBitsPerIdr));
    }));
    CHECK(throws_invalid_argument([&] {
        // 300 IDRs at one bit each cannot hold a 4096-byte payload frame.
        static_cast<void>(zkstego::embed_cavlc_stream_file(
            fixture_bytes, blind_key, std::vector<std::uint8_t>(4096U), 1U));
    }));
    // Sign edits preserve every segment's candidate identities.
    const auto cover_segments = zkstego::analyze_cavlc_stream_file(fixture_bytes);
    const auto stego_segments = zkstego::analyze_cavlc_stream_file(file_stego);
    CHECK(cover_segments.size() == 300U);
    CHECK(stego_segments.size() == cover_segments.size());
    CHECK(cover_segments.front().analysis_nal_index == 4U);  // SPS PPS (stored) SPS PPS IDR
    for (std::size_t segment = 0; segment < cover_segments.size(); ++segment) {
        const auto& cover = cover_segments[segment];
        const auto& stego = stego_segments[segment];
        CHECK(cover.idr_nal_index == stego.idr_nal_index);
        CHECK(cover.analysis_nal_index == stego.analysis_nal_index);
        CHECK(segment == 0U || cover.idr_nal_index > cover_segments[segment - 1U].idr_nal_index);
        CHECK(cover.candidates.size() == stego.candidates.size());
        for (std::size_t index = 0; index < cover.candidates.size(); ++index) {
            CHECK(zkstego::serialize_cavlc_sign_candidate(cover.candidates[index]) ==
                zkstego::serialize_cavlc_sign_candidate(stego.candidates[index]));
        }
    }
    // Reproduce the encoder schedule from the audit view: per segment the
    // lowest min(cap, candidates) keyed scores, global frame-bit order.
    const auto cover_file_units = zkstego::split_annex_b(fixture_bytes);
    const auto stego_file_units = zkstego::split_annex_b(file_stego);
    const auto file_bit = [](const std::vector<zkstego::AnnexBNalUnit>& units, std::size_t nal, std::size_t offset) {
        const auto rbsp = units.at(nal).rbsp();
        return static_cast<std::uint8_t>((rbsp.at(offset / 8U) >> (7U - offset % 8U)) & 1U);
    };
    const auto frame_bit_count = (3U + file_payload.size()) * 8U;
    std::vector<std::pair<std::size_t, std::size_t>> placements;
    for (const auto& segment : cover_segments) {
        if (placements.size() == frame_bit_count) break;
        const auto capacity = std::min(kFileBitsPerIdr, segment.candidates.size());
        for (const auto& candidate : zkstego::select_keyed_cavlc_sign_candidates(
                 segment.candidates, blind_key, capacity)) {
            if (placements.size() == frame_bit_count) break;
            placements.emplace_back(segment.idr_nal_index, candidate.rbsp_bit_offset);
        }
    }
    CHECK(placements.size() == frame_bit_count);
    std::vector<std::uint8_t> raw_frame_bytes(frame_bit_count / 8U);
    for (std::size_t index = 0; index < placements.size(); ++index) {
        const auto bit = file_bit(stego_file_units, placements[index].first, placements[index].second);
        raw_frame_bytes[index / 8U] |= static_cast<std::uint8_t>(bit << (7U - index % 8U));
    }
    // Whitening on the real carrier: the scheduled sign bits are the whitened
    // frame (frame XOR keystream), never the plaintext frame.
    CHECK(raw_frame_bytes == expected_whitened_frame);
    CHECK(raw_frame_bytes != expected_frame);
    // Every other candidate sign is unchanged.
    std::size_t changed_signs = 0;
    for (const auto& segment : cover_segments) {
        for (const auto& candidate : segment.candidates) {
            const auto before = file_bit(cover_file_units, segment.idr_nal_index, candidate.rbsp_bit_offset);
            const auto after = file_bit(stego_file_units, segment.idr_nal_index, candidate.rbsp_bit_offset);
            if (before == after) continue;
            ++changed_signs;
            CHECK(std::find(placements.begin(), placements.end(),
                std::make_pair(segment.idr_nal_index, candidate.rbsp_bit_offset)) != placements.end());
        }
    }
    CHECK(changed_signs > 0U && changed_signs <= frame_bit_count);
    const auto flip_frame_bit = [&](const std::size_t frame_bit) {
        const auto target = placements.at(frame_bit);
        const auto bit = file_bit(stego_file_units, target.first, target.second);
        return zkstego::patch_annex_b_rbsp_plan(file_stego, {
            {target.first, {{target.second, {static_cast<std::uint8_t>(1U - bit)}}}},
        });
    };
    // The v3 channel checks only the header: a flipped version bit is refused,
    // while a flipped payload bit decodes to a different payload. Detecting that
    // is the job of the Groth16 proof carried in the payload, not of the channel.
    CHECK(throws_invalid_argument([&] {
        static_cast<void>(zkstego::extract_cavlc_stream_file(flip_frame_bit(0U), blind_key, 32, kFileBitsPerIdr));
    }));
    const auto altered_payload = zkstego::extract_cavlc_stream_file(flip_frame_bit(24U), blind_key, 32, kFileBitsPerIdr);
    CHECK(altered_payload.size() == file_payload.size());
    CHECK(altered_payload != file_payload);
    CHECK(static_cast<std::uint8_t>(altered_payload[0] ^ file_payload[0]) == 0x80U);

    // Video binding digest: embedding (and any edit of a carrier sign, which the
    // payload's proof catches instead) keeps it; flipping any other candidate
    // sign, its parameters, another key and a truncated file change it.
    const auto digest_of = [&](const std::vector<std::uint8_t>& video, const std::vector<std::uint8_t>& key,
                               const std::size_t bits, const std::size_t cap) {
        return zkstego::cavlc_video_binding_digest(video, key, bits, cap).digest;
    };
    const auto cover_digest = zkstego::cavlc_video_binding_digest(fixture_bytes, blind_key, frame_bit_count, kFileBitsPerIdr);
    CHECK(digest_of(file_stego, blind_key, frame_bit_count, kFileBitsPerIdr) == cover_digest.digest);
    CHECK(cover_digest.carrier_segments == 1U && cover_digest.nal_units == cover_file_units.size());
    CHECK(digest_of(flip_frame_bit(24U), blind_key, frame_bit_count, kFileBitsPerIdr) == cover_digest.digest);
    const auto unscheduled = std::find_if(cover_segments.front().candidates.begin(), cover_segments.front().candidates.end(),
        [&](const auto& candidate) {
            return std::find(placements.begin(), placements.end(),
                std::make_pair(cover_segments.front().idr_nal_index, candidate.rbsp_bit_offset)) == placements.end();
        });
    CHECK(unscheduled != cover_segments.front().candidates.end());
    const auto unscheduled_bit = file_bit(stego_file_units, cover_segments.front().idr_nal_index, unscheduled->rbsp_bit_offset);
    const auto flipped_unscheduled = zkstego::patch_annex_b_rbsp_plan(file_stego, {
        {cover_segments.front().idr_nal_index,
         {{unscheduled->rbsp_bit_offset, {static_cast<std::uint8_t>(1U - unscheduled_bit)}}}},
    });
    CHECK(digest_of(flipped_unscheduled, blind_key, frame_bit_count, kFileBitsPerIdr) != cover_digest.digest);
    CHECK(digest_of(fixture_bytes, blind_key, frame_bit_count + 8U, kFileBitsPerIdr) != cover_digest.digest);
    CHECK(digest_of(fixture_bytes, wrong_key, frame_bit_count, kFileBitsPerIdr) != cover_digest.digest);
    const std::vector<std::uint8_t> truncated_stego(file_stego.begin(), file_stego.begin() +
        static_cast<std::ptrdiff_t>(file_stego.size() / 2U));
    CHECK(digest_of(truncated_stego, blind_key, frame_bit_count, kFileBitsPerIdr) != cover_digest.digest);
    CHECK(throws_invalid_argument([&] {
        static_cast<void>(zkstego::cavlc_video_binding_digest(fixture_bytes, blind_key, 0U, kFileBitsPerIdr));
    }));

    // Realtime protocol contract: each IDR is selected independently, and a
    // stateful blind decoder reconstructs the frame across IDRs.
    const auto stream_fixture_units = zkstego::split_annex_b(fixture_bytes);
    std::vector<zkstego::AnnexBNalUnit> current_parameter_sets;
    std::vector<std::vector<std::uint8_t>> idr_segments;
    bool first_idr_segment = true;
    for (const auto& unit : stream_fixture_units) {
        if (unit.nal_unit_type == 7U || unit.nal_unit_type == 8U) {
            const auto existing = std::find_if(current_parameter_sets.begin(), current_parameter_sets.end(),
                [&](const auto& parameter_set) { return parameter_set.nal_unit_type == unit.nal_unit_type; });
            if (existing == current_parameter_sets.end()) current_parameter_sets.push_back(unit);
            else *existing = unit;
        } else if (unit.nal_unit_type == 5U) {
            auto frame_units = first_idr_segment ? current_parameter_sets : std::vector<zkstego::AnnexBNalUnit>{};
            frame_units.push_back(unit);
            idr_segments.push_back(zkstego::assemble_annex_b(frame_units));
            first_idr_segment = false;
        }
    }
    CHECK(idr_segments.size() == 300U);
    std::vector<std::uint8_t> stream_payload(257U);
    for (std::size_t index = 0; index < stream_payload.size(); ++index) {
        stream_payload[index] = static_cast<std::uint8_t>((index * 37U + 11U) & 0xffU);
    }
    zkstego::CavlcStreamEncoder stream_encoder(blind_key, stream_payload, 64U);
    zkstego::CavlcStreamDecoder stream_decoder(blind_key, 512U, 64U);
    zkstego::CavlcStreamDecoder wrong_stream_decoder(wrong_key, 512U, 64U);
    bool wrong_stream_rejected = false;
    std::string wrong_stream_error;
    std::size_t frames_to_complete = 0;
    for (const auto& segment : idr_segments) {
        const auto encoded_segment = stream_encoder.process_segment(segment);
        CHECK(encoded_segment.output.size() == segment.size());
        if (encoded_segment.session_complete && frames_to_complete == 0U) {
            frames_to_complete = static_cast<std::size_t>(&segment - idr_segments.data()) + 1U;
        }
        stream_decoder.consume_segment(encoded_segment.output);
        if (!wrong_stream_rejected) {
            try {
                wrong_stream_decoder.consume_segment(encoded_segment.output);
            } catch (const std::invalid_argument& error) {
                wrong_stream_rejected = true;
                wrong_stream_error = error.what();
            }
        }
    }
    CHECK(stream_encoder.complete());
    CHECK(stream_decoder.complete());
    CHECK(stream_decoder.payload() == stream_payload);
    CHECK(wrong_stream_rejected);
    CHECK(wrong_stream_error == "CAVLC stream version is invalid" ||
        wrong_stream_error == "CAVLC stream length exceeds configured maximum");
    CHECK(wrong_stream_decoder.failed());
    CHECK(wrong_stream_decoder.buffered_bit_count() == 0U);
    try {
        wrong_stream_decoder.consume_segment(idr_segments.back());
        CHECK(false);
    } catch (const std::invalid_argument& error) {
        CHECK(wrong_stream_error == error.what());
    }
    CHECK(wrong_stream_decoder.buffered_bit_count() == 0U);
    CHECK(frames_to_complete > 1U);
    CHECK(frames_to_complete < 300U);

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

    // Incremental reader must recognize a four-byte start code split across
    // its 64 KiB input reads while retaining no more than the configured NAL.
    std::vector<std::uint8_t> large_first_nal{0x00, 0x00, 0x00, 0x01, 0x65};
    large_first_nal.resize(65534U, 0x55);
    const std::vector<std::uint8_t> final_nal{0x00, 0x00, 0x00, 0x01, 0x41, 0x80};
    auto incremental_bytes = large_first_nal;
    incremental_bytes.insert(incremental_bytes.end(), final_nal.begin(), final_nal.end());
    const std::string incremental_text(
        reinterpret_cast<const char*>(incremental_bytes.data()), incremental_bytes.size());
    std::istringstream incremental_input(incremental_text, std::ios::in | std::ios::binary);
    zkstego::AnnexBNalStreamReader incremental_reader(incremental_input, 70000U);
    std::vector<std::uint8_t> streamed_nal;
    CHECK(incremental_reader.read_next(streamed_nal));
    CHECK(streamed_nal == large_first_nal);
    CHECK(incremental_reader.read_next(streamed_nal));
    CHECK(streamed_nal == final_nal);
    CHECK(!incremental_reader.read_next(streamed_nal));

    large_first_nal.resize(65535U, 0x55);
    const std::vector<std::uint8_t> final_three_byte_nal{0x00, 0x00, 0x01, 0x41, 0x80};
    incremental_bytes = large_first_nal;
    incremental_bytes.insert(incremental_bytes.end(), final_three_byte_nal.begin(), final_three_byte_nal.end());
    const std::string incremental_three_text(
        reinterpret_cast<const char*>(incremental_bytes.data()), incremental_bytes.size());
    std::istringstream incremental_three_input(incremental_three_text, std::ios::in | std::ios::binary);
    zkstego::AnnexBNalStreamReader incremental_three_reader(incremental_three_input, 70000U);
    CHECK(incremental_three_reader.read_next(streamed_nal));
    CHECK(streamed_nal == large_first_nal);
    CHECK(incremental_three_reader.read_next(streamed_nal));
    CHECK(streamed_nal == final_three_byte_nal);
    CHECK(!incremental_three_reader.read_next(streamed_nal));

    std::vector<std::uint8_t> oversized_nal{0x00, 0x00, 0x01, 0x65};
    oversized_nal.resize(32U, 0x55);
    const std::string oversized_text(reinterpret_cast<const char*>(oversized_nal.data()), oversized_nal.size());
    std::istringstream oversized_input(oversized_text, std::ios::in | std::ios::binary);
    zkstego::AnnexBNalStreamReader bounded_reader(oversized_input, 16U);
    bool oversized_rejected = false;
    try {
        static_cast<void>(bounded_reader.read_next(streamed_nal));
    } catch (const std::invalid_argument&) {
        oversized_rejected = true;
    }
    CHECK(oversized_rejected);

    const std::string invalid_prefix_text("x\0\0\1\x65", 5U);
    std::istringstream invalid_prefix_input(invalid_prefix_text, std::ios::in | std::ios::binary);
    zkstego::AnnexBNalStreamReader invalid_prefix_reader(invalid_prefix_input);
    bool invalid_prefix_rejected = false;
    try {
        static_cast<void>(invalid_prefix_reader.read_next(streamed_nal));
    } catch (const std::invalid_argument&) {
        invalid_prefix_rejected = true;
    }
    CHECK(invalid_prefix_rejected);

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

    const auto throws_exception = [](const auto& operation) {
        try { operation(); } catch (const std::exception&) { return true; }
        return false;
    };

    // Streaming reader regression: a stream buffer that never reports
    // buffered input (in_avail()==0, like synced std::cin) must still split a
    // ~2 MB stream in linear time. The previous reader rescanned the pending
    // NAL from offset zero after every single-byte read (quadratic).
    {
        std::vector<std::uint8_t> synthetic_stream;
        std::vector<std::size_t> synthetic_sizes;
        for (std::size_t index = 0; index < 4U; ++index) {
            const std::size_t nal_size = 500000U + index * 1000U;
            const auto start = synthetic_stream.size();
            synthetic_stream.insert(synthetic_stream.end(), {0x00, 0x00, 0x00, 0x01, 0x65});
            synthetic_stream.resize(start + nal_size, static_cast<std::uint8_t>(0x55U + index));
            synthetic_sizes.push_back(nal_size);
        }
        class OneByteStreambuf : public std::streambuf {
        public:
            explicit OneByteStreambuf(const std::vector<std::uint8_t>& bytes) : bytes_(bytes) {}
        protected:
            std::streamsize showmanyc() override { return 0; }
            int_type underflow() override {
                return position_ < bytes_.size() ? traits_type::to_int_type(static_cast<char>(bytes_[position_]))
                                                 : traits_type::eof();
            }
            int_type uflow() override {
                return position_ < bytes_.size() ? traits_type::to_int_type(static_cast<char>(bytes_[position_++]))
                                                 : traits_type::eof();
            }
        private:
            const std::vector<std::uint8_t>& bytes_;
            std::size_t position_{};
        };
        OneByteStreambuf one_byte_buffer(synthetic_stream);
        std::istream one_byte_input(&one_byte_buffer);
        CHECK(one_byte_input.rdbuf()->in_avail() == 0);
        zkstego::AnnexBNalStreamReader slow_reader(one_byte_input);
        const auto started = std::chrono::steady_clock::now();
        std::size_t streamed_count = 0;
        std::vector<std::uint8_t> slow_nal;
        while (slow_reader.read_next(slow_nal)) {
            CHECK(streamed_count < synthetic_sizes.size());
            CHECK(slow_nal.size() == synthetic_sizes[streamed_count]);
            CHECK(slow_nal[4] == 0x65U && slow_nal.back() == static_cast<std::uint8_t>(0x55U + streamed_count));
            ++streamed_count;
        }
        const auto elapsed = std::chrono::steady_clock::now() - started;
        CHECK(streamed_count == synthetic_sizes.size());
        CHECK(elapsed < std::chrono::seconds(2));
    }

    // SPS with a hostile picture size is rejected before any per-macroblock
    // allocation (width 1001 MBs exceeds the 543-MB dimension bound).
    {
        std::string sps_bits = "010000101100000000001101";  // profile 66, flags, level 13
        const auto append_ue = [&](const std::uint32_t value) {
            const auto code = value + 1U;
            std::string binary;
            for (auto remaining = code; remaining != 0U; remaining >>= 1U) {
                binary.insert(binary.begin(), (remaining & 1U) != 0U ? '1' : '0');
            }
            sps_bits.append(binary.size() - 1U, '0');
            sps_bits += binary;
        };
        append_ue(0);     // seq_parameter_set_id
        append_ue(0);     // log2_max_frame_num_minus4
        append_ue(2);     // pic_order_cnt_type
        append_ue(0);     // max_num_ref_frames
        sps_bits += '0';  // gaps_in_frame_num_value_allowed_flag
        append_ue(1000);  // pic_width_in_mbs_minus1
        append_ue(0);     // pic_height_in_map_units_minus1
        sps_bits += "11"; // frame_mbs_only_flag, then rbsp stop bit
        CHECK(throws_invalid_argument([&] { static_cast<void>(zkstego::parse_baseline_sps(bits_to_bytes(sps_bits))); }));
        auto huge_sps = sps;
        huge_sps.pic_width_in_mbs_minus1 = 400;
        huge_sps.pic_height_in_map_units_minus1 = 400;  // 160801 MBs > 36864
        CHECK(throws_invalid_argument([&] { static_cast<void>(zkstego::validated_picture_macroblock_count(huge_sps)); }));
        CHECK(zkstego::validated_picture_macroblock_count(sps) == 22U * 18U);
    }

    // Truncated or malformed NALs fail with an exception, never a crash.
    {
        for (std::size_t keep = 0; keep < inspectable_annex_b.size(); ++keep) {
            const std::vector<std::uint8_t> truncated(
                inspectable_annex_b.begin(), inspectable_annex_b.begin() + static_cast<std::ptrdiff_t>(keep));
            try {
                static_cast<void>(zkstego::decode_baseline_i_idr_slices(truncated));
                static_cast<void>(zkstego::inspect_baseline_idr_headers(truncated));
            } catch (const std::exception&) {
            }
        }
        auto truncated_idr = inspectable_annex_b;
        truncated_idr.resize(inspectable_annex_b.size() - 12U);
        CHECK(throws_exception([&] { static_cast<void>(zkstego::decode_baseline_i_idr_slices(truncated_idr)); }));
        CHECK(throws_exception([&] { static_cast<void>(zkstego::parse_baseline_sps({0x42, 0xc0})); }));
        CHECK(throws_exception([&] { static_cast<void>(zkstego::parse_baseline_pps({})); }));
        // nC == -2 (4:2:2 ChromaDC) is outside the supported profile.
        CHECK(throws_invalid_argument([&] { static_cast<void>(zkstego::parse_cavlc_coeff_token({0x80}, 0, -2)); }));
    }

    // PPS bottom_field_pic_order_in_frame_present_flag adds
    // delta_pic_order_cnt_bottom to POC-type-0 slice headers.
    {
        const auto bottom_field_pps = zkstego::parse_baseline_pps({0xde, 0x3c, 0x80});
        CHECK(bottom_field_pps.bottom_field_pic_order_in_frame_present_flag);
        CHECK(bottom_field_pps.deblocking_filter_control_present_flag);
        CHECK(!pps.bottom_field_pic_order_in_frame_present_flag);
        zkstego::H264BaselinePps bottom_field_header_pps;
        bottom_field_header_pps.bottom_field_pic_order_in_frame_present_flag = true;
        const auto bottom_field_header = zkstego::parse_baseline_idr_slice_header(
            {0xb9, 0xd5, 0x90}, poc_type_zero_sps, bottom_field_header_pps);
        CHECK(bottom_field_header.frame_num == 3);
        CHECK(bottom_field_header.pic_order_cnt_lsb == 5);
        CHECK(bottom_field_header.delta_pic_order_cnt_bottom == -1);
        CHECK(bottom_field_header.slice_qp_delta == 0);
        CHECK(bottom_field_header.data_bit_offset == 20);
    }

    // Stream parameter-set context: same id replaces, a second id is rejected.
    {
        std::vector<zkstego::AnnexBNalUnit> context;
        zkstego::AnnexBNalUnit pps_zero;
        pps_zero.start_code_size = 4;
        pps_zero.nal_unit_type = 8;
        pps_zero.payload = {0xce, 0x04, 0xcb, 0x20};
        auto pps_zero_repeat = pps_zero;
        pps_zero_repeat.payload = {0xce, 0x06};
        auto pps_one = pps_zero;
        pps_one.payload = {0x40};
        zkstego::update_parameter_set_context(context, pps_zero);
        zkstego::update_parameter_set_context(context, pps_zero_repeat);
        CHECK(context.size() == 1U && context[0].payload == pps_zero_repeat.payload);
        CHECK(zkstego::parameter_set_id(pps_one) == 1U);
        CHECK(throws_invalid_argument([&] { zkstego::update_parameter_set_context(context, pps_one); }));
        CHECK(context.size() == 1U && context[0].payload == pps_zero_repeat.payload);
    }
}
