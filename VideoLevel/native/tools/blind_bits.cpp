#include "zkstego/cavlc_stream.hpp"

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
    // 64 hex characters, optional CR, LF delimiter, and terminating NUL.
    std::array<char, 67> value_{};
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

std::vector<std::uint8_t> bytes_to_bits(const std::vector<std::uint8_t>& bytes) {
    std::vector<std::uint8_t> bits;
    bits.reserve(bytes.size() * 8U);
    for (const auto byte : bytes) {
        for (std::uint8_t shift = 8U; shift-- > 0U;) bits.push_back((byte >> shift) & 1U);
    }
    return bits;
}

std::string bits_to_hex(const std::vector<std::uint8_t>& bits) {
    if (bits.size() % 8U != 0U) throw std::invalid_argument("extraction bit count must be a multiple of eight");
    constexpr char hex[] = "0123456789abcdef";
    std::string text;
    text.reserve(bits.size() / 4U);
    for (std::size_t index = 0; index < bits.size(); index += 8U) {
        std::uint8_t byte = 0;
        for (std::size_t bit = 0; bit < 8U; ++bit) byte = static_cast<std::uint8_t>((byte << 1U) | bits[index + bit]);
        text.push_back(hex[byte >> 4U]);
        text.push_back(hex[byte & 0x0fU]);
    }
    return text;
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
    std::ifstream input(path, std::ios::binary);
    if (!input) throw std::invalid_argument("cannot open input video");
    return {std::istreambuf_iterator<char>(input), std::istreambuf_iterator<char>()};
}

