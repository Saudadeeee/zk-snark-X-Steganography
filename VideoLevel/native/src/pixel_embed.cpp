#include "zkstego/live.hpp"

#include <algorithm>
#include <charconv>
#include <chrono>
#include <cstdint>
#include <iomanip>
#include <iostream>
#include <stdexcept>
#include <string>
#include <vector>

#ifdef _WIN32
#include <fcntl.h>
#include <io.h>
#endif

namespace {

std::vector<std::uint8_t> parse_hex(const std::string& source) {
    if (source.empty() || source.size() % 2 != 0) throw std::runtime_error("payload hex must be non-empty and even length");
    std::vector<std::uint8_t> result(source.size() / 2);
    for (std::size_t i = 0; i < result.size(); ++i) {
        unsigned value = 0;
        const auto* begin = source.data() + i * 2;
        const auto [ptr, error] = std::from_chars(begin, begin + 2, value, 16);
        if (error != std::errc{} || ptr != begin + 2 || value > 255) throw std::runtime_error("invalid payload hex");
        result[i] = static_cast<std::uint8_t>(value);
    }
    return result;
}

std::uint32_t parse_dimension(const char* source, const char* name) {
    unsigned value = 0;
    const auto [ptr, error] = std::from_chars(source, source + std::char_traits<char>::length(source), value);
    if (error != std::errc{} || *ptr != '\0' || value == 0) throw std::runtime_error(std::string("invalid ") + name);
    return value;
}

}  // namespace

int main(int argc, char** argv) {
    try {
#ifdef _WIN32
        _setmode(_fileno(stdin), _O_BINARY);
        _setmode(_fileno(stdout), _O_BINARY);
#endif
        zkstego::PixelEmbeddingConfig config{};
        std::vector<std::uint8_t> payload;
        bool metrics = false;
        for (int i = 1; i < argc; ++i) {
            const std::string argument(argv[i]);
            if (argument == "--help") {
                std::cerr << "usage: zkstego_pixel_embed --width W --height H --payload-hex HEX [--qim-step 8] [--metrics]\n";
                return 0;
            }
            if (argument == "--metrics") {
                metrics = true;
                continue;
            }
            if ((argument == "--width" || argument == "--height" || argument == "--payload-hex" || argument == "--qim-step") && i + 1 < argc) {
                const char* value = argv[++i];
                if (argument == "--width") config.width = parse_dimension(value, "width");
                else if (argument == "--height") config.height = parse_dimension(value, "height");
                else if (argument == "--payload-hex") payload = parse_hex(value);
                else config.quantization_step = static_cast<std::uint8_t>(parse_dimension(value, "qim-step"));
                continue;
            }
            throw std::runtime_error("unknown or incomplete argument: " + argument);
        }
        if (payload.empty()) throw std::runtime_error("--payload-hex is required");
        const std::size_t luma_bytes = static_cast<std::size_t>(config.width) * config.height;
        const std::size_t frame_bytes = luma_bytes + luma_bytes / 2;
        if (config.width == 0 || config.height == 0 || config.width % 2 != 0 || config.height % 2 != 0) {
            throw std::runtime_error("--width and --height must be positive even values");
        }
        std::vector<std::uint8_t> frame(frame_bytes);
        std::vector<double> embed_ms;
        while (std::cin.read(reinterpret_cast<char*>(frame.data()), static_cast<std::streamsize>(frame.size())) || std::cin.gcount() > 0) {
            if (static_cast<std::size_t>(std::cin.gcount()) != frame.size()) throw std::runtime_error("input ended mid-frame");
            std::vector<std::uint8_t> luma(frame.begin(), frame.begin() + static_cast<std::ptrdiff_t>(luma_bytes));
            const auto started = std::chrono::steady_clock::now();
            const auto stego = zkstego::embed_luma_qim(luma, payload, config);
            const auto elapsed = std::chrono::duration<double, std::milli>(std::chrono::steady_clock::now() - started).count();
            if (metrics) embed_ms.push_back(elapsed);
            std::copy(stego.begin(), stego.end(), frame.begin());
            std::cout.write(reinterpret_cast<const char*>(frame.data()), static_cast<std::streamsize>(frame.size()));
            if (!std::cout) return 1;
        }
        if (metrics) {
            std::sort(embed_ms.begin(), embed_ms.end());
            const double p95 = embed_ms.empty() ? 0.0 : embed_ms[(embed_ms.size() * 95 + 99) / 100 - 1];
            std::cerr << "{\"frames\":" << embed_ms.size() << ",\"p95_embed_ms\":"
                      << std::fixed << std::setprecision(6) << p95 << "}\n";
        }
        return 0;
    } catch (const std::exception& error) {
        std::cerr << "zkstego_pixel_embed: " << error.what() << '\n';
        return 2;
    }
}
