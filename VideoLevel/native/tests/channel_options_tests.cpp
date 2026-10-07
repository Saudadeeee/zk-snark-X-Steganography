// CTest cases for the optional channel parameters: selection policy
// (random | low-drift) and key mode (master | per-video, verification token).
// Each case is one CTest entry: zkstego_channel_options_tests <case-name>.
// A failing CHECK returns its line number as the exit code.
#include "zkstego/cavlc_stream.hpp"

#include <algorithm>
#include <array>
#include <cstdint>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <iterator>
#include <map>
#include <numeric>
#include <stdexcept>
#include <string>
#include <string_view>
#include <vector>

#define CHECK(condition) do { if (!(condition)) { std::cerr << "CHECK failed at line " << __LINE__ << ": " #condition "\n"; return __LINE__; } } while (false)

namespace {

using Bytes = std::vector<std::uint8_t>;
using zkstego::CavlcChannelOptions;
using zkstego::CavlcKeyMode;
using zkstego::CavlcResidualCategory;
using zkstego::CavlcSelectionPolicy;

constexpr std::size_t kBitsPerIdr = 64U;
constexpr std::size_t kMaximumPayload = 512U;
constexpr CavlcChannelOptions kLowDriftPerVideo{CavlcSelectionPolicy::LowDrift, CavlcKeyMode::PerVideo};
constexpr CavlcChannelOptions kRandomPerVideo{CavlcSelectionPolicy::Random, CavlcKeyMode::PerVideo};
constexpr CavlcChannelOptions kLowDriftMaster{CavlcSelectionPolicy::LowDrift, CavlcKeyMode::Master};

Bytes read_fixture(const std::string_view name) {
    const std::string path = std::string{ZKSTEGO_PROJECT_SOURCE_DIR} + "/data/encoded/" + std::string(name);
    std::ifstream input(std::filesystem::path(std::u8string(
        reinterpret_cast<const char8_t*>(path.data()), path.size())), std::ios::binary);
    if (!input) throw std::runtime_error("fixture not found: " + path);
    return {std::istreambuf_iterator<char>(input), std::istreambuf_iterator<char>()};
}

// Video A: 50-frame all-IDR CIF (QP 22). Video B: 300-frame all-IDR CIF (QP 18).
const Bytes& video_a() {
    static const Bytes bytes = read_fixture("foreman_cif_q22_g1.h264");
    return bytes;
}

const Bytes& video_b() {
    static const Bytes bytes = read_fixture("foreman_cif_q18_g1_300f.h264");
    return bytes;
}

Bytes master_key() {
    Bytes key(32U);
    std::iota(key.begin(), key.end(), static_cast<std::uint8_t>(0U));
    return key;
}

Bytes payload() {
    Bytes bytes(40U);
    for (std::size_t index = 0; index < bytes.size(); ++index) {
        bytes[index] = static_cast<std::uint8_t>((index * 29U + 7U) & 0xffU);
    }
    return bytes;
}

template <class Operation>
bool throws_invalid_argument(Operation&& operation) {
    try {
        operation();
    } catch (const std::invalid_argument&) {
        return true;
    }
    return false;
}

// True when extraction fails or yields anything but the payload.
template <class Operation>
bool misses_payload(Operation&& operation, const Bytes& expected) {
    try {
        return operation() != expected;
    } catch (const std::invalid_argument&) {
        return true;
    }
}

std::vector<std::string> identities(const std::vector<zkstego::CavlcSignCandidate>& candidates) {
    std::vector<std::string> output;
    output.reserve(candidates.size());
    for (const auto& candidate : candidates) output.push_back(zkstego::serialize_cavlc_sign_candidate(candidate));
    return output;
}

zkstego::CavlcSignCandidate synthetic(const std::uint32_t address, const CavlcResidualCategory category,
                                      const std::uint8_t block, const std::uint32_t row,
                                      const std::uint32_t height, const std::uint8_t frequency) {
    zkstego::CavlcSignCandidate candidate{7U, address, category, block, 100U + address * 16U + block};
    candidate.mb_row = row;
    candidate.mb_height = height;
    candidate.frequency = frequency;
    return candidate;
}

int low_drift_order_follows_tiers() {
    // Tier formula on hand-built candidates (picture height 18 MB rows).
    CHECK(zkstego::cavlc_candidate_tier(synthetic(0, CavlcResidualCategory::LumaDc, 0, 0, 18, 6)) == 4U);
    CHECK(zkstego::cavlc_candidate_tier(synthetic(1, CavlcResidualCategory::ChromaDc, 1, 17, 18, 2)) == 2U);
    CHECK(zkstego::cavlc_candidate_tier(synthetic(2, CavlcResidualCategory::Luma4x4, 3, 5, 18, 0)) == 3U);
    CHECK(zkstego::cavlc_candidate_tier(synthetic(3, CavlcResidualCategory::Luma4x4, 3, 6, 18, 2)) == 2U);
    CHECK(zkstego::cavlc_candidate_tier(synthetic(4, CavlcResidualCategory::ChromaAc, 0, 11, 18, 3)) == 1U);
    CHECK(zkstego::cavlc_candidate_tier(synthetic(5, CavlcResidualCategory::ChromaAc, 0, 12, 18, 6)) == 0U);
    CHECK(zkstego::parse_cavlc_selection_policy("low-drift") == CavlcSelectionPolicy::LowDrift);
    CHECK(throws_invalid_argument([] { static_cast<void>(zkstego::parse_cavlc_selection_policy("lowdrift")); }));
    CHECK(throws_invalid_argument([] { static_cast<void>(zkstego::parse_cavlc_key_mode("video")); }));

    const auto key = master_key();
    const auto segments = zkstego::analyze_cavlc_stream_file(video_a());
    CHECK(segments.size() >= 4U);
    bool differs_from_random = false;
    std::array<std::size_t, 6> tier_histogram{};
    for (std::size_t index = 0; index < 4U; ++index) {
        const auto& candidates = segments[index].candidates;
        CHECK(candidates.size() > kBitsPerIdr);
        for (const auto& candidate : candidates) {
            // Tier inputs come from the slice: CIF is 22 x 18 macroblocks.
            CHECK(candidate.mb_height == 18U);
            CHECK(candidate.mb_row == candidate.macroblock_address / 22U);
            CHECK(candidate.frequency <= 6U);
            ++tier_histogram.at(zkstego::cavlc_candidate_tier(candidate));
        }
        const auto low_drift = zkstego::select_keyed_cavlc_sign_candidates(
            candidates, key, kBitsPerIdr, CavlcSelectionPolicy::LowDrift);
        const auto random = zkstego::select_keyed_cavlc_sign_candidates(candidates, key, kBitsPerIdr);
        CHECK(identities(random) == identities(zkstego::select_keyed_cavlc_sign_candidates(
            candidates, key, kBitsPerIdr, CavlcSelectionPolicy::Random)));
        // Selected tiers never decrease, and no unselected candidate has a
        // lower tier than the highest selected one.
        std::uint8_t highest_selected = 0U;
        for (std::size_t position = 0; position < low_drift.size(); ++position) {
            const auto tier = zkstego::cavlc_candidate_tier(low_drift[position]);
            CHECK(position == 0U || tier >= zkstego::cavlc_candidate_tier(low_drift[position - 1U]));
            highest_selected = std::max(highest_selected, tier);
            // Within one tier the keyed score orders the candidates.
            if (position > 0U && tier == zkstego::cavlc_candidate_tier(low_drift[position - 1U])) {
                CHECK(zkstego::score_keyed_cavlc_sign_candidate(low_drift[position - 1U], key) <
                      zkstego::score_keyed_cavlc_sign_candidate(low_drift[position], key));
            }
        }
        for (const auto& candidate : candidates) {
            const auto selected = std::any_of(low_drift.begin(), low_drift.end(), [&](const auto& item) {
                return item.rbsp_bit_offset == candidate.rbsp_bit_offset;
            });
            if (!selected) CHECK(zkstego::cavlc_candidate_tier(candidate) >= highest_selected);
        }
        const auto same_set = std::all_of(low_drift.begin(), low_drift.end(), [&](const auto& item) {
            return std::any_of(random.begin(), random.end(), [&](const auto& other) {
                return other.rbsp_bit_offset == item.rbsp_bit_offset;
            });
        });
        differs_from_random = differs_from_random || !same_set;
    }
    CHECK(differs_from_random);
    CHECK(tier_histogram[0] > 0U && tier_histogram[5] == 0U);

    // End to end on a file: low-drift embeds only where low-drift extracts,
    // and the tier inputs of every candidate survive embedding.
    const auto message = payload();
    const auto stego = zkstego::embed_cavlc_stream_file(video_a(), key, message, kBitsPerIdr, kLowDriftMaster);
    CHECK(zkstego::extract_cavlc_stream_file(stego, key, kMaximumPayload, kBitsPerIdr, kLowDriftMaster) == message);
    CHECK(misses_payload([&] {
        return zkstego::extract_cavlc_stream_file(stego, key, kMaximumPayload, kBitsPerIdr);
    }, message));
    const auto stego_segments = zkstego::analyze_cavlc_stream_file(stego);
    CHECK(stego_segments.size() == segments.size());
    for (std::size_t index = 0; index < segments.size(); ++index) {
        CHECK(stego_segments[index].candidates.size() == segments[index].candidates.size());
        for (std::size_t item = 0; item < segments[index].candidates.size(); ++item) {
            const auto& before = segments[index].candidates[item];
            const auto& after = stego_segments[index].candidates[item];
            CHECK(before.mb_row == after.mb_row && before.mb_height == after.mb_height);
            CHECK(before.frequency == after.frequency);
        }
    }
    // Every changed sign sits on a low-drift-scheduled position.
    const auto cover_units = zkstego::split_annex_b(video_a());
    const auto stego_units = zkstego::split_annex_b(stego);
    std::size_t changed = 0;
    for (const auto& segment : segments) {
        const auto scheduled = zkstego::select_keyed_cavlc_sign_candidates(
            segment.candidates, key, std::min(kBitsPerIdr, segment.candidates.size()), CavlcSelectionPolicy::LowDrift);
        const auto before = cover_units.at(segment.idr_nal_index).rbsp();
        const auto after = stego_units.at(segment.idr_nal_index).rbsp();
        for (const auto& candidate : segment.candidates) {
            const auto bit = candidate.rbsp_bit_offset;
            if (((before.at(bit / 8U) ^ after.at(bit / 8U)) & (0x80U >> (bit % 8U))) == 0U) continue;
            ++changed;
            CHECK(std::any_of(scheduled.begin(), scheduled.end(), [&](const auto& item) {
                return item.rbsp_bit_offset == bit;
            }));
        }
    }
    CHECK(changed > 0U && changed <= (3U + message.size()) * 8U);
    return 0;
}

int defaults_are_protocol_v3() {
    // Explicit random/master options are the v3 defaults, byte for byte.
    const auto key = master_key();
    const auto message = payload();
    const CavlcChannelOptions explicit_defaults{CavlcSelectionPolicy::Random, CavlcKeyMode::Master};
    const auto stego = zkstego::embed_cavlc_stream_file(video_a(), key, message, kBitsPerIdr);
    CHECK(zkstego::embed_cavlc_stream_file(video_a(), key, message, kBitsPerIdr, explicit_defaults) == stego);
    const auto frame_bits = (3U + message.size()) * 8U;
    CHECK(zkstego::cavlc_video_binding_digest(video_a(), key, frame_bits, kBitsPerIdr).digest ==
          zkstego::cavlc_video_binding_digest(video_a(), key, frame_bits, kBitsPerIdr, explicit_defaults).digest);
    // Each non-default parameter writes a different stego file.
    CHECK(zkstego::embed_cavlc_stream_file(video_a(), key, message, kBitsPerIdr, kLowDriftMaster) != stego);
    CHECK(zkstego::embed_cavlc_stream_file(video_a(), key, message, kBitsPerIdr, kRandomPerVideo) != stego);
    return 0;
}

int per_video_nonce_cover_equals_stego() {
    const auto key = master_key();
    const auto message = payload();
    const auto cover_nonce = zkstego::cavlc_video_nonce(video_a());
    const auto first_idr = zkstego::analyze_cavlc_stream_file(video_a()).front().idr_nal_index;
    for (const auto& options : {kRandomPerVideo, kLowDriftPerVideo}) {
        const auto stego = zkstego::embed_cavlc_stream_file(video_a(), key, message, kBitsPerIdr, options);
        CHECK(stego != video_a());
        // The first IDR carries frame bits, yet its nonce is unchanged: every
        // candidate sign is cleared before hashing.
        CHECK(zkstego::split_annex_b(stego).at(first_idr).rbsp() !=
              zkstego::split_annex_b(video_a()).at(first_idr).rbsp());
        CHECK(zkstego::cavlc_video_nonce(stego) == cover_nonce);
        CHECK(zkstego::cavlc_verification_token(stego, key) == zkstego::cavlc_verification_token(video_a(), key));
        CHECK(zkstego::extract_cavlc_stream_file(stego, key, kMaximumPayload, kBitsPerIdr, options) == message);
        // Master-mode subkeys do not read a per-video embedding.
        CHECK(misses_payload([&] {
            return zkstego::extract_cavlc_stream_file(
                stego, key, kMaximumPayload, kBitsPerIdr, {options.selection, CavlcKeyMode::Master});
        }, message));
    }
    // Another video, another nonce and token; the nonce does not depend on K.
    CHECK(zkstego::cavlc_video_nonce(video_b()) != cover_nonce);
    auto other_key = key;
    other_key[0] ^= 0x80U;
    const auto token = zkstego::cavlc_verification_token(video_a(), key);
    CHECK(token.size() == zkstego::kCavlcVerificationTokenBytes);
    CHECK(zkstego::cavlc_verification_token_for_nonce(key, cover_nonce) == token);
    CHECK(zkstego::cavlc_verification_token(video_a(), other_key) != token);
    CHECK(zkstego::cavlc_verification_token(video_b(), key) != token);
    CHECK(throws_invalid_argument([&] {
        static_cast<void>(zkstego::cavlc_verification_token(video_a(), token));
    }));
    return 0;
}

int token_extract_equals_master() {
    const auto key = master_key();
    const auto message = payload();
    const auto stego = zkstego::embed_cavlc_stream_file(video_a(), key, message, kBitsPerIdr, kLowDriftPerVideo);
    const auto token = zkstego::cavlc_verification_token(stego, key);
    const auto with_key = zkstego::extract_cavlc_stream_file(stego, key, kMaximumPayload, kBitsPerIdr, kLowDriftPerVideo);
    const auto with_token = zkstego::extract_cavlc_stream_file(stego, token, kMaximumPayload, kBitsPerIdr, kLowDriftPerVideo);
    CHECK(with_key == message);
    CHECK(with_token == with_key);
    // The token holds exactly the per-video subkeys: embedding with it writes
    // the same file as embedding with K.
    CHECK(zkstego::embed_cavlc_stream_file(video_a(), token, message, kBitsPerIdr, kLowDriftPerVideo) == stego);
    // A token is refused in master mode, and a malformed secret everywhere.
    CHECK(throws_invalid_argument([&] {
        static_cast<void>(zkstego::extract_cavlc_stream_file(stego, token, kMaximumPayload, kBitsPerIdr, kLowDriftMaster));
    }));
    CHECK(throws_invalid_argument([&] {
        static_cast<void>(zkstego::extract_cavlc_stream_file(
            stego, Bytes(48U, 0x11U), kMaximumPayload, kBitsPerIdr, kLowDriftPerVideo));
    }));
    // The incremental decoder (live path) agrees with the file path.
    zkstego::CavlcStreamDecoder decoder(token, kMaximumPayload, kBitsPerIdr, kLowDriftPerVideo);
    std::vector<zkstego::AnnexBNalUnit> context;
    for (const auto& unit : zkstego::split_annex_b(stego)) {
        if (unit.nal_unit_type == 7U || unit.nal_unit_type == 8U) {
            zkstego::update_parameter_set_context(context, unit);
        } else if (unit.is_idr()) {
            decoder.consume_segment(zkstego::assemble_cavlc_stream_segment(context, unit));
            if (decoder.complete()) break;
        }
    }
    CHECK(decoder.complete() && decoder.payload() == message);
    return 0;
}

int token_of_other_video_fails() {
    const auto key = master_key();
    const auto message = payload();
    const auto stego_a = zkstego::embed_cavlc_stream_file(video_a(), key, message, kBitsPerIdr, kLowDriftPerVideo);
    const auto stego_b = zkstego::embed_cavlc_stream_file(video_b(), key, message, kBitsPerIdr, kLowDriftPerVideo);
    const auto token_a = zkstego::cavlc_verification_token(video_a(), key);
    const auto token_b = zkstego::cavlc_verification_token(video_b(), key);
    CHECK(token_a != token_b);
    CHECK(zkstego::extract_cavlc_stream_file(stego_a, token_a, kMaximumPayload, kBitsPerIdr, kLowDriftPerVideo) == message);
    CHECK(zkstego::extract_cavlc_stream_file(stego_b, token_b, kMaximumPayload, kBitsPerIdr, kLowDriftPerVideo) == message);
    CHECK(misses_payload([&] {
        return zkstego::extract_cavlc_stream_file(stego_b, token_a, kMaximumPayload, kBitsPerIdr, kLowDriftPerVideo);
    }, message));
    CHECK(misses_payload([&] {
        return zkstego::extract_cavlc_stream_file(stego_a, token_b, kMaximumPayload, kBitsPerIdr, kLowDriftPerVideo);
    }, message));
    // Its digest of video B is not video B's digest either.
    const auto frame_bits = (3U + message.size()) * 8U;
    CHECK(zkstego::cavlc_video_binding_digest(stego_b, token_a, frame_bits, kBitsPerIdr, kLowDriftPerVideo).digest !=
          zkstego::cavlc_video_binding_digest(stego_b, token_b, frame_bits, kBitsPerIdr, kLowDriftPerVideo).digest);
    return 0;
}

int token_digest_equals_master_digest() {
    const auto key = master_key();
    const auto message = payload();
    const auto frame_bits = (3U + message.size()) * 8U;
    for (const auto& options : {kRandomPerVideo, kLowDriftPerVideo}) {
        const auto stego = zkstego::embed_cavlc_stream_file(video_a(), key, message, kBitsPerIdr, options);
        const auto token = zkstego::cavlc_verification_token(video_a(), key);
        const auto with_key = zkstego::cavlc_video_binding_digest(video_a(), key, frame_bits, kBitsPerIdr, options);
        const auto with_token = zkstego::cavlc_video_binding_digest(video_a(), token, frame_bits, kBitsPerIdr, options);
        CHECK(with_token.digest == with_key.digest);
        CHECK(with_token.carrier_segments == with_key.carrier_segments && with_key.carrier_segments > 1U);
        // Cover and stego share the digest under the token too.
        CHECK(zkstego::cavlc_video_binding_digest(stego, token, frame_bits, kBitsPerIdr, options).digest == with_key.digest);
        // The carriers depend on the parameters: master mode marks other bits.
        CHECK(zkstego::cavlc_video_binding_digest(
            video_a(), key, frame_bits, kBitsPerIdr, {options.selection, CavlcKeyMode::Master}).digest != with_key.digest);
        CHECK(throws_invalid_argument([&] {
            static_cast<void>(zkstego::cavlc_video_binding_digest(
                video_a(), token, frame_bits, kBitsPerIdr, {options.selection, CavlcKeyMode::Master}));
        }));
    }
    return 0;
}

}  // namespace

int main(const int argc, char* argv[]) {
    const std::map<std::string, int (*)()> cases{
        {"low_drift_order_follows_tiers", low_drift_order_follows_tiers},
        {"defaults_are_protocol_v3", defaults_are_protocol_v3},
        {"per_video_nonce_cover_equals_stego", per_video_nonce_cover_equals_stego},
        {"token_extract_equals_master", token_extract_equals_master},
        {"token_of_other_video_fails", token_of_other_video_fails},
        {"token_digest_equals_master_digest", token_digest_equals_master_digest},
    };
    if (argc != 2 || cases.find(argv[1]) == cases.end()) {
        std::cerr << "usage: zkstego_channel_options_tests <case>\n";
        for (const auto& [name, _] : cases) std::cerr << "  " << name << '\n';
        return 2;
    }
    try {
        const auto line = cases.at(argv[1])();
        if (line != 0) std::cerr << argv[1] << " failed at line " << line << '\n';
        return line == 0 ? 0 : 1;
    } catch (const std::exception& error) {
        std::cerr << argv[1] << " threw: " << error.what() << '\n';
        return 1;
    }
}
