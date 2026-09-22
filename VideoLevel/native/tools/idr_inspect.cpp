#include "zkstego/cavlc_stream.hpp"

#include <fstream>
#include <iostream>
#include <iterator>
#include <stdexcept>
#include <string>
#include <vector>

int main(int argc, char* argv[]) {
    if (argc != 2 && argc != 3) {
        std::cerr << "usage: zkstego_idr_inspect <annex-b-h264> [--verbose]\n";
        return 2;
    }
    const std::string input_path = argv[1];
    std::ifstream input(input_path, std::ios::binary);
    if (!input) {
        std::cerr << "cannot open input: " << input_path << '\n';
        return 2;
    }
    const std::vector<std::uint8_t> annex_b{
        std::istreambuf_iterator<char>(input), std::istreambuf_iterator<char>()};
    try {
        const auto idrs = zkstego::inspect_baseline_idr_headers(annex_b);
        std::cout << "idr_count=" << idrs.size() << '\n';
        const bool verbose = argc == 3 && std::string(argv[2]) == "--verbose";
        for (const auto& idr : idrs) {
            if (!verbose && &idr != &idrs.front() && &idr != &idrs.back()) {
                continue;
            }
            std::cout << "nal=" << idr.nal_index
                      << " first_mb=" << idr.slice_header.first_mb_in_slice
                      << " slice_type=" << idr.slice_header.slice_type
                      << " data_bit_offset=" << idr.slice_header.data_bit_offset
                      << " cbp=" << idr.first_macroblock.coded_block_pattern
                      << " residual_bit_offset=" << idr.first_macroblock.residual_bit_offset
                      << '\n';
        }
    } catch (const std::exception& error) {
        std::cerr << "native IDR inspection failed: " << error.what() << '\n';
        return 1;
    }
    return 0;
}
