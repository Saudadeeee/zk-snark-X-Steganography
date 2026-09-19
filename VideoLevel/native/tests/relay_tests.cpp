#include "zkstego/live.hpp"

#include <cassert>
#include <cstdlib>
#include <cstdint>
#include <iostream>
#include <vector>

int main() {
    zkstego::PixelEmbeddingConfig config{16, 16, 8};
    std::vector<std::uint8_t> luma(16 * 16, 128);
    const std::vector<std::uint8_t> payload{0xCA, 0xFE};

    const auto stego = zkstego::embed_luma_qim(luma, payload, config);
    assert(stego.size() == luma.size());
    for (std::size_t i = 0; i < luma.size(); ++i) {
        assert(std::abs(static_cast<int>(stego[i]) - static_cast<int>(luma[i])) <= 4);
    }

    std::vector<std::uint8_t> lightly_reencoded = stego;
    for (std::size_t i = 0; i < lightly_reencoded.size(); i += 3) {
        ++lightly_reencoded[i];
    }
    assert(zkstego::extract_luma_qim(lightly_reencoded, payload.size(), config) == payload);
    std::cout << "native pixel QIM: 4/4 passed\n";
}
