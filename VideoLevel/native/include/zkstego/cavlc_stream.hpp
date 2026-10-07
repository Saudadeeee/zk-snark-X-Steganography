#pragma once

#include <cstddef>
#include <cstdint>
#include <array>
#include <istream>
#include <optional>
#include <string>
#include <stdexcept>
#include <utility>
#include <vector>

namespace zkstego {

// Resource bounds shared by the library and CLI tools.
//
// kMaxPictureMacroblocks is the H.264 Table A-1 MaxFS of levels 5.1/5.2
// (36864 macroblocks, e.g. 4096x2304), which covers 3840x2160 UHD. Each
// decoded I macroblock retains several kilobytes of residual state, so this
// bounds worst-case decoder memory per slice to a few hundred MiB instead of
// letting a hostile SPS scale it with the RBSP size. kMaxPictureDimensionMbs
// is the matching A.3.1 bound floor(sqrt(8 * MaxFS)) on either dimension.
inline constexpr std::size_t kMaxPictureMacroblocks = 36864U;
inline constexpr std::size_t kMaxPictureDimensionMbs = 543U;
// Whole-file inputs read by the CLI tools are loaded into memory; 1 GiB is far
// above the 300..3000-frame CIF fixtures while refusing unbounded allocation.
inline constexpr std::size_t kMaxAnnexBFileBytes = 1024U * 1024U * 1024U;

// Non-owning MSB-first bit reader over an RBSP byte range. Constructing from
// an lvalue vector stores only a view, so the vector must outlive the reader;
// constructing from an rvalue vector (including a braced list) moves the
// bytes into the reader so a temporary can never dangle. The reader is
// neither copyable nor movable because the view may point into its own
// storage.
class RbspBitReader {
public:
    explicit RbspBitReader(const std::vector<std::uint8_t>& bytes) noexcept
        : data_(bytes.data()), size_(bytes.size()) {}
    explicit RbspBitReader(std::vector<std::uint8_t>&& bytes)
        : owned_(std::move(bytes)), data_(owned_.data()), size_(owned_.size()) {}
    RbspBitReader(const std::uint8_t* data, std::size_t size) noexcept : data_(data), size_(size) {}
    RbspBitReader(const RbspBitReader&) = delete;
    RbspBitReader& operator=(const RbspBitReader&) = delete;
    RbspBitReader(RbspBitReader&&) = delete;
    RbspBitReader& operator=(RbspBitReader&&) = delete;
    ~RbspBitReader() = default;