SensitiveBytes read_key_file(const std::string& path) {
    std::ifstream key_file;
    std::istream* input = &std::cin;
    if (path != "-") {
        key_file.open(path);
        if (!key_file) throw std::invalid_argument("cannot open protected key file");
        input = &key_file;
    }
    SensitiveKeyText text;
    input->getline(text.data(), static_cast<std::streamsize>(text.size()));
    if (input->fail() && !input->eof()) {
        throw std::invalid_argument("key file must contain exactly one 64-character key line");
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
    if (text_size != 64U) throw std::invalid_argument("key file must contain exactly 64 hex characters");
    SensitiveBytes key;
    for (std::size_t index = 0; index < text_size; index += 2U) {
        key.append(static_cast<std::uint8_t>(
            (hex_nibble(text[index]) << 4U) | hex_nibble(text[index + 1U])));
    }
    if (key.size() != 32U) throw std::invalid_argument("key file must decode to exactly 32 bytes");
    return key;
}

SensitiveBytes read_key_stdin_line() {
    SensitiveKeyText text;
    std::cin.getline(text.data(), static_cast<std::streamsize>(text.size()));
    if (std::cin.fail() && !std::cin.eof()) {
        throw std::invalid_argument("stdin key must be exactly one 64-character hex line");
    }
    std::size_t text_size = std::char_traits<char>::length(text.data());
    if (text_size > 0U && text[text_size - 1U] == '\r') --text_size;
    if (text_size != 64U) throw std::invalid_argument("stdin key must contain exactly 64 hex characters");
    SensitiveBytes key;
    for (std::size_t index = 0; index < text_size; index += 2U) {
        key.append(static_cast<std::uint8_t>(
            (hex_nibble(text[index]) << 4U) | hex_nibble(text[index + 1U])));
    }
    return key;
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
    std::FILE* output = nullptr;
#ifdef _MSC_VER
    if (fopen_s(&output, path.c_str(), "wbx") != 0 || output == nullptr) {
        throw std::invalid_argument("cannot exclusively create output video");
    }
#else
    output = std::fopen(path.c_str(), "wbx");
    if (output == nullptr) throw std::invalid_argument("cannot exclusively create output video");
#endif
    const auto written = std::fwrite(bytes.data(), 1U, bytes.size(), output);
    const auto closed = std::fclose(output);
    if (written != bytes.size() || closed != 0) {
        throw std::invalid_argument("failed while writing output video");
    }
}

std::vector<std::uint8_t> embed_authenticated_idr_stream(
    const std::vector<std::uint8_t>& input,
    const std::vector<std::uint8_t>& key,
    const std::vector<std::uint8_t>& payload,
    const std::size_t maximum_bits_per_segment) {
    const auto units = zkstego::split_annex_b(input);
    if (units.empty()) throw std::invalid_argument("input contains no Annex-B NAL units");
    zkstego::AuthenticatedCavlcStreamEncoder encoder(key, payload, maximum_bits_per_segment);
    std::vector<zkstego::AnnexBNalUnit> parameter_sets;
    std::vector<zkstego::AnnexBNalUnit> output_units;
    std::size_t idr_count = 0;
    for (const auto& unit : units) {
        if (unit.nal_unit_type == 7U || unit.nal_unit_type == 8U) {
            const auto existing = std::find_if(parameter_sets.begin(), parameter_sets.end(),
                [&](const auto& item) { return item.nal_unit_type == unit.nal_unit_type; });
            if (existing == parameter_sets.end()) parameter_sets.push_back(unit);
            else *existing = unit;
        }
        if (unit.nal_unit_type != 5U) {
            output_units.push_back(unit);
            continue;
        }
        ++idr_count;
        auto segment = parameter_sets;
        segment.push_back(unit);
        auto result = encoder.process_segment(zkstego::assemble_annex_b(segment));
        const auto patched = zkstego::split_annex_b(result.output);
        const auto idr = std::find_if(patched.begin(), patched.end(),
            [](const auto& item) { return item.nal_unit_type == 5U; });
        if (idr == patched.end() || std::find_if(std::next(idr), patched.end(),
            [](const auto& item) { return item.nal_unit_type == 5U; }) != patched.end()) {
            throw std::invalid_argument("native stream patch did not return exactly one IDR slice");
        }
        auto output_idr = unit;
        output_idr.payload = idr->payload;
        output_units.push_back(std::move(output_idr));
    }
    if (idr_count == 0U) throw std::invalid_argument("input contains no IDR slices");
    if (!encoder.complete()) throw std::invalid_argument("IDR stream capacity is insufficient for authenticated payload");
    return zkstego::assemble_annex_b(output_units);
}

std::vector<std::uint8_t> extract_authenticated_idr_stream(
    const std::vector<std::uint8_t>& input,
    const std::vector<std::uint8_t>& key,
    const std::size_t maximum_payload_bytes,
    const std::size_t maximum_bits_per_segment) {
    const auto units = zkstego::split_annex_b(input);
    if (units.empty()) throw std::invalid_argument("input contains no Annex-B NAL units");
    zkstego::AuthenticatedCavlcStreamDecoder decoder(key, maximum_payload_bytes, maximum_bits_per_segment);
    std::vector<zkstego::AnnexBNalUnit> parameter_sets;
    std::size_t idr_count = 0;
    for (const auto& unit : units) {
        if (unit.nal_unit_type == 7U || unit.nal_unit_type == 8U) {
            const auto existing = std::find_if(parameter_sets.begin(), parameter_sets.end(),
                [&](const auto& item) { return item.nal_unit_type == unit.nal_unit_type; });
            if (existing == parameter_sets.end()) parameter_sets.push_back(unit);
            else *existing = unit;
        } else if (unit.nal_unit_type == 5U) {
            ++idr_count;
            auto segment = parameter_sets;
            segment.push_back(unit);
            decoder.consume_segment(zkstego::assemble_annex_b(segment));
            if (decoder.complete()) break;
        }
    }
    if (idr_count == 0U) throw std::invalid_argument("input contains no IDR slices");
    if (!decoder.complete()) throw std::invalid_argument("IDR stream ended before authenticated payload was complete");
    return decoder.authenticated_payload();
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
        const auto unit = parse_single_stream_nal(nal_bytes);
        if (unit.nal_unit_type == 7U || unit.nal_unit_type == 8U) {
            const auto existing = std::find_if(parameter_sets.begin(), parameter_sets.end(),
                [&](const auto& item) { return item.nal_unit_type == unit.nal_unit_type; });
            if (existing == parameter_sets.end()) parameter_sets.push_back(unit);
            else *existing = unit;
            continue;
        }
        if (unit.nal_unit_type != 5U) continue;

        auto segment = parameter_sets;
        segment.push_back(unit);
        const auto slices = zkstego::decode_baseline_i_idr_slices(
            zkstego::assemble_annex_b(segment));
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

void run_live_authenticated_embed(
    std::istream& input,
    std::ostream& output,
    const std::vector<std::uint8_t>& key,
    const std::vector<std::uint8_t>& payload,
    const std::size_t maximum_bits_per_segment) {
    zkstego::AuthenticatedCavlcStreamEncoder encoder(key, payload, maximum_bits_per_segment);
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
        const auto idr_service_started = std::chrono::steady_clock::now();
        auto unit = parse_single_stream_nal(nal_bytes);
        if (unit.nal_unit_type == 7U || unit.nal_unit_type == 8U) {
            const auto existing = std::find_if(parameter_sets.begin(), parameter_sets.end(),
                [&](const auto& item) { return item.nal_unit_type == unit.nal_unit_type; });
            if (existing == parameter_sets.end()) parameter_sets.push_back(unit);
            else *existing = unit;
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
        auto segment = parameter_sets;
        segment.push_back(unit);
        const auto processing_started = std::chrono::steady_clock::now();
        const auto result = encoder.process_segment(zkstego::assemble_annex_b(segment));
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
    if (!encoder.complete()) throw std::invalid_argument("IDR stream ended before authenticated payload capacity was met");
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

std::vector<std::uint8_t> run_live_authenticated_extract(
    std::istream& input,
    const std::vector<std::uint8_t>& key,
    const std::size_t maximum_payload_bytes,
    const std::size_t maximum_bits_per_segment) {
    zkstego::AuthenticatedCavlcStreamDecoder decoder(key, maximum_payload_bytes, maximum_bits_per_segment);
    zkstego::AnnexBNalStreamReader reader(input);
    std::vector<zkstego::AnnexBNalUnit> parameter_sets;
    std::vector<std::uint8_t> nal_bytes;
    std::size_t idr_count = 0;
    while (reader.read_next(nal_bytes)) {
        const auto unit = parse_single_stream_nal(nal_bytes);
        if (unit.nal_unit_type == 7U || unit.nal_unit_type == 8U) {
            const auto existing = std::find_if(parameter_sets.begin(), parameter_sets.end(),
                [&](const auto& item) { return item.nal_unit_type == unit.nal_unit_type; });
            if (existing == parameter_sets.end()) parameter_sets.push_back(unit);
            else *existing = unit;
        } else if (unit.nal_unit_type == 5U) {
            ++idr_count;
            auto segment = parameter_sets;
            segment.push_back(unit);
            decoder.consume_segment(zkstego::assemble_annex_b(segment));
            if (decoder.complete()) return decoder.authenticated_payload();
        }
    }
    if (idr_count == 0U) throw std::invalid_argument("input stream contained no IDR slices");
    throw std::invalid_argument("input stream ended before authenticated payload was complete");
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

}  // namespace

int main(int argc, char* argv[]) {
    if (argc < 2) {
        std::cerr << "usage: zkstego_blind_bits embed <input.h264> <protected-key-file> <payload-hex> <new-output.h264>\n"
                     "   or: zkstego_blind_bits extract <input.h264> <protected-key-file> <bit-count-multiple-of-8>\n"
                     "   or: zkstego_blind_bits embed-auth <input.h264> <protected-key-file> <payload-hex> <new-output.h264>\n"
                     "   or: zkstego_blind_bits embed-auth-stdin <input.h264> <new-output.h264>\n"
                     "   or: zkstego_blind_bits extract-auth <input.h264> <protected-key-file> <maximum-payload-bytes>\n"
                     "   or: zkstego_blind_bits embed-stream-auth-stdin <input.h264> <new-output.h264> <max-bits-per-IDR>\n"
                     "   or: zkstego_blind_bits extract-stream-auth <input.h264> <protected-key-file> <maximum-payload-bytes> <max-bits-per-IDR>\n"
                     "   or: zkstego_blind_bits measure-live-capacity-stdin <max-bits-per-IDR> (raw Annex-B stdin; JSON metrics stdout)\n"
                     "   or: zkstego_blind_bits embed-live-auth-stdin <max-bits-per-IDR> (key+payload lines, then raw Annex-B stdin; H.264 stdout)\n"
                     "   or: zkstego_blind_bits extract-live-auth-stdin <maximum-payload-bytes> <max-bits-per-IDR> (key line, then raw Annex-B stdin; payload hex stdout)\n"
                     "key source: one 64-hex-character key line; use '-' to read it from stdin.\n"
                     "embed-auth-stdin reads the key line followed by one payload-hex line from stdin.\n"
                     "key files must have restricted OS access.\n"
                     "warning: extraction prints unauthenticated raw bits; it does not reject wrong keys.\n";
        return 2;
    }
    try {
        const std::string operation{argv[1]};
        if (operation == "embed" && argc == 6) {
            const auto key = read_key_file(argv[3]);
            const auto payload = decode_hex(argv[4]);
            const auto stego = zkstego::embed_keyed_cavlc_sign_bits(
                read_binary(argv[2]), key.value(), bytes_to_bits(payload.value()));
            write_new_binary(argv[5], stego);
            std::cout << "embedded_bits=" << payload.size() * 8U << " output_bytes=" << stego.size() << '\n';
            return 0;
        }
        if (operation == "embed-auth" && argc == 6) {
            const auto key = read_key_file(argv[3]);
            const auto payload = decode_hex(argv[4]);
            const auto stego = zkstego::embed_authenticated_cavlc_payload(
                read_binary(argv[2]), key.value(), payload.value());
            write_new_binary(argv[5], stego);
            std::cout << "embedded_authenticated_payload_bytes=" << payload.size()
                      << " output_bytes=" << stego.size() << '\n';
            return 0;
        }
        if (operation == "embed-auth-stdin" && argc == 4) {
            auto key = read_key_stdin_line();
            auto payload = read_hex_payload_stdin_line();
            const auto stego = zkstego::embed_authenticated_cavlc_payload(
                read_binary(argv[2]), key.value(), payload.value());
            write_new_binary(argv[3], stego);
            std::cout << "embedded_authenticated_payload_bytes=" << payload.size()
                      << " output_bytes=" << stego.size() << '\n';
            return 0;
        }
        if (operation == "extract" && argc == 5) {
            const auto key = read_key_file(argv[3]);
            const auto count = parse_bit_count(argv[4]);
            if (count % 8U != 0U) throw std::invalid_argument("bit count must be a multiple of eight");
            std::cerr << "warning: printing unauthenticated raw bits; wrong keys are not rejected\n";
            std::cout << bits_to_hex(zkstego::extract_keyed_cavlc_sign_bits(
                read_binary(argv[2]), key.value(), count)) << '\n';
            return 0;
        }
        if (operation == "extract-auth" && argc == 5) {
            const auto key = read_key_file(argv[3]);
            const auto maximum_payload_bytes = parse_bit_count(argv[4]);
            std::cout << bytes_to_hex(zkstego::extract_authenticated_cavlc_payload(
                read_binary(argv[2]), key.value(), maximum_payload_bytes)) << '\n';
            return 0;
        }
        if (operation == "embed-stream-auth-stdin" && argc == 5) {
            auto key = read_key_stdin_line();
            auto payload = read_hex_payload_stdin_line();
            const auto maximum_bits = parse_bit_count(argv[4]);
            if (maximum_bits == 0U) throw std::invalid_argument("max-bits-per-IDR must be positive");
            const auto output = embed_authenticated_idr_stream(
                read_binary(argv[2]), key.value(), payload.value(), maximum_bits);
            write_new_binary(argv[3], output);
            std::cout << "embedded_authenticated_stream_payload_bytes=" << payload.size()
                      << " output_bytes=" << output.size() << '\n';
            return 0;
        }
        if (operation == "extract-stream-auth" && argc == 6) {
            const auto key = read_key_file(argv[3]);
            const auto maximum_payload = parse_bit_count(argv[4]);
            const auto maximum_bits = parse_bit_count(argv[5]);
            if (maximum_bits == 0U) throw std::invalid_argument("max-bits-per-IDR must be positive");
            const auto payload = extract_authenticated_idr_stream(
                read_binary(argv[2]), key.value(), maximum_payload, maximum_bits);
            std::cout << bytes_to_hex(payload) << '\n';
            return 0;
        }
        if (operation == "measure-live-capacity-stdin" && argc == 3) {
            set_standard_streams_to_binary();
            const auto maximum_bits = parse_bit_count(argv[2]);
            run_live_capacity_measure(std::cin, std::cout, maximum_bits);
            return 0;
        }
        if (operation == "embed-live-auth-stdin" && argc == 3) {
            set_standard_streams_to_binary();
            auto key = read_key_stdin_line();
            auto payload = read_hex_payload_stdin_line();
            const auto maximum_bits = parse_bit_count(argv[2]);
            if (maximum_bits == 0U) throw std::invalid_argument("max-bits-per-IDR must be positive");
            run_live_authenticated_embed(std::cin, std::cout, key.value(), payload.value(), maximum_bits);
            return 0;
        }
        if (operation == "extract-live-auth-stdin" && argc == 4) {
            set_standard_streams_to_binary();
            auto key = read_key_stdin_line();
            const auto maximum_payload = parse_bit_count(argv[2]);
            const auto maximum_bits = parse_bit_count(argv[3]);
            if (maximum_bits == 0U) throw std::invalid_argument("max-bits-per-IDR must be positive");
            const auto payload = run_live_authenticated_extract(
                std::cin, key.value(), maximum_payload, maximum_bits);
            std::cout << bytes_to_hex(payload) << '\n';
            return 0;
        }
        throw std::invalid_argument("invalid command arguments");
    } catch (const std::exception& error) {
        std::cerr << "error: " << error.what() << '\n';
        return 2;
    }
}
