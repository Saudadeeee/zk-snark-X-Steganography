#include "zkstego/cavlc_stream.hpp"

#include <cstdio>
#include <array>
#include <fstream>
#include <iostream>
#include <iterator>
#include <limits>
#include <stdexcept>
#include <string>
#include <vector>

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

class SensitiveBytes {
public:
    SensitiveBytes() { value_.reserve(32U); }
    SensitiveBytes(const SensitiveBytes&) = delete;
    SensitiveBytes& operator=(const SensitiveBytes&) = delete;
    SensitiveBytes(SensitiveBytes&& other) noexcept : value_(std::move(other.value_)) {}
    SensitiveBytes& operator=(SensitiveBytes&& other) noexcept {
        if (this != &other) {
            secure_wipe(value_.data(), value_.size());
            value_ = std::move(other.value_);
        }
        return *this;
    }
    ~SensitiveBytes() noexcept { secure_wipe(value_.data(), value_.capacity()); }
    void append(const std::uint8_t byte) { value_.push_back(byte); }
    std::size_t size() const noexcept { return value_.size(); }
    const std::vector<std::uint8_t>& value() const noexcept { return value_; }

private:
    std::vector<std::uint8_t> value_;
};

std::uint8_t hex_nibble(const char value) {
    if (value >= '0' && value <= '9') return static_cast<std::uint8_t>(value - '0');
    if (value >= 'a' && value <= 'f') return static_cast<std::uint8_t>(value - 'a' + 10);
    if (value >= 'A' && value <= 'F') return static_cast<std::uint8_t>(value - 'A' + 10);
    throw std::invalid_argument("hex input contains a non-hex character");
}

std::vector<std::uint8_t> decode_hex(const std::string& text) {
    if (text.size() % 2U != 0U) throw std::invalid_argument("hex input must have an even number of characters");
    std::vector<std::uint8_t> bytes;
    bytes.reserve(text.size() / 2U);
    for (std::size_t index = 0; index < text.size(); index += 2U) {
        bytes.push_back(static_cast<std::uint8_t>((hex_nibble(text[index]) << 4U) | hex_nibble(text[index + 1U])));
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

std::vector<std::uint8_t> read_binary(const std::string& path) {
    std::ifstream input(path, std::ios::binary);
    if (!input) throw std::invalid_argument("cannot open input video");
    return {std::istreambuf_iterator<char>(input), std::istreambuf_iterator<char>()};
}

SensitiveBytes read_key_file(const std::string& path) {
    std::ifstream input(path);
    if (!input) throw std::invalid_argument("cannot open protected key file");
    SensitiveKeyText text;
    input.getline(text.data(), static_cast<std::streamsize>(text.size()));
    if (input.fail() && !input.eof()) {
        throw std::invalid_argument("key file must contain exactly one 64-character key line");
    }
    std::size_t text_size = std::char_traits<char>::length(text.data());
    if (text_size > 0U && text[text_size - 1U] == '\r') --text_size;
    char trailing{};
    while (input.get(trailing)) {
        if (trailing != ' ' && trailing != '\t' && trailing != '\r' && trailing != '\n') {
            throw std::invalid_argument("key file must contain exactly one hex key line");
        }
    }
    if (input.bad()) throw std::invalid_argument("failed while reading protected key file");
    if (text_size != 64U) throw std::invalid_argument("key file must contain exactly 64 hex characters");
    SensitiveBytes key;
    for (std::size_t index = 0; index < text_size; index += 2U) {
        key.append(static_cast<std::uint8_t>(
            (hex_nibble(text[index]) << 4U) | hex_nibble(text[index + 1U])));
    }
    if (key.size() != 32U) throw std::invalid_argument("key file must decode to exactly 32 bytes");
    return key;
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
                     "key file: one 64-hex-character key line; restrict OS access to it.\n"
                     "warning: extraction prints unauthenticated raw bits; it does not reject wrong keys.\n";
        return 2;
    }
    try {
        const std::string operation{argv[1]};
        if (operation == "embed" && argc == 6) {
            const auto key = read_key_file(argv[3]);
            const auto payload = decode_hex(argv[4]);
            const auto stego = zkstego::embed_keyed_cavlc_sign_bits(
                read_binary(argv[2]), key.value(), bytes_to_bits(payload));
            write_new_binary(argv[5], stego);
            std::cout << "embedded_bits=" << payload.size() * 8U << " output_bytes=" << stego.size() << '\n';
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
        throw std::invalid_argument("invalid command arguments");
    } catch (const std::exception& error) {
        std::cerr << "error: " << error.what() << '\n';
        return 2;
    }
}