    [[nodiscard]] std::size_t position() const noexcept { return position_; }
    [[nodiscard]] std::size_t remaining_bits() const noexcept { return size_ * 8 - position_; }
    void skip_bits(std::size_t count) {
        if (count > remaining_bits()) throw std::out_of_range("RBSP bit skip past end");
        position_ += count;
    }
    [[nodiscard]] std::uint8_t read_bit() {
        if (position_ >= size_ * 8) throw std::out_of_range("RBSP bit read past end");
        const auto bit = static_cast<std::uint8_t>((data_[position_ / 8] >> (7 - position_ % 8)) & 1U);
        ++position_;
        return bit;
    }
    [[nodiscard]] std::uint32_t read_bits(std::size_t count) {
        if (count > 32) throw std::invalid_argument("RBSP read_bits count exceeds 32");
        std::uint32_t value = 0;
        for (std::size_t i = 0; i < count; ++i) value = (value << 1U) | read_bit();
        return value;
    }
    [[nodiscard]] std::uint32_t read_ue() {
        std::size_t zeros = 0;
        while (read_bit() == 0) { if (++zeros > 31) throw std::invalid_argument("invalid RBSP ue(v)"); }
        return zeros == 0 ? 0 : ((1U << zeros) - 1U + read_bits(zeros));
    }
    [[nodiscard]] std::int32_t read_se() {
        const auto code_num = read_ue();
        if ((code_num & 1U) != 0U) {
            return static_cast<std::int32_t>((code_num + 1U) / 2U);
        }
        return -static_cast<std::int32_t>(code_num / 2U);
    }
private:
    std::vector<std::uint8_t> owned_;
    const std::uint8_t* data_{};
    std::size_t size_{};
    std::size_t position_{};
};

struct FixedLengthBitPatch {
    std::size_t bit_offset;
    std::vector<std::uint8_t> bits;
};

struct AnnexBRbspPatchPlan {
    std::size_t nal_index;
    std::vector<FixedLengthBitPatch> patches;
};

struct H264BaselineSps {
    std::uint8_t profile_idc{};
    std::uint8_t level_idc{};
    std::uint32_t sequence_parameter_set_id{};
    std::uint32_t log2_max_frame_num_minus4{};
    std::uint32_t pic_order_cnt_type{};
    std::uint32_t log2_max_pic_order_cnt_lsb_minus4{};
    bool frame_mbs_only_flag{};
    std::uint32_t pic_width_in_mbs_minus1{};
    std::uint32_t pic_height_in_map_units_minus1{};
};

// Throws std::invalid_argument unless the SPS picture size is within
// kMaxPictureDimensionMbs / kMaxPictureMacroblocks. Returns the macroblock
// count of one frame.
std::size_t validated_picture_macroblock_count(const H264BaselineSps& sps);

struct H264BaselinePps {
    std::uint32_t pic_parameter_set_id{};
    std::uint32_t sequence_parameter_set_id{};
    bool entropy_coding_mode_flag{};
    std::uint32_t num_slice_groups_minus1{};
    std::uint32_t num_ref_idx_l0_default_active_minus1{};
    std::uint32_t num_ref_idx_l1_default_active_minus1{};
    bool bottom_field_pic_order_in_frame_present_flag{};
    std::int32_t pic_init_qp_minus26{};
    bool deblocking_filter_control_present_flag{};
    bool redundant_pic_cnt_present_flag{};
};

struct H264BaselineIdrSliceHeader {
    std::uint32_t first_mb_in_slice{};
    std::uint32_t slice_type{};
    std::uint32_t pic_parameter_set_id{};
    std::uint32_t frame_num{};
    std::uint32_t idr_pic_id{};
    std::uint32_t pic_order_cnt_lsb{};
    std::int32_t delta_pic_order_cnt_bottom{};
    std::int32_t slice_qp_delta{};
    std::size_t data_bit_offset{};
};

struct CavlcCoeffToken {
    std::uint32_t total_coefficients{};
    std::uint32_t trailing_ones{};
    std::vector<std::size_t> sign_bit_offsets;
    std::size_t level_bit_offset{};
    // Diagnostics only: RBSP bit where coeff_token starts and the nC context
    // used to choose its VLC table. They do not affect parsing or embedding.
    std::size_t start_bit_offset{};
    int n_c{};
};

struct CavlcDecodedLevels {
    // CAVLC signals trailing-one signs before the remaining levels, in reverse scan order.
    std::vector<std::int32_t> trailing_one_values;
    std::vector<std::int32_t> values;
    std::size_t next_bit_offset{};
};

struct CavlcResidualTail {
    std::uint32_t total_zeros{};
    std::vector<std::uint32_t> runs;
    std::size_t next_bit_offset{};
};

struct CavlcDecodedLumaBlock {
    CavlcCoeffToken token;
    CavlcDecodedLevels levels;
    CavlcResidualTail tail;
    std::vector<std::int32_t> coefficients;
};

struct CavlcDecodedLumaMacroblock {
    std::array<CavlcDecodedLumaBlock, 16> blocks;
    std::size_t next_bit_offset{};
};

struct CavlcLumaNeighbourCounts {
    // Valid only for the locked progressive, single-slice raster profile.
    // Callers must derive availability from the slice, not merely from frame
    // position; FMO and MBAFF are intentionally outside this primitive.
    bool left_available{};
    bool top_available{};
    // TotalCoeff values at the left MB's x=3 edge and top MB's y=3 edge,
    // indexed by luma 4x4 raster coordinate. Values must be in [0, 16].
    std::array<std::uint32_t, 4> left{};
    std::array<std::uint32_t, 4> top{};
};

struct H264BaselineIMacroblockHeader {
    std::uint32_t mb_type{};
    std::uint32_t coded_block_pattern{};
    std::int32_t mb_qp_delta{};
    std::array<std::int8_t, 16> intra_4x4_prediction_modes{};
    std::size_t residual_bit_offset{};
};

struct CavlcDecodedIMacroblock {
    std::uint32_t address{};
    H264BaselineIMacroblockHeader header;
    // Parsed only for I16x16. Its nC context follows the normal luma
    // block-zero neighbour mapping used by CAVLC decoders.
    CavlcDecodedLumaBlock luma_dc;
    CavlcDecodedLumaMacroblock luma;
    std::array<CavlcDecodedLumaBlock, 2> chroma_dc;
    std::array<CavlcDecodedLumaBlock, 8> chroma_ac;
    std::size_t next_bit_offset{};
};

struct CavlcDecodedIdrSlice {
    std::size_t nal_index{};
    H264BaselineSps sps;
    H264BaselinePps pps;
    H264BaselineIdrSliceHeader header;
    std::vector<CavlcDecodedIMacroblock> macroblocks;
    std::size_t rbsp_trailing_bit_offset{};
};

enum class CavlcResidualCategory : std::uint8_t {
    LumaDc,
    Luma4x4,
    ChromaDc,
    ChromaAc,
};

// A trailing-one sign bit is a bit-exact, length-invariant CAVLC candidate:
// flipping it changes only coefficient sign, never coeff_token or residual
// block length. One candidate is emitted per residual block.
//
// The first five fields are the candidate identity (serialized and scored by
// the keyed schedule). The trailing fields are low-drift tier inputs derived
// only from syntax a sign flip never changes; they are not part of the
// identity and default to zero for candidates built by hand.
struct CavlcSignCandidate {
    std::size_t nal_index{};
    std::uint32_t macroblock_address{};
    CavlcResidualCategory category{};
    std::uint8_t block_index{};
    std::size_t rbsp_bit_offset{};
    std::uint32_t mb_row{};      // macroblock_address / PicWidthInMbs
    std::uint32_t mb_height{};   // PicHeightInMbs of the slice's SPS
    // i + j of the raster position (i, j) of the coefficient whose sign this
    // is: the last non-zero coefficient in scan order (4x4 zig-zag; AC-only
    // blocks start at zig-zag index 1; ChromaDC uses its 2x2 raster order).
    std::uint8_t frequency{};
};

// Channel parameters carried out of band, like the per-IDR cap. The defaults
// are protocol v3 exactly.
//   selection: random    = rank by (HMAC score, identity)
//              low-drift = rank by (tier, HMAC score, identity), tier below
//   key_mode:  master    = v3 subkeys from the 32-byte stego key K
//              per-video = v4 subkeys bound to the video nonce (see below)
enum class CavlcSelectionPolicy : std::uint8_t { Random = 0, LowDrift = 1 };
enum class CavlcKeyMode : std::uint8_t { Master = 0, PerVideo = 1 };
struct CavlcChannelOptions {
    CavlcSelectionPolicy selection{CavlcSelectionPolicy::Random};
    CavlcKeyMode key_mode{CavlcKeyMode::Master};
};
// "random" | "low-drift" and "master" | "per-video"; anything else throws.
CavlcSelectionPolicy parse_cavlc_selection_policy(const std::string& text);
CavlcKeyMode parse_cavlc_key_mode(const std::string& text);

// Low-drift tier = r + d + f in [0, 5] (lower is selected first):
//   r = 2 if mb_row * 3 < mb_height, 1 if mb_row * 3 < 2 * mb_height, else 0
//   d = 2 for LumaDC / ChromaDC, else 0
//   f = 1 for Luma4x4 (incl. I16x16 AC) / ChromaAC with frequency <= 2, else 0
std::uint8_t cavlc_candidate_tier(const CavlcSignCandidate& candidate);

struct H264BaselineIdrNalHeader {
    std::size_t nal_index{};
    H264BaselineIdrSliceHeader slice_header;
    H264BaselineIMacroblockHeader first_macroblock;
    CavlcDecodedLumaBlock first_luma_block;
};

struct AnnexBNalUnit {
    std::size_t start_offset{};
    std::size_t start_code_size{};
    std::uint8_t forbidden_zero_bit{};
    std::uint8_t nal_ref_idc{};
    std::uint8_t nal_unit_type{};
    std::vector<std::uint8_t> payload;

