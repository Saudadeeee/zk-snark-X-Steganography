#include "zkstego/cavlc_stream.hpp"

#include <fstream>
#include <iostream>
#include <iterator>
#include <stdexcept>
#include <string>
#include <vector>

int main(int argc, char* argv[]) {
    if (argc != 2 && argc != 3) {
        std::cerr << "usage: zkstego_idr_inspect <annex-b-h264> [--verbose|--macroblock]\n";
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
        const bool macroblock_mode = argc == 3 && std::string(argv[2]) == "--macroblock";
        if (argc == 3 && !verbose && !macroblock_mode) {
            std::cerr << "unknown option: " << argv[2] << '\n';
            return 2;
        }
        const auto units = zkstego::split_annex_b(annex_b);
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
                      << " first_luma_tc=" << idr.first_luma_block.token.total_coefficients
                      << " first_luma_end=" << idr.first_luma_block.tail.next_bit_offset
                      << '\n';
            if (macroblock_mode) {
                const auto macroblock = zkstego::decode_cavlc_luma_macroblock(
                    units.at(idr.nal_index).rbsp(),
                    idr.first_macroblock.residual_bit_offset,
                    idr.first_macroblock.coded_block_pattern & 0x0fU);
                std::cout << "nal=" << idr.nal_index
                          << " luma_macroblock_end=" << macroblock.next_bit_offset
                          << " total_coefficients=";
                for (std::size_t block_index = 0; block_index < macroblock.blocks.size(); ++block_index) {
                    if (block_index != 0) std::cout << ',';
                    std::cout << macroblock.blocks[block_index].token.total_coefficients;
                }
                std::cout << '\n';
            }
        }
    } catch (const std::exception& error) {
        std::cerr << "native IDR inspection failed: " << error.what() << '\n';
        return 1;
    }
    return 0;
}
