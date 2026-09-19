#include "zkstego/live.hpp"

#include <algorithm>
#include <limits>
#include <stdexcept>

namespace zkstego {
namespace {

void validate(const std::vector<std::uint8_t>& luma, std::size_t payload_bytes, PixelEmbeddingConfig config) {
    if (config.width == 0 || config.height == 0 || config.width % 2 != 0 || config.height % 2 != 0) {
        throw std::invalid_argument("YUV420P width and height must be positive even values");
    }
    if (config.quantization_step < 4 || config.quantization_step % 4 != 0) {
        throw std::invalid_argument("quantization_step must be a multiple of four");
    }
    const std::size_t pixels = static_cast<std::size_t>(config.width) * config.height;
    if (luma.size() != pixels) throw std::invalid_argument("luma plane size does not match dimensions");
    if (payload_bytes > pixels / 8) throw std::invalid_argument("payload exceeds one-frame pixel capacity");
}

std::size_t position_for_bit(std::size_t bit_index, std::size_t bit_count, std::size_t pixels) {
    // Equally spaced positions make all locations unique for bit_count <= pixels,
    // avoiding visual clustering without storing a position sidecar.
    return (bit_index * pixels) / bit_count;
}

int circular_distance(int a, int b, int modulus) {
    const int linear = std::abs(a - b);
    return std::min(linear, modulus - linear);
}

std::uint8_t quantize_to_bit(std::uint8_t value, int bit, int step) {
    const int remainder = bit == 0 ? step / 4 : (3 * step) / 4;
    const int base = (static_cast<int>(value) / step) * step;
    int selected = 0;
    int best_distance = std::numeric_limits<int>::max();
    for (const int candidate : {base - step + remainder, base + remainder, base + step + remainder}) {
        if (candidate < 0 || candidate > 255) continue;
        const int distance = std::abs(candidate - static_cast<int>(value));
        if (distance < best_distance) {
            selected = candidate;
            best_distance = distance;
        }
    }
    return static_cast<std::uint8_t>(selected);
}

int bit_at(const std::vector<std::uint8_t>& payload, std::size_t bit_index) {
    return (payload[bit_index / 8] >> (7 - (bit_index % 8))) & 1;
}

}  // namespace

std::vector<std::uint8_t> embed_luma_qim(
    const std::vector<std::uint8_t>& luma,
    const std::vector<std::uint8_t>& payload,
    PixelEmbeddingConfig config) {
    validate(luma, payload.size(), config);
    if (payload.empty()) return luma;
    std::vector<std::uint8_t> stego = luma;
    const std::size_t bit_count = payload.size() * 8;
    for (std::size_t bit = 0; bit < bit_count; ++bit) {
        const auto position = position_for_bit(bit, bit_count, stego.size());
        stego[position] = quantize_to_bit(stego[position], bit_at(payload, bit), config.quantization_step);
    }
    return stego;
}

std::vector<std::uint8_t> extract_luma_qim(
    const std::vector<std::uint8_t>& luma,
    std::size_t payload_bytes,
    PixelEmbeddingConfig config) {
    validate(luma, payload_bytes, config);
    std::vector<std::uint8_t> payload(payload_bytes, 0);
    const std::size_t bit_count = payload_bytes * 8;
    if (bit_count == 0) return payload;
    const int step = config.quantization_step;
    for (std::size_t bit = 0; bit < bit_count; ++bit) {
        const auto position = position_for_bit(bit, bit_count, luma.size());
        const int remainder = luma[position] % step;
        const int zero_distance = circular_distance(remainder, step / 4, step);
        const int one_distance = circular_distance(remainder, (3 * step) / 4, step);
        if (one_distance < zero_distance) payload[bit / 8] |= static_cast<std::uint8_t>(1U << (7 - (bit % 8)));
    }
    return payload;
}

}  // namespace zkstego
