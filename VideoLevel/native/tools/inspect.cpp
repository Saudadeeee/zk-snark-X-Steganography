// zkstego_inspect: read-only inspection of a Baseline CAVLC Annex-B file.
// All syntax, coefficients and candidates come from the native parser.
//
//   zkstego_inspect <input.h264>                       JSON schema 1: NALs, IDR slices, candidates
//   zkstego_inspect <input.h264> --macroblock NAL MB   JSON macroblock-detail-1
//   zkstego_inspect <input.h264> --summary             human-readable text summary
//   zkstego_inspect <input.h264> --segments MAX_BITS   JSON segments-1: the segment-protocol
//                                                      schedule input per IDR segment
#include "zkstego/cavlc_stream.hpp"
#include "cli_io.hpp"

#include <algorithm>
#include <cstdint>
#include <iostream>
#include <limits>
#include <map>
#include <sstream>
#include <stdexcept>
#include <string>
#include <vector>

namespace {

// Output is buffered and written only after every check passed, so a failure
// never leaves truncated JSON or text on stdout next to a non-zero exit code.
std::ostringstream out;

constexpr std::size_t kMaxInspectBytes = 64U * 1024U * 1024U;
constexpr char kUsage[] =
    "usage: zkstego_inspect <input.h264> [--summary | --macroblock NAL_INDEX MB_ADDRESS | --segments MAX_BITS_PER_IDR]";

// Whole-string unsigned decimal with an explicit upper bound (rejects "12abc", "-1", overflow).
unsigned long long parse_index(const std::string& text, const unsigned long long maximum) {
    if (text.empty() || text.find_first_not_of("0123456789") != std::string::npos) {
        throw std::invalid_argument("index must be a non-negative decimal integer");
    }
    std::size_t consumed = 0;
    const auto value = std::stoull(text, &consumed);
    if (consumed != text.size() || value > maximum) throw std::invalid_argument("index is out of range");
    return value;
}

int emit() {
    std::cout << out.str();
    std::cout.flush();
    return std::cout ? 0 : 2;
}

std::vector<std::uint8_t> read_input(const std::string& path) {
    auto bytes = zkstego::cli::read_binary_file(path, kMaxInspectBytes);
    if (bytes.empty()) throw std::runtime_error("inspect input must be 1..64 MiB");
    return bytes;
}

template <class T> void numbers(const T& values) {
    out << '[';
    bool first = true;
    for (const auto value : values) {
        if (!first) out << ',';
        first = false;
        out << +value;
    }
    out << ']';
}

std::uint8_t rbsp_bit(const std::vector<std::uint8_t>& rbsp, const std::size_t offset) {
    return static_cast<std::uint8_t>((rbsp.at(offset / 8U) >> (7U - offset % 8U)) & 1U);
}

// Low-drift tier and its sign-invariant inputs (see cavlc_candidate_tier).
void tier_fields(const zkstego::CavlcSignCandidate& candidate) {
    out << ",\"mb_row\":" << candidate.mb_row
        << ",\"mb_height\":" << candidate.mb_height
        << ",\"freq\":" << +candidate.frequency
        << ",\"tier\":" << +zkstego::cavlc_candidate_tier(candidate);
}

std::int64_t initial_slice_qp(const zkstego::CavlcDecodedIdrSlice& slice) {
    const auto qp = std::int64_t{26} + slice.pps.pic_init_qp_minus26 + slice.header.slice_qp_delta;
    if (qp < 0 || qp > 51) throw std::invalid_argument("slice QP outside Baseline range");
    return qp;
}

const char* nal_type_name(const std::uint8_t type) {
    switch (type) {
    case 1: return "non-IDR slice";
    case 5: return "IDR slice";
    case 6: return "SEI";
    case 7: return "SPS";
    case 8: return "PPS";
    case 9: return "AUD";
    default: return "other";
    }
}

const zkstego::CavlcDecodedLumaBlock& block_for(
    const zkstego::CavlcDecodedIMacroblock& mb,
    const zkstego::CavlcSignCandidate& candidate) {
    switch (candidate.category) {
    case zkstego::CavlcResidualCategory::LumaDc: return mb.luma_dc;
    case zkstego::CavlcResidualCategory::Luma4x4: return mb.luma.blocks.at(candidate.block_index);
    case zkstego::CavlcResidualCategory::ChromaDc: return mb.chroma_dc.at(candidate.block_index);
    case zkstego::CavlcResidualCategory::ChromaAc: return mb.chroma_ac.at(candidate.block_index);
    }
    throw std::invalid_argument("unknown residual category");
}

void block_json(const char* category, const std::size_t index, const zkstego::CavlcDecodedLumaBlock& block) {
    // A block that the coded_block_pattern skipped was never parsed: its offsets stay zero.
    const bool coded = block.token.level_bit_offset != 0;
    out << "{\"category\":\"" << category << "\",\"index\":" << index << ",\"coded\":" << (coded ? "true" : "false");
    if (coded) {
        out << ",\"n_c\":" << block.token.n_c
            << ",\"coeff_token_bit\":" << block.token.start_bit_offset
            << ",\"total_coeff\":" << block.token.total_coefficients
            << ",\"trailing_ones\":" << block.token.trailing_ones
            << ",\"sign_offsets\":";
        numbers(block.token.sign_bit_offsets);
        out << ",\"level_bit\":" << block.token.level_bit_offset
            << ",\"tail_bit\":" << block.levels.next_bit_offset
            << ",\"end_bit\":" << block.tail.next_bit_offset
            << ",\"trailing_one_values\":";
        numbers(block.levels.trailing_one_values);
        out << ",\"level_values\":";
        numbers(block.levels.values);
        out << ",\"total_zeros\":" << block.tail.total_zeros << ",\"runs\":";
        numbers(block.tail.runs);
        out << ",\"coefficients_scan\":";
        numbers(block.coefficients);
    }
    out << '}';
}

// Full syntax-level view of one macroblock plus compact headers of its whole
// slice (needed to derive Intra4x4PredMode and QP_Y from neighbours).
int trace_macroblock(const std::string& path, const std::size_t nal_index, const std::uint32_t address) {
    const auto bytes = read_input(path);
    const auto units = zkstego::split_annex_b(bytes);
    const auto slices = zkstego::decode_baseline_i_idr_slices(bytes);
    const zkstego::CavlcDecodedIdrSlice* slice = nullptr;
    for (const auto& candidate : slices) {
        if (candidate.nal_index == nal_index) slice = &candidate;
    }
    if (slice == nullptr) throw std::invalid_argument("NAL index is not a supported IDR slice");
    const auto first = slice->header.first_mb_in_slice;
    if (address < first || address - first >= slice->macroblocks.size()) {
        throw std::invalid_argument("macroblock address is outside the slice");
    }
    const auto rbsp = units.at(nal_index).rbsp();
    out << "{\"schema\":\"macroblock-detail-1\",\"nal_index\":" << nal_index
        << ",\"mb_width\":" << slice->sps.pic_width_in_mbs_minus1 + 1
        << ",\"mb_height\":" << slice->sps.pic_height_in_map_units_minus1 + 1
        << ",\"pic_init_qp\":" << std::int64_t{26} + slice->pps.pic_init_qp_minus26
        << ",\"slice_qp_delta\":" << slice->header.slice_qp_delta
        << ",\"data_bit_offset\":" << slice->header.data_bit_offset
        << ",\"trailing_bit_offset\":" << slice->rbsp_trailing_bit_offset
        << ",\"rbsp_hex\":\"";
    constexpr char hex[] = "0123456789abcdef";
    for (const auto byte : rbsp) out << hex[byte >> 4U] << hex[byte & 15U];
    out << "\",\"macroblocks\":[";
    std::size_t previous_end = slice->header.data_bit_offset;
    for (std::size_t i = 0; i < slice->macroblocks.size(); ++i) {
        const auto& mb = slice->macroblocks[i];
        if (i) out << ',';
        out << "{\"address\":" << mb.address << ",\"start_bit\":" << previous_end
            << ",\"residual_bit\":" << mb.header.residual_bit_offset
            << ",\"end_bit\":" << mb.next_bit_offset
            << ",\"mb_type\":" << mb.header.mb_type
            << ",\"cbp\":" << mb.header.coded_block_pattern
            << ",\"mb_qp_delta\":" << mb.header.mb_qp_delta
            << ",\"rem_intra4x4\":";
        numbers(mb.header.intra_4x4_prediction_modes);
        out << '}';
        previous_end = mb.next_bit_offset;
    }
    const auto& mb = slice->macroblocks.at(address - first);
    out << "],\"detail\":{\"address\":" << address << ",\"blocks\":[";
    bool first_block = true;
    const auto separator = [&first_block] {
        if (!first_block) out << ',';
        first_block = false;
    };
    if (mb.header.mb_type >= 1) {
        separator();
        block_json("LumaDC", 0, mb.luma_dc);
    }
    for (std::size_t i = 0; i < mb.luma.blocks.size(); ++i) {
        separator();
        block_json("Luma4x4", i, mb.luma.blocks[i]);
    }
    for (std::size_t i = 0; i < mb.chroma_dc.size(); ++i) {
        separator();
        block_json("ChromaDC", i, mb.chroma_dc[i]);
    }
    for (std::size_t i = 0; i < mb.chroma_ac.size(); ++i) {
        separator();
        block_json("ChromaAC", i, mb.chroma_ac[i]);
    }
    out << "]}}\n";
    return emit();
}

// Default JSON (schema 1): every NAL, every decoded IDR slice, every
// whole-file trailing-one sign candidate with its current sign bit.
int trace(const std::string& path) {
    const auto bytes = read_input(path);
    const auto units = zkstego::split_annex_b(bytes);
    const auto slices = zkstego::decode_baseline_i_idr_slices(bytes);
    const auto candidates = zkstego::collect_cavlc_trailing_one_sign_candidates(slices);
    std::map<std::size_t, std::size_t> slice_by_nal;
    for (std::size_t i = 0; i < slices.size(); ++i) slice_by_nal.emplace(slices[i].nal_index, i);
    out << "{\"schema\":1,\"bytes\":" << bytes.size() << ",\"nals\":[";
    for (std::size_t i = 0; i < units.size(); ++i) {
        const auto& nal = units[i];
        if (i) out << ',';
        out << "{\"index\":" << i << ",\"offset\":" << nal.start_offset
            << ",\"start_code_bytes\":" << nal.start_code_size
            << ",\"type\":" << +nal.nal_unit_type << ",\"ref_idc\":" << +nal.nal_ref_idc
            << ",\"ebsp_bytes\":" << nal.payload.size() << ",\"rbsp_bytes\":" << nal.rbsp().size() << '}';
    }
    out << "],\"slices\":[";
    for (std::size_t i = 0; i < slices.size(); ++i) {
        const auto& slice = slices[i];
        const auto initial_qp = initial_slice_qp(slice);
        if (i) out << ',';
        out << "{\"nal_index\":" << slice.nal_index
            << ",\"profile_idc\":" << +slice.sps.profile_idc
            << ",\"level_idc\":" << +slice.sps.level_idc
            << ",\"mb_width\":" << slice.sps.pic_width_in_mbs_minus1 + 1
            << ",\"mb_height\":" << slice.sps.pic_height_in_map_units_minus1 + 1
            << ",\"macroblocks\":" << slice.macroblocks.size()
            << ",\"first_mb\":" << slice.header.first_mb_in_slice
            << ",\"slice_type\":" << slice.header.slice_type
            << ",\"frame_num\":" << slice.header.frame_num
            << ",\"idr_pic_id\":" << slice.header.idr_pic_id
            << ",\"initial_qp\":" << initial_qp
            << ",\"data_bit_offset\":" << slice.header.data_bit_offset
            << ",\"trailing_bit_offset\":" << slice.rbsp_trailing_bit_offset << '}';
    }
    out << "],\"candidates\":[";
    std::size_t cached_nal = units.size();
    std::vector<std::uint8_t> rbsp;
    for (std::size_t i = 0; i < candidates.size(); ++i) {
        const auto& c = candidates[i];
        const auto& slice = slices.at(slice_by_nal.at(c.nal_index));
        const auto& mb = slice.macroblocks.at(c.macroblock_address - slice.header.first_mb_in_slice);
        if (mb.address != c.macroblock_address) throw std::runtime_error("non-raster macroblock trace");
        const auto& block = block_for(mb, c);
        if (cached_nal != c.nal_index) { cached_nal = c.nal_index; rbsp = units.at(c.nal_index).rbsp(); }
        if (i) out << ',';
        out << "{\"id\":[" << c.nal_index << ',' << c.macroblock_address << ','
            << +static_cast<std::uint8_t>(c.category) << ',' << +c.block_index << ',' << c.rbsp_bit_offset
            << "],\"bit\":" << +rbsp_bit(rbsp, c.rbsp_bit_offset) << ",\"mb_type\":" << mb.header.mb_type
            << ",\"total_coeff\":" << block.token.total_coefficients
            << ",\"trailing_ones\":" << block.token.trailing_ones << ",\"sign_offsets\":";
        numbers(block.token.sign_bit_offsets);
        out << ",\"coefficients_scan\":";
        numbers(block.coefficients);
        tier_fields(c);
        out << '}';
    }
    out << "]}\n";
    return emit();
}

// Human-readable summary: NAL list, IDR count, then one line per decoded IDR
// slice with macroblocks, QP, bit offsets and trailing-one sign candidates.
int summary(const std::string& path) {
    const auto bytes = read_input(path);
    const auto units = zkstego::split_annex_b(bytes);
    const auto slices = zkstego::decode_baseline_i_idr_slices(bytes);
    const auto candidates = zkstego::collect_cavlc_trailing_one_sign_candidates(slices);
    std::map<std::size_t, std::size_t> candidates_by_nal;
    for (const auto& candidate : candidates) ++candidates_by_nal[candidate.nal_index];
    const auto idr_count = static_cast<std::size_t>(std::count_if(units.begin(), units.end(),
        [](const auto& unit) { return unit.is_idr(); }));
    out << "file_bytes=" << bytes.size() << " nal_units=" << units.size() << " idr_count=" << idr_count << '\n';
    for (std::size_t i = 0; i < units.size(); ++i) {
        const auto& nal = units[i];
        out << "nal=" << i << " type=" << +nal.nal_unit_type << " (" << nal_type_name(nal.nal_unit_type) << ")"
            << " offset=" << nal.start_offset << " ref_idc=" << +nal.nal_ref_idc
            << " ebsp_bytes=" << nal.payload.size() << '\n';
    }
    std::size_t decoded_macroblocks = 0;
    for (const auto& slice : slices) {
        decoded_macroblocks += slice.macroblocks.size();
        const auto found = candidates_by_nal.find(slice.nal_index);
        out << "slice nal=" << slice.nal_index
            << " size_mbs=" << slice.sps.pic_width_in_mbs_minus1 + 1 << 'x' << slice.sps.pic_height_in_map_units_minus1 + 1
            << " first_mb=" << slice.header.first_mb_in_slice
            << " macroblocks=" << slice.macroblocks.size()
            << " slice_type=" << slice.header.slice_type
            << " frame_num=" << slice.header.frame_num
            << " idr_pic_id=" << slice.header.idr_pic_id
            << " initial_qp=" << initial_slice_qp(slice)
            << " data_bit=" << slice.header.data_bit_offset
            << " trailing_bit=" << slice.rbsp_trailing_bit_offset
            << " candidates=" << (found == candidates_by_nal.end() ? 0U : found->second) << '\n';
    }
    out << "decoded_idr_slices=" << slices.size() << " decoded_i_macroblocks=" << decoded_macroblocks
        << " trailing_one_sign_candidates=" << candidates.size() << '\n';
    return emit();
}

// Segment-protocol audit view (schema "segments-1"). For each IDR segment the
// candidates are exactly those the stream codec schedules from: "id" is the
// segment-relative identity scored by HMAC(schedule_key, id); nal_index and
// rbsp_bit_offset locate the same sign bit in this file; "bit" is its value;
// mb_row, mb_height, freq and tier are the low-drift ranking inputs.
int segments(const std::string& path, const std::size_t maximum_bits_per_idr) {
    const auto bytes = read_input(path);
    const auto units = zkstego::split_annex_b(bytes);
    const auto analysis = zkstego::analyze_cavlc_stream_file(bytes);
    std::size_t raw_candidates = 0;
    std::size_t capacity_bits = 0;
    for (const auto& segment : analysis) {
        raw_candidates += segment.candidates.size();
        capacity_bits += std::min(maximum_bits_per_idr, segment.candidates.size());
    }
    out << "{\"schema\":\"segments-1\",\"bytes\":" << bytes.size()
        << ",\"max_bits_per_idr\":" << maximum_bits_per_idr
        << ",\"idr_segments\":" << analysis.size()
        << ",\"raw_candidate_signs\":" << raw_candidates
        << ",\"candidate_capacity_bits\":" << capacity_bits
        << ",\"segments\":[";
    for (std::size_t s = 0; s < analysis.size(); ++s) {
        const auto& segment = analysis[s];
        const auto rbsp = units.at(segment.idr_nal_index).rbsp();
        if (s) out << ',';
        out << "{\"segment\":" << s
            << ",\"idr_nal_index\":" << segment.idr_nal_index
            << ",\"analysis_nal_index\":" << segment.analysis_nal_index
            << ",\"candidate_count\":" << segment.candidates.size()
            << ",\"capacity\":" << std::min(maximum_bits_per_idr, segment.candidates.size())
            << ",\"candidates\":[";
        for (std::size_t i = 0; i < segment.candidates.size(); ++i) {
            const auto& c = segment.candidates[i];
            if (i) out << ',';
            out << "{\"id\":\"" << zkstego::serialize_cavlc_sign_candidate(c)
                << "\",\"nal_index\":" << segment.idr_nal_index
                << ",\"rbsp_bit_offset\":" << c.rbsp_bit_offset
                << ",\"bit\":" << +rbsp_bit(rbsp, c.rbsp_bit_offset);
            tier_fields(c);
            out << '}';
        }
        out << "]}";
    }
    out << "]}\n";
    return emit();
}

int run(const std::vector<std::string>& argv) {
    const auto argc = argv.size();
    if (argc == 2) return trace(argv[1]);
    if (argc == 3 && argv[2] == "--summary") return summary(argv[1]);
    if (argc == 4 && argv[2] == "--segments") {
        const auto maximum_bits = parse_index(argv[3], std::numeric_limits<std::size_t>::max());
        if (maximum_bits == 0U) throw std::invalid_argument("max-bits-per-IDR must be positive");
        return segments(argv[1], static_cast<std::size_t>(maximum_bits));
    }
    if (argc == 5 && argv[2] == "--macroblock") {
        const auto nal = parse_index(argv[3], std::numeric_limits<std::size_t>::max());
        const auto address = parse_index(argv[4], std::numeric_limits<std::uint32_t>::max());
        return trace_macroblock(argv[1], static_cast<std::size_t>(nal), static_cast<std::uint32_t>(address));
    }
    throw std::invalid_argument(kUsage);
}

}  // namespace

// Windows uses wide arguments so Unicode paths (the repository and videos may
// have non-ASCII names) survive; cli_io converts them to UTF-8.
#ifdef _WIN32
int wmain(int argc, wchar_t* argv[]) {
#else
int main(int argc, char* argv[]) {
#endif
    try {
        return run(zkstego::cli::utf8_arguments(argc, argv));
    } catch (const std::exception& error) {
        std::cerr << "inspect: " << error.what() << '\n';
        return 2;
    }
}
