#pragma once

#include <cstddef>
#include <cstdint>
#include <vector>

namespace zkstego {

/// Inserts a standards-shaped user-data SEI immediately before the first IDR.
/// This is edge transport metadata, not a replacement for CAVLC proof embedding.
std::vector<std::uint8_t> inject_sei_before_idr(
    const std::vector<std::uint8_t>& annex_b,
    const std::vector<std::uint8_t>& payload);

std::size_t count_nal_type(const std::vector<std::uint8_t>& annex_b, std::uint8_t nal_type);

}  // namespace zkstego
