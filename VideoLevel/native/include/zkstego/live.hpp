#pragma once

#include <cstddef>
#include <cstdint>
#include <vector>

namespace zkstego {

/// Pixel-domain configuration for one Y (luma) plane of a YUV420P frame.
struct PixelEmbeddingConfig {
    std::uint32_t width;
    std::uint32_t height;
    std::uint8_t quantization_step = 8;
};

/// Embed payload bits directly in luma pixels with two QIM cosets. The payload
/// is not written to H.264 headers, SEI, or other metadata.
std::vector<std::uint8_t> embed_luma_qim(
    const std::vector<std::uint8_t>& luma,
    const std::vector<std::uint8_t>& payload,
    PixelEmbeddingConfig config);

/// Recover payload bytes from a luma plane produced by embed_luma_qim().
std::vector<std::uint8_t> extract_luma_qim(
    const std::vector<std::uint8_t>& luma,
    std::size_t payload_bytes,
    PixelEmbeddingConfig config);

}  // namespace zkstego
