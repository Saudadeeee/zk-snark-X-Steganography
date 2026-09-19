#include "zkstego/live.hpp"

#include <charconv>
#include <cstdint>
#include <iostream>
#include <iterator>
#include <string>
#include <vector>

namespace {

std::vector<std::uint8_t> parse_hex(const std::string& source) {
    if (source.size() % 2 != 0) throw std::runtime_error("SEI payload hex must have an even length");
    std::vector<std::uint8_t> result(source.size() / 2);
    for (std::size_t i = 0; i < result.size(); ++i) {
        unsigned value = 0;
        const auto* begin = source.data() + i * 2;
        const auto [ptr, error] = std::from_chars(begin, begin + 2, value, 16);
        if (error != std::errc{} || ptr != begin + 2 || value > 255) throw std::runtime_error("invalid SEI payload hex");
        result[i] = static_cast<std::uint8_t>(value);
    }
    return result;
}
}  // namespace

int main(int argc, char** argv) {
    try {
        std::vector<std::uint8_t> payload;
        for (int i = 1; i < argc; ++i) {
            const std::string argument(argv[i]);
            if (argument == "--help") {
                std::cerr << "usage: zkstego_annexb_relay [--sei-payload-hex HEX]\n";
                return 0;
            }
            if (argument == "--sei-payload-hex" && i + 1 < argc) {
                payload = parse_hex(argv[++i]);
                continue;
            }
            throw std::runtime_error("unknown or incomplete argument: " + argument);
        }
        const std::vector<std::uint8_t> input(std::istreambuf_iterator<char>(std::cin), {});
        const auto output = zkstego::inject_sei_before_idr(input, payload);
        std::cout.write(reinterpret_cast<const char*>(output.data()), static_cast<std::streamsize>(output.size()));
        return std::cout ? 0 : 1;
    } catch (const std::exception& error) {
        std::cerr << "zkstego_annexb_relay: " << error.what() << '\n';
        return 2;
    }
}