    [[nodiscard]] bool is_idr() const noexcept { return nal_unit_type == 5; }
    [[nodiscard]] std::vector<std::uint8_t> rbsp() const;
};

std::vector<std::uint8_t> ebsp_to_rbsp(const std::vector<std::uint8_t>& ebsp);
std::vector<std::uint8_t> rbsp_to_ebsp(const std::vector<std::uint8_t>& rbsp);
H264BaselineSps parse_baseline_sps(const std::vector<std::uint8_t>& rbsp);
H264BaselinePps parse_baseline_pps(const std::vector<std::uint8_t>& rbsp);
H264BaselineIdrSliceHeader parse_baseline_idr_slice_header(
    const std::vector<std::uint8_t>& rbsp,
    const H264BaselineSps& sps,
    const H264BaselinePps& pps);
CavlcCoeffToken parse_cavlc_coeff_token(
    const std::vector<std::uint8_t>& rbsp,
    std::size_t start_bit,
    int n_c);
CavlcDecodedLevels decode_cavlc_non_trailing_levels(
    const std::vector<std::uint8_t>& rbsp,
    const CavlcCoeffToken& token);
std::vector<std::int32_t> reconstruct_cavlc_block(
    const CavlcDecodedLevels& decoded_levels,
    const std::vector<std::uint32_t>& runs,
    std::size_t max_num_coefficients);
CavlcResidualTail decode_cavlc_tail_tc4(
    const std::vector<std::uint8_t>& rbsp,
    std::size_t start_bit);
CavlcResidualTail decode_cavlc_residual_tail(
    const std::vector<std::uint8_t>& rbsp,
    std::size_t start_bit,
    std::uint32_t total_coefficients,
    std::size_t max_num_coefficients);
CavlcResidualTail decode_cavlc_luma_residual_tail(
    const std::vector<std::uint8_t>& rbsp,
    std::size_t start_bit,
    std::uint32_t total_coefficients);
CavlcResidualTail decode_cavlc_chroma_dc_residual_tail(
    const std::vector<std::uint8_t>& rbsp,
    std::size_t start_bit,
    std::uint32_t total_coefficients);
CavlcDecodedLumaBlock decode_cavlc_luma_block(
    const std::vector<std::uint8_t>& rbsp,
    std::size_t start_bit,
    int n_c);
CavlcDecodedLumaBlock decode_cavlc_luma_ac_block(
    const std::vector<std::uint8_t>& rbsp,
    std::size_t start_bit,
    int n_c);
CavlcDecodedLumaBlock decode_cavlc_chroma_dc_block(
    const std::vector<std::uint8_t>& rbsp,
    std::size_t start_bit);
CavlcDecodedLumaBlock decode_cavlc_chroma_ac_block(
    const std::vector<std::uint8_t>& rbsp,
    std::size_t start_bit,
    int n_c);
CavlcDecodedLumaMacroblock decode_cavlc_luma_macroblock(
    const std::vector<std::uint8_t>& rbsp,
    std::size_t start_bit,
    std::uint32_t coded_block_pattern_luma);
CavlcDecodedLumaMacroblock decode_cavlc_luma_macroblock(
    const std::vector<std::uint8_t>& rbsp,
    std::size_t start_bit,
    std::uint32_t coded_block_pattern_luma,
    const CavlcLumaNeighbourCounts& neighbours);
CavlcDecodedLumaMacroblock decode_cavlc_luma_ac_macroblock(
    const std::vector<std::uint8_t>& rbsp,
    std::size_t start_bit,
    std::uint32_t coded_block_pattern_luma,
    const CavlcLumaNeighbourCounts& neighbours);
CavlcDecodedIdrSlice decode_baseline_i_idr_slice(
    const std::vector<std::uint8_t>& rbsp,
    const H264BaselineSps& sps,
    const H264BaselinePps& pps);
std::vector<CavlcDecodedIdrSlice> decode_baseline_i_idr_slices(
    const std::vector<std::uint8_t>& annex_b);
std::vector<CavlcSignCandidate> collect_cavlc_trailing_one_sign_candidates(
    const std::vector<CavlcDecodedIdrSlice>& slices);
std::string serialize_cavlc_sign_candidate(const CavlcSignCandidate& candidate);

// Blind channel protocol v3. One 32-byte secret K (the stego key) is never
// used as an HMAC key directly; RFC 5869 HKDF-SHA-256 separates it into
// independent subkeys (labels unchanged from v2):
//   PRK           = HMAC-SHA256(key = "zkstego-cavlc-v2-salt", msg = K)
//   schedule_key  = HKDF-Expand(PRK, "zkstego/cavlc/v2/schedule", 32)
//   whitening_key = HKDF-Expand(PRK, "zkstego/cavlc/v2/whitening", 32)
// Schedule score = HMAC(schedule_key, identity); frame = [0x03][len BE16]
// [payload]. The frame carries no MAC: the channel only hides and locates the
// payload, and the Groth16 proof inside it is what a verifier checks. A wrong
// key still fails cheaply here in almost every case (random version byte or
// length). Embedded bit i (global across every IDR segment of one session) =
// frame bit i XOR keystream bit i, where the keystream is
// HMAC(whitening_key, uint64_be(j)) for j = 0, 1, ... and both bit streams are
// MSB-first. src/native_blind_contract.py is the byte-for-byte Python reference.
inline constexpr std::uint8_t kCavlcFrameVersion = 3U;

// RFC 5869 HKDF with SHA-256 (empty salt means 32 zero bytes). length must
// not exceed 255 * 32 bytes.
std::vector<std::uint8_t> hkdf_sha256(
    const std::vector<std::uint8_t>& salt,
    const std::vector<std::uint8_t>& input_key_material,
    const std::vector<std::uint8_t>& info,
    std::size_t length);
// Whitening keystream bytes [0, byte_count) for a 32-byte secret; bits are
// read MSB-first from these bytes.
std::vector<std::uint8_t> cavlc_whitening_keystream(
    const std::vector<std::uint8_t>& secret_key,
    std::size_t byte_count);

std::array<std::uint8_t, 32> score_keyed_cavlc_sign_candidate(
    const CavlcSignCandidate& candidate,
    const std::vector<std::uint8_t>& secret_key);
// secret_key is the 32-byte master key (v3 schedule subkey).
std::vector<CavlcSignCandidate> select_keyed_cavlc_sign_candidates(
    const std::vector<CavlcSignCandidate>& candidates,
    const std::vector<std::uint8_t>& secret_key,
    std::size_t required_bits,
    CavlcSelectionPolicy policy = CavlcSelectionPolicy::Random);

// Key mode per-video (channel protocol v3 frame, v4 key schedule):
//   video_nonce   = SHA256("zkstego/video-nonce/v1" || for each NAL of the
//                   first stream segment - its stored SPS/PPS context, then
//                   its IDR - : u32be(1 + rbsp_size) || nal_header_byte || rbsp')
//                   where rbsp' is the IDR RBSP with EVERY trailing-one sign
//                   candidate bit cleared (parameter sets are unchanged), so the
//                   nonce is key-independent and equal for cover and stego;
//   PRK           = HKDF-Extract(salt = "zkstego-cavlc-v4-salt", K)
//   video_key     = HKDF-Expand(PRK, "zkstego/cavlc/v4/video" || video_nonce, 32)
//   schedule_key  = HKDF-Expand(video_key, "zkstego/cavlc/v4/schedule", 32)
//   whitening_key = HKDF-Expand(video_key, "zkstego/cavlc/v4/whitening", 32)
// A verification token is schedule_key || whitening_key (64 bytes): it
// extracts from, and computes the video digest of, that one video without K.
// The stream encoder/decoder and the file/digest entry points below that take
// a "secret" accept the 32-byte K, or (per-video only) a 64-byte token; a
// token in master mode is rejected. The low-level keyed selection/scoring
// helpers (select_/score_keyed_cavlc_sign_candidate*) take the 32-byte K only.
inline constexpr std::size_t kCavlcVerificationTokenBytes = 64U;
std::array<std::uint8_t, 32> cavlc_video_nonce(const std::vector<std::uint8_t>& annex_b);
// Token for a known nonce (cross-language vectors) and for a whole file.
// The caller owns and wipes the returned secret.
std::vector<std::uint8_t> cavlc_verification_token_for_nonce(
    const std::vector<std::uint8_t>& master_key,
    const std::array<std::uint8_t, 32>& video_nonce);
std::vector<std::uint8_t> cavlc_verification_token(
    const std::vector<std::uint8_t>& annex_b,
    const std::vector<std::uint8_t>& master_key);
std::vector<std::uint8_t> pack_cavlc_frame(const std::vector<std::uint8_t>& payload);
std::vector<std::uint8_t> unpack_cavlc_frame(
    const std::vector<std::uint8_t>& frame,
    std::size_t maximum_payload_bytes);

struct CavlcStreamSegment {
    std::vector<std::uint8_t> output;
    std::size_t candidate_capacity{};
    std::size_t bits_embedded{};
    bool session_complete{};
};

class CavlcStreamEncoder {
public:
    // secret_key: 32-byte K, or a 64-byte verification token (per-video only).
    CavlcStreamEncoder(
        std::vector<std::uint8_t> secret_key,
        const std::vector<std::uint8_t>& payload,
        std::size_t maximum_bits_per_segment,
        CavlcChannelOptions options = {});
    CavlcStreamEncoder(const CavlcStreamEncoder&) = delete;
    CavlcStreamEncoder& operator=(const CavlcStreamEncoder&) = delete;
    ~CavlcStreamEncoder() noexcept;
    [[nodiscard]] CavlcStreamSegment process_segment(
        const std::vector<std::uint8_t>& annex_b_segment);
    [[nodiscard]] bool complete() const noexcept;
    [[nodiscard]] std::size_t remaining_bits() const noexcept;

private:
    // Only derived subkeys and frame bits are retained; the caller's secret
    // is wiped after HKDF in the constructor. In per-video mode with K, the
    // HKDF-Extract PRK is held until the first segment fixes the video nonce;
    // until then frame_bits_ is plaintext and is whitened in place there.
    CavlcChannelOptions options_;
    std::vector<std::uint8_t> schedule_key_;
    std::vector<std::uint8_t> whitening_key_;
    std::vector<std::uint8_t> pending_prk_;
    std::vector<std::uint8_t> frame_bits_;
    std::vector<AnnexBNalUnit> parameter_sets_;
    std::size_t maximum_bits_per_segment_{};
    std::size_t next_bit_{};
    bool frame_whitened_{};
};

class CavlcStreamDecoder {
public:
    CavlcStreamDecoder(
        std::vector<std::uint8_t> secret_key,
        std::size_t maximum_payload_bytes,
        std::size_t maximum_bits_per_segment,
        CavlcChannelOptions options = {});
    CavlcStreamDecoder(const CavlcStreamDecoder&) = delete;
    CavlcStreamDecoder& operator=(const CavlcStreamDecoder&) = delete;
    ~CavlcStreamDecoder() noexcept;
    void consume_segment(const std::vector<std::uint8_t>& annex_b_segment);
    [[nodiscard]] bool complete() const noexcept { return payload_.has_value(); }
    [[nodiscard]] bool failed() const noexcept { return failed_; }
    [[nodiscard]] std::size_t buffered_bit_count() const noexcept { return collected_bits_.size(); }
    [[nodiscard]] const std::vector<std::uint8_t>& payload() const;

private:
    // Derived subkeys; the caller's secret is wiped after HKDF (per-video
    // with K: the PRK waits for the first segment's nonce).
    // collected_bits_ holds un-whitened frame bits.
    CavlcChannelOptions options_;
    std::vector<std::uint8_t> schedule_key_;
    std::vector<std::uint8_t> whitening_key_;
    std::vector<std::uint8_t> pending_prk_;
    std::vector<AnnexBNalUnit> parameter_sets_;
    std::size_t maximum_payload_bytes_{};
    std::size_t maximum_bits_per_segment_{};
    std::vector<std::uint8_t> collected_bits_;
    std::optional<std::size_t> expected_frame_bits_;
    std::optional<std::vector<std::uint8_t>> payload_;
    bool failed_{};
    std::string failure_reason_;
};

std::vector<std::int32_t> reconstruct_cavlc_tc4_no_trailing(
    const std::vector<std::int32_t>& decoded_non_trailing_levels,
    const std::vector<std::uint32_t>& runs);
H264BaselineIMacroblockHeader parse_baseline_i_macroblock_header(
    const std::vector<std::uint8_t>& rbsp,
    std::size_t start_bit);
std::vector<H264BaselineIdrNalHeader> inspect_baseline_idr_headers(
    const std::vector<std::uint8_t>& annex_b);
std::vector<AnnexBNalUnit> split_annex_b(const std::vector<std::uint8_t>& annex_b);
// Returns seq_parameter_set_id (SPS, type 7) or pic_parameter_set_id (PPS,
// type 8). Throws std::invalid_argument for other NAL types or bad ids.
std::uint32_t parameter_set_id(const AnnexBNalUnit& unit);
// Maintains the single-SPS/single-PPS context prepended to stream segments.
// A repeated parameter set with the same id replaces the stored one; a
// different id of the same type is rejected rather than silently replacing
// the active set, because the blind schedule's NAL indices assume exactly
// one stored SPS and one stored PPS.
void update_parameter_set_context(std::vector<AnnexBNalUnit>& parameter_sets, const AnnexBNalUnit& unit);
std::vector<std::uint8_t> assemble_annex_b(const std::vector<AnnexBNalUnit>& units);

// File-mode segment protocol (the only channel protocol). Every IDR NAL of a
// whole Annex-B file is one stream segment: the SPS/PPS context seen so far in
// the file (update_parameter_set_context) followed by that IDR. The live
// stdin/stdout CLI commands build segments from a pipe with the same helper.
std::vector<std::uint8_t> assemble_cavlc_stream_segment(
    const std::vector<AnnexBNalUnit>& parameter_sets,
    const AnnexBNalUnit& idr);
// Embeds the v3 frame across the file's IDR segments (at most
// maximum_bits_per_segment scheduled signs per IDR). Non-IDR NAL units and
// IDRs after the frame is complete are copied unchanged. Throws when the file
// has no IDR or not enough capacity.
std::vector<std::uint8_t> embed_cavlc_stream_file(
    const std::vector<std::uint8_t>& annex_b,
    const std::vector<std::uint8_t>& secret_key,
    const std::vector<std::uint8_t>& payload,
    std::size_t maximum_bits_per_segment,
    CavlcChannelOptions options = {});
std::vector<std::uint8_t> extract_cavlc_stream_file(
    const std::vector<std::uint8_t>& annex_b,
    const std::vector<std::uint8_t>& secret_key,
    std::size_t maximum_payload_bytes,
    std::size_t maximum_bits_per_segment,
    CavlcChannelOptions options = {});

// Audit view of the file-mode schedule input: for each IDR segment, the
// trailing-one sign candidates exactly as the stream codec collects them.
// Candidate identities (nal_index) are relative to the codec's analysis input
// (stored SPS/PPS context + the segment's own NAL units); rbsp_bit_offset is
// also the bit offset inside the file's IDR NAL at idr_nal_index.
struct CavlcStreamSegmentCandidates {
    std::size_t idr_nal_index{};       // IDR NAL index in the whole file
    std::size_t analysis_nal_index{};  // the same IDR inside the analysis input
    std::vector<CavlcSignCandidate> candidates;
};
std::vector<CavlcStreamSegmentCandidates> analyze_cavlc_stream_file(
    const std::vector<std::uint8_t>& annex_b);

// Video binding digest: a SHA-256 over the whole file that embedding cannot
// change, so a proof bound to it fails on any other or edited video.
//   carriers = the frame_bit_count sign positions the stream codec writes the
//              frame into under secret_key (segment by segment, the first
//              min(cap, candidates) keyed-schedule positions, until the frame ends);
//   digest   = SHA256("zkstego/video-digest/v1" || u32be(frame_bit_count) ||
//              u32be(maximum_bits_per_segment) || for every NAL unit in file order:
//              u32be(1 + rbsp_size) || nal_header_byte || rbsp')
// where rbsp' is the NAL's RBSP (emulation-prevention bytes removed) with exactly
// the carrier bits cleared to 0. Those are the only bits embedding changes, and
// EPB edits do not reach the RBSP, so cover and stego share one digest, while
// every other bit of the file - any other sign included - is covered. Editing a
// carrier bit changes the extracted payload instead, which the proof rejects.
// The verifier needs the stego key anyway to extract. src/video_binding.py is
// the reference. The carriers follow options (selection policy and key mode;
// a per-video verification token suffices); the formula itself is unchanged.
struct CavlcVideoBindingDigest {
    std::array<std::uint8_t, 32> digest{};
    std::size_t carrier_segments{};
    std::size_t nal_units{};
};
CavlcVideoBindingDigest cavlc_video_binding_digest(
    const std::vector<std::uint8_t>& annex_b,
    const std::vector<std::uint8_t>& secret_key,
    std::size_t frame_bit_count,
    std::size_t maximum_bits_per_segment,
    CavlcChannelOptions options = {});

// Incremental Annex-B reader. It retains at most one NAL plus one input chunk,
// recognizes start codes crossing read boundaries, and fails closed on a NAL
// larger than the configured bound. Returned bytes include the start code.
//
// Input strategy: it never asks the stream buffer for more bytes than
// in_avail() reports (capped at 64 KiB), so a live pipe is never stalled
// waiting to fill a large block. When nothing is buffered it blocks for one
// byte, then drains whatever became available. Start-code scanning resumes
// where the previous call stopped, so total work is linear in the input even
// for stream buffers that only ever expose one byte at a time.
class AnnexBNalStreamReader {
public:
    explicit AnnexBNalStreamReader(std::istream& input, std::size_t maximum_nal_bytes = 16U * 1024U * 1024U);
    [[nodiscard]] bool read_next(std::vector<std::uint8_t>& nal_bytes);

private:
    std::istream& input_;
    std::size_t maximum_nal_bytes_{};
    std::vector<std::uint8_t> buffer_;
    // buffer_[0, head_) has already been returned; buffer_[head_, ...) is the
    // pending NAL. scan_ is the next undecided start-code offset.
    std::size_t head_{};
    std::size_t scan_{};
    bool started_{};
    bool eof_{};

    void read_more();
    void compact();
};
std::vector<std::uint8_t> apply_fixed_length_patches(
    const std::vector<std::uint8_t>& source,
    const std::vector<FixedLengthBitPatch>& patches);
std::vector<std::uint8_t> patch_annex_b_nal_rbsp(
    const std::vector<std::uint8_t>& annex_b,
    std::size_t nal_index,
    const std::vector<FixedLengthBitPatch>& patches);
std::vector<std::uint8_t> patch_annex_b_rbsp_plan(
    const std::vector<std::uint8_t>& annex_b,
    const std::vector<AnnexBRbspPatchPlan>& plan);

}  // namespace zkstego
