#include "zkstego/cavlc_stream.hpp"
#include "cli_io.hpp"

#include <algorithm>
#include <chrono>
#include <cstdio>
#include <array>
#include <fstream>
#include <iostream>
#include <iterator>
#include <limits>
#include <stdexcept>
#include <string>
#include <string_view>
#include <vector>
#ifdef _WIN32
#include <fcntl.h>
#include <io.h>
#endif

namespace {

void secure_wipe(void* pointer, const std::size_t size) noexcept {
    volatile auto* bytes = static_cast<volatile std::uint8_t*>(pointer);
    for (std::size_t index = 0; index < size; ++index) bytes[index] = 0;
}

class SensitiveKeyText {
public:
    SensitiveKeyText() = default;
    SensitiveKeyText(const SensitiveKeyText&) = delete;
    SensitiveKeyText& operator=(const SensitiveKeyText&) = delete;
    ~SensitiveKeyText() noexcept { secure_wipe(value_.data(), value_.size()); }
    char* data() noexcept { return value_.data(); }
    const char* data() const noexcept { return value_.data(); }
    std::size_t size() const noexcept { return value_.size(); }
    char& operator[](const std::size_t index) noexcept { return value_[index]; }

private:
    // The longest accepted line is "token:" + 128 hex characters, plus an
    // optional CR, the LF delimiter and the terminating NUL; a few spare bytes
    // make an overlong line fail on length rather than on the stream state.
    std::array<char, 140> value_{};
};

class SensitivePayloadText {
public:
    SensitivePayloadText() = default;
    SensitivePayloadText(const SensitivePayloadText&) = delete;
    SensitivePayloadText& operator=(const SensitivePayloadText&) = delete;
    ~SensitivePayloadText() noexcept { secure_wipe(value_.data(), value_.size()); }
    char* data() noexcept { return value_.data(); }
    const char* data() const noexcept { return value_.data(); }
    std::size_t size() const noexcept { return value_.size(); }

private:
    // 8192 hex chars, optional CRLF, and NUL.
    std::array<char, 8195> value_{};
};

class SensitiveBytes {
public:
    explicit SensitiveBytes(const std::size_t capacity = 32U) : value_(capacity) {}
    SensitiveBytes(const SensitiveBytes&) = delete;
    SensitiveBytes& operator=(const SensitiveBytes&) = delete;
    SensitiveBytes(SensitiveBytes&& other) noexcept
        : value_(std::move(other.value_)), written_(other.written_) {
        other.written_ = 0;
    }
    SensitiveBytes& operator=(SensitiveBytes&& other) noexcept {
        if (this != &other) {
            secure_wipe(value_.data(), value_.size());
            value_ = std::move(other.value_);
            written_ = other.written_;
            other.written_ = 0;
        }
        return *this;
    }
    ~SensitiveBytes() noexcept { secure_wipe(value_.data(), value_.size()); }
    void append(const std::uint8_t byte) {
        if (written_ == value_.size()) throw std::invalid_argument("protected key is too long");
        value_[written_++] = byte;
    }
    std::size_t size() const noexcept { return written_; }
    const std::vector<std::uint8_t>& value() const noexcept { return value_; }

private:
    std::vector<std::uint8_t> value_;
    std::size_t written_{};
};

std::uint8_t hex_nibble(const char value) {
    if (value >= '0' && value <= '9') return static_cast<std::uint8_t>(value - '0');
    if (value >= 'a' && value <= 'f') return static_cast<std::uint8_t>(value - 'a' + 10);
    if (value >= 'A' && value <= 'F') return static_cast<std::uint8_t>(value - 'A' + 10);
    throw std::invalid_argument("hex input contains a non-hex character");
}

SensitiveBytes decode_hex(const std::string_view text) {
    if (text.size() % 2U != 0U) throw std::invalid_argument("hex input must have an even number of characters");
    SensitiveBytes bytes(text.size() / 2U);
    for (std::size_t index = 0; index < text.size(); index += 2U) {
        bytes.append(static_cast<std::uint8_t>((hex_nibble(text[index]) << 4U) | hex_nibble(text[index + 1U])));
    }
    return bytes;
}

std::string bytes_to_hex(const std::vector<std::uint8_t>& bytes) {
    constexpr char hex[] = "0123456789abcdef";
    std::string text;
    text.reserve(bytes.size() * 2U);
    for (const auto byte : bytes) {
        text.push_back(hex[byte >> 4U]);
        text.push_back(hex[byte & 0x0fU]);
    }
    return text;
}

std::vector<std::uint8_t> read_binary(const std::string& path) {
    return zkstego::cli::read_binary_file(path);
}

// A channel secret line: the 64-hex master key K, or "token:" followed by the
// 128-hex per-video verification token (schedule_key || whitening_key).
struct ChannelSecret {
    SensitiveBytes bytes;
    bool token{};
};

constexpr std::string_view kTokenPrefix{"token:"};

ChannelSecret parse_channel_secret(const char* text, const std::size_t text_size, const char* source) {
    const auto hex_line = [&](const std::size_t first, const std::size_t count) {
        SensitiveBytes bytes(count / 2U);
        for (std::size_t index = first; index < first + count; index += 2U) {
            bytes.append(static_cast<std::uint8_t>(
                (hex_nibble(text[index]) << 4U) | hex_nibble(text[index + 1U])));
        }
        return bytes;
    };
    if (text_size >= kTokenPrefix.size() && std::string_view(text, kTokenPrefix.size()) == kTokenPrefix) {
        if (text_size - kTokenPrefix.size() != 2U * zkstego::kCavlcVerificationTokenBytes) {
            throw std::invalid_argument("verification token must be 'token:' followed by 128 hex characters");
        }
        return {hex_line(kTokenPrefix.size(), 2U * zkstego::kCavlcVerificationTokenBytes), true};
    }
    if (text_size != 64U) throw std::invalid_argument(std::string(source) + " must contain exactly 64 hex characters");
    return {hex_line(0U, 64U), false};
}

ChannelSecret read_key_file(const std::string& path) {
    std::ifstream key_file;
    std::istream* input = &std::cin;
    if (path != "-") {
        key_file.open(zkstego::cli::os_path(path));
        if (!key_file) throw std::invalid_argument("cannot open protected key file");
        input = &key_file;
    }
    SensitiveKeyText text;
    input->getline(text.data(), static_cast<std::streamsize>(text.size()));
    if (input->fail() && !input->eof()) {
        throw std::invalid_argument("key file must contain exactly one key line");
    }
    std::size_t text_size = std::char_traits<char>::length(text.data());
    if (text_size > 0U && text[text_size - 1U] == '\r') --text_size;
    char trailing{};
    while (input->get(trailing)) {
        if (trailing != ' ' && trailing != '\t' && trailing != '\r' && trailing != '\n') {
            throw std::invalid_argument("key source must contain exactly one hex key line");
        }
    }
    if (input->bad()) throw std::invalid_argument("failed while reading protected key source");
    return parse_channel_secret(text.data(), text_size, "key file");
}

ChannelSecret read_key_stdin_line() {
    SensitiveKeyText text;
    std::cin.getline(text.data(), static_cast<std::streamsize>(text.size()));
    if (std::cin.fail() && !std::cin.eof()) {
        throw std::invalid_argument("stdin key must be exactly one hex key line");
    }
    std::size_t text_size = std::char_traits<char>::length(text.data());
    if (text_size > 0U && text[text_size - 1U] == '\r') --text_size;
    return parse_channel_secret(text.data(), text_size, "stdin key");
}

// Optional trailing channel flags: --select random|low-drift and
// --key-mode master|per-video, each at most once.
zkstego::CavlcChannelOptions parse_channel_flags(const std::vector<std::string>& argv, const std::size_t first) {
    zkstego::CavlcChannelOptions options;
    bool saw_select = false;
    bool saw_key_mode = false;
    if ((argv.size() - first) % 2U != 0U) throw std::invalid_argument("channel flags must be '--name value' pairs");
    for (std::size_t index = first; index < argv.size(); index += 2U) {
        const auto& name = argv[index];
        const auto& value = argv[index + 1U];
        if (name == "--select" && !saw_select) {
            options.selection = zkstego::parse_cavlc_selection_policy(value);
            saw_select = true;
        } else if (name == "--key-mode" && !saw_key_mode) {
            options.key_mode = zkstego::parse_cavlc_key_mode(value);
            saw_key_mode = true;
        } else {
            throw std::invalid_argument("unknown or repeated channel flag (use --select, --key-mode)");
        }
    }
    return options;
}

// A token carries the subkeys of one video, so it only makes sense per-video.
void require_secret_matches_key_mode(const ChannelSecret& secret, const zkstego::CavlcChannelOptions& options) {
    if (secret.token && options.key_mode != zkstego::CavlcKeyMode::PerVideo) {
        throw std::invalid_argument("a verification token requires --key-mode per-video");
    }
}

SensitiveBytes read_hex_payload_stdin_line() {
    SensitivePayloadText text;
    std::cin.getline(text.data(), static_cast<std::streamsize>(text.size()));
    if ((std::cin.fail() && !std::cin.eof()) || std::cin.bad()) {
        throw std::invalid_argument("stdin payload must be a non-empty hex line of at most 4096 bytes");
    }
    auto text_size = std::char_traits<char>::length(text.data());
    if (text_size > 0U && text.data()[text_size - 1U] == '\r') --text_size;
    if (text_size == 0U || text_size > 8192U) {
        throw std::invalid_argument("stdin payload must be a non-empty hex line of at most 4096 bytes");
    }
    return decode_hex(std::string_view(text.data(), text_size));
}

void write_new_binary(const std::string& path, const std::vector<std::uint8_t>& bytes) {
    zkstego::cli::write_new_binary_file(path, bytes);
}

// A start code followed immediately by another start code or EOF yields an empty
// NAL. split_annex_b() drops it in file mode; live mode must skip it too.
bool is_bare_start_code(const std::vector<std::uint8_t>& bytes) {
    const std::vector<std::uint8_t> three{0, 0, 1};
    const std::vector<std::uint8_t> four{0, 0, 0, 1};
    return bytes == three || bytes == four;
}

zkstego::AnnexBNalUnit parse_single_stream_nal(const std::vector<std::uint8_t>& bytes) {
    auto units = zkstego::split_annex_b(bytes);
    if (units.size() != 1U) throw std::invalid_argument("incremental reader did not return exactly one NAL unit");
    return std::move(units.front());
}

void add_capacity_count(std::size_t& total, const std::size_t increment) {
    if (increment > std::numeric_limits<std::size_t>::max() - total) {
        throw std::invalid_argument("stream capacity count exceeds supported range");
    }
    total += increment;
}

void run_live_capacity_measure(
    std::istream& input,
    std::ostream& output,
    const std::size_t maximum_bits_per_segment) {
    if (maximum_bits_per_segment == 0U) {
        throw std::invalid_argument("max-bits-per-IDR must be positive");
    }
    zkstego::AnnexBNalStreamReader reader(input);
    std::vector<zkstego::AnnexBNalUnit> parameter_sets;
    std::vector<std::uint8_t> nal_bytes;
    std::size_t idr_segments = 0U;
    std::size_t raw_candidate_signs = 0U;
    std::size_t candidate_capacity_bits = 0U;
    while (reader.read_next(nal_bytes)) {
        if (is_bare_start_code(nal_bytes)) continue;
        const auto unit = parse_single_stream_nal(nal_bytes);
        if (unit.nal_unit_type == 7U || unit.nal_unit_type == 8U) {
            zkstego::update_parameter_set_context(parameter_sets, unit);
            continue;
        }
        if (unit.nal_unit_type != 5U) continue;

        const auto slices = zkstego::decode_baseline_i_idr_slices(
            zkstego::assemble_cavlc_stream_segment(parameter_sets, unit));
        if (slices.size() != 1U) {
            throw std::invalid_argument("capacity measurement requires one supported IDR slice per segment");
        }
        const auto candidates = zkstego::collect_cavlc_trailing_one_sign_candidates(slices);
        add_capacity_count(raw_candidate_signs, candidates.size());
        add_capacity_count(candidate_capacity_bits,
            std::min(maximum_bits_per_segment, candidates.size()));
        add_capacity_count(idr_segments, 1U);
    }
    if (idr_segments == 0U) throw std::invalid_argument("input stream contained no IDR segments");
    output << "ZKSTEG_CAPACITY_METRICS {\"idr_segments\":" << idr_segments
           << ",\"raw_candidate_signs\":" << raw_candidate_signs
           << ",\"candidate_capacity_bits\":" << candidate_capacity_bits
           << ",\"max_bits_per_idr\":" << maximum_bits_per_segment << "}\n";
    if (!output) throw std::invalid_argument("failed while writing stream capacity metrics");
}

void write_stream_bytes(std::ostream& output, const std::vector<std::uint8_t>& bytes) {
    output.write(reinterpret_cast<const char*>(bytes.data()), static_cast<std::streamsize>(bytes.size()));
    output.flush();
    if (!output) throw std::invalid_argument("failed while forwarding Annex-B NAL");
}

double sample_quantile_ms(std::vector<double> samples, const std::size_t numerator, const std::size_t denominator) {
    if (samples.empty()) return 0.0;
    std::sort(samples.begin(), samples.end());
    const auto index = (samples.size() * numerator + denominator - 1U) / denominator - 1U;
    return samples[index];
}

void run_live_embed(
    std::istream& input,
    std::ostream& output,
    const std::vector<std::uint8_t>& key,
    const std::vector<std::uint8_t>& payload,
    const std::size_t maximum_bits_per_segment,
    const zkstego::CavlcChannelOptions options) {
    // Per-video mode: the encoder derives its subkeys from the first segment
    // as it arrives (its SPS/PPS context and first IDR).
    zkstego::CavlcStreamEncoder encoder(key, payload, maximum_bits_per_segment, options);
    zkstego::AnnexBNalStreamReader reader(input);
    std::vector<zkstego::AnnexBNalUnit> parameter_sets;
    std::vector<std::uint8_t> nal_bytes;
    std::vector<double> segment_latency_ms;
    std::vector<double> idr_service_latency_ms;
    segment_latency_ms.reserve(4096U);
    idr_service_latency_ms.reserve(4096U);
    std::size_t idr_count = 0;
    std::size_t idr_segment_count = 0;
    std::size_t candidate_capacity_bits = 0;
    std::size_t bits_embedded = 0;
    while (reader.read_next(nal_bytes)) {
        if (is_bare_start_code(nal_bytes)) {
            write_stream_bytes(output, nal_bytes);  // keep the output byte-identical
            continue;
        }
        const auto idr_service_started = std::chrono::steady_clock::now();
        auto unit = parse_single_stream_nal(nal_bytes);
        if (unit.nal_unit_type == 7U || unit.nal_unit_type == 8U) {
            zkstego::update_parameter_set_context(parameter_sets, unit);
            write_stream_bytes(output, nal_bytes);
            continue;
        }
        if (unit.nal_unit_type != 5U) {
            write_stream_bytes(output, nal_bytes);
            continue;
        }
        add_capacity_count(idr_segment_count, 1U);
        if (encoder.complete()) {
            write_stream_bytes(output, nal_bytes);
            if (idr_service_latency_ms.size() < 4096U) {
                idr_service_latency_ms.push_back(std::chrono::duration<double, std::milli>(
                    std::chrono::steady_clock::now() - idr_service_started).count());
            }
            continue;
        }
        ++idr_count;
        const auto segment = zkstego::assemble_cavlc_stream_segment(parameter_sets, unit);
        const auto processing_started = std::chrono::steady_clock::now();
        const auto result = encoder.process_segment(segment);
        candidate_capacity_bits += result.candidate_capacity;
        bits_embedded += result.bits_embedded;
        const auto processing_elapsed = std::chrono::duration<double, std::milli>(
            std::chrono::steady_clock::now() - processing_started).count();
        if (segment_latency_ms.size() < 4096U) segment_latency_ms.push_back(processing_elapsed);
        const auto patched_units = zkstego::split_annex_b(result.output);
        const auto patched_idr = std::find_if(patched_units.begin(), patched_units.end(),
            [](const auto& candidate) { return candidate.nal_unit_type == 5U; });
        if (patched_idr == patched_units.end() || std::find_if(std::next(patched_idr), patched_units.end(),
            [](const auto& candidate) { return candidate.nal_unit_type == 5U; }) != patched_units.end()) {
            throw std::invalid_argument("native stream patch did not return exactly one IDR slice");
        }
        write_stream_bytes(output, zkstego::assemble_annex_b({*patched_idr}));
        if (idr_service_latency_ms.size() < 4096U) {
            idr_service_latency_ms.push_back(std::chrono::duration<double, std::milli>(
                std::chrono::steady_clock::now() - idr_service_started).count());
        }
    }
    if (idr_count == 0U) throw std::invalid_argument("input stream contained no IDR slices");
    if (!encoder.complete()) throw std::invalid_argument("IDR stream ended before payload capacity was met");
    std::cerr << "ZKSTEG_STREAM_METRICS {\"patched_idr_segments\":" << idr_count
              << ",\"idr_segment_count\":" << idr_segment_count
              << ",\"idr_service_samples\":" << idr_service_latency_ms.size()
              << ",\"idr_service_sample_limit\":4096"
              << ",\"idr_service_p50_ms\":" << sample_quantile_ms(idr_service_latency_ms, 50U, 100U)
              << ",\"idr_service_p95_ms\":" << sample_quantile_ms(idr_service_latency_ms, 95U, 100U)
              << ",\"candidate_capacity_bits\":" << candidate_capacity_bits
              << ",\"bits_embedded\":" << bits_embedded
              << ",\"segment_process_samples\":" << segment_latency_ms.size()
              << ",\"segment_process_sample_limit\":4096"
              << ",\"segment_process_p50_ms\":" << sample_quantile_ms(segment_latency_ms, 50U, 100U)
              << ",\"segment_process_p95_ms\":" << sample_quantile_ms(segment_latency_ms, 95U, 100U)
              << "}\n";
}

std::vector<std::uint8_t> run_live_extract(
    std::istream& input,
    const std::vector<std::uint8_t>& key,
    const std::size_t maximum_payload_bytes,
    const std::size_t maximum_bits_per_segment,
    const zkstego::CavlcChannelOptions options) {
    zkstego::CavlcStreamDecoder decoder(key, maximum_payload_bytes, maximum_bits_per_segment, options);
    zkstego::AnnexBNalStreamReader reader(input);
    std::vector<zkstego::AnnexBNalUnit> parameter_sets;
    std::vector<std::uint8_t> nal_bytes;
    std::size_t idr_count = 0;
    while (reader.read_next(nal_bytes)) {
        if (is_bare_start_code(nal_bytes)) continue;
        const auto unit = parse_single_stream_nal(nal_bytes);
        if (unit.nal_unit_type == 7U || unit.nal_unit_type == 8U) {
            zkstego::update_parameter_set_context(parameter_sets, unit);
        } else if (unit.nal_unit_type == 5U) {
            ++idr_count;
            decoder.consume_segment(zkstego::assemble_cavlc_stream_segment(parameter_sets, unit));
            if (decoder.complete()) return decoder.payload();
        }
    }
    if (idr_count == 0U) throw std::invalid_argument("input stream contained no IDR slices");
    throw std::invalid_argument("input stream ended before payload was complete");
}

void set_standard_streams_to_binary() {
#ifdef _WIN32
    if (_setmode(_fileno(stdin), _O_BINARY) == -1 || _setmode(_fileno(stdout), _O_BINARY) == -1) {
        throw std::invalid_argument("cannot set standard streams to binary mode");
    }
#endif
}

std::size_t parse_bit_count(const std::string& text) {
    if (text.empty() || text.front() == '-') throw std::invalid_argument("bit count must be non-negative");
    std::size_t consumed = 0;
    const auto count = std::stoull(text, &consumed);
    if (consumed != text.size() || count > std::numeric_limits<std::size_t>::max()) {
        throw std::invalid_argument("bit count is out of range");
    }
    return static_cast<std::size_t>(count);
}

int run(const std::vector<std::string>& argv) {
    const auto argc = static_cast<int>(argv.size());
    if (argc < 2) {
        std::cerr << "usage: zkstego_blind_bits <command> ...  (keyed CAVLC segment protocol v3)\n"
                     "  embed-stream-auth-stdin <input.h264> <new-output.h264> <max-bits-per-IDR> [flags]\n"
                     "      stdin: key line, payload-hex line; writes the stego file\n"
                     "  extract-stream-auth <input.h264> <key-file|-> <maximum-payload-bytes> <max-bits-per-IDR> [flags]\n"
                     "      prints the payload hex; a wrong key fails the frame version/length checks\n"
                     "The frame has no MAC: '-auth' names a keyed command, and the payload's\n"
                     "Groth16 proof (verified by the service) is what authenticates it.\n"
                     "  video-digest <input.h264> <frame-bits> <max-bits-per-IDR> [flags]\n"
                     "      stdin: key line; prints the video binding digest: SHA-256 of every\n"
                     "      NAL's RBSP with exactly the keyed frame-carrier sign bits cleared\n"
                     "  video-token <input.h264>\n"
                     "      stdin: master key line; prints the 128-hex per-video verification token\n"
                     "  measure-live-capacity-stdin <max-bits-per-IDR>\n"
                     "      stdin: raw Annex-B; stdout: ZKSTEG_CAPACITY_METRICS JSON\n"
                     "  embed-live-auth-stdin <max-bits-per-IDR> [flags]\n"
                     "      stdin: key line, payload-hex line, then raw Annex-B; stdout: H.264\n"
                     "  extract-live-auth-stdin <maximum-payload-bytes> <max-bits-per-IDR> [flags]\n"
                     "      stdin: key line, then raw Annex-B; stdout: payload hex\n"
                     "flags (channel parameters, out of band like the cap; defaults = v3):\n"
                     "  --select random|low-drift      sign selection policy (default random)\n"
                     "  --key-mode master|per-video    subkeys from K, or bound to the video (default master)\n"
                     "Each IDR is one segment (stored SPS/PPS + that IDR) carrying at most\n"
                     "max-bits-per-IDR scheduled sign bits. A key line is the 64-hex master key, or\n"
                     "'token:' + 128 hex (a per-video verification token; needs --key-mode per-video).\n"
                     "Key files must have restricted OS access ('-' reads the key from stdin).\n";
        return 2;
    }
    try {
        const std::string operation{argv[1]};
        if (operation == "embed-stream-auth-stdin" && argc >= 5) {
            const auto options = parse_channel_flags(argv, 5U);
            auto key = read_key_stdin_line();
            require_secret_matches_key_mode(key, options);
            auto payload = read_hex_payload_stdin_line();
            const auto maximum_bits = parse_bit_count(argv[4]);
            if (maximum_bits == 0U) throw std::invalid_argument("max-bits-per-IDR must be positive");
            const auto output = zkstego::embed_cavlc_stream_file(
                read_binary(argv[2]), key.bytes.value(), payload.value(), maximum_bits, options);
            write_new_binary(argv[3], output);
            std::cout << "embedded_stream_payload_bytes=" << payload.size()
                      << " output_bytes=" << output.size() << '\n';
            return 0;
        }
        if (operation == "extract-stream-auth" && argc >= 6) {
            const auto options = parse_channel_flags(argv, 6U);
            const auto key = read_key_file(argv[3]);
            require_secret_matches_key_mode(key, options);
            const auto maximum_payload = parse_bit_count(argv[4]);
            const auto maximum_bits = parse_bit_count(argv[5]);
            if (maximum_bits == 0U) throw std::invalid_argument("max-bits-per-IDR must be positive");
            const auto payload = zkstego::extract_cavlc_stream_file(
                read_binary(argv[2]), key.bytes.value(), maximum_payload, maximum_bits, options);
            std::cout << bytes_to_hex(payload) << '\n';
            return 0;
        }
        if (operation == "video-digest" && argc >= 5) {
            const auto options = parse_channel_flags(argv, 5U);
            const auto key = read_key_stdin_line();
            require_secret_matches_key_mode(key, options);
            const auto frame_bits = parse_bit_count(argv[3]);
            const auto maximum_bits = parse_bit_count(argv[4]);
            if (maximum_bits == 0U) throw std::invalid_argument("max-bits-per-IDR must be positive");
            const auto result = zkstego::cavlc_video_binding_digest(
                read_binary(argv[2]), key.bytes.value(), frame_bits, maximum_bits, options);
            const std::vector<std::uint8_t> digest(result.digest.begin(), result.digest.end());
            std::cout << "ZKSTEGO_VIDEO_DIGEST " << bytes_to_hex(digest) << " carrier_segments="
                      << result.carrier_segments << " nal_units=" << result.nal_units << '\n';
            return 0;
        }
        if (operation == "video-token" && argc == 3) {
            const auto key = read_key_stdin_line();
            if (key.token) throw std::invalid_argument("video-token needs the master key, not a token");
            auto token = zkstego::cavlc_verification_token(read_binary(argv[2]), key.bytes.value());
            auto text = bytes_to_hex(token);
            secure_wipe(token.data(), token.size());
            std::cout << text << '\n';
            std::cout.flush();
            secure_wipe(text.data(), text.size());
            if (!std::cout) throw std::invalid_argument("failed while writing the verification token");
            return 0;
        }
        if (operation == "measure-live-capacity-stdin" && argc == 3) {
            set_standard_streams_to_binary();
            const auto maximum_bits = parse_bit_count(argv[2]);
            run_live_capacity_measure(std::cin, std::cout, maximum_bits);
            return 0;
        }
        if (operation == "embed-live-auth-stdin" && argc >= 3) {
            const auto options = parse_channel_flags(argv, 3U);
            set_standard_streams_to_binary();
            auto key = read_key_stdin_line();
            require_secret_matches_key_mode(key, options);
            auto payload = read_hex_payload_stdin_line();
            const auto maximum_bits = parse_bit_count(argv[2]);
            if (maximum_bits == 0U) throw std::invalid_argument("max-bits-per-IDR must be positive");
            run_live_embed(std::cin, std::cout, key.bytes.value(), payload.value(), maximum_bits, options);
            return 0;
        }
        if (operation == "extract-live-auth-stdin" && argc >= 4) {
            const auto options = parse_channel_flags(argv, 4U);
            set_standard_streams_to_binary();
            auto key = read_key_stdin_line();
            require_secret_matches_key_mode(key, options);
            const auto maximum_payload = parse_bit_count(argv[2]);
            const auto maximum_bits = parse_bit_count(argv[3]);
            if (maximum_bits == 0U) throw std::invalid_argument("max-bits-per-IDR must be positive");
            const auto payload = run_live_extract(
                std::cin, key.bytes.value(), maximum_payload, maximum_bits, options);
            std::cout << bytes_to_hex(payload) << '\n';
            return 0;
        }
        throw std::invalid_argument("invalid command arguments");
    } catch (const std::exception& error) {
        std::cerr << "error: " << error.what() << '\n';
        return 2;
    }
}

}  // namespace

// Windows uses wide arguments so Unicode input/output paths survive.
#ifdef _WIN32
int wmain(int argc, wchar_t* argv[]) {
#else
int main(int argc, char* argv[]) {
#endif
    try {
        return run(zkstego::cli::utf8_arguments(argc, argv));
    } catch (const std::exception& error) {
        std::cerr << "error: " << error.what() << '\n';
        return 2;
    }
}
