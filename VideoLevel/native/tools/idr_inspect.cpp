#include "zkstego/cavlc_stream.hpp"

#include <array>
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
    const bool verbose = argc == 3 && std::string(argv[2]) == "--verbose";
    const bool macroblock_mode = argc == 3 && std::string(argv[2]) == "--macroblock";
    if (argc == 3 && !verbose && !macroblock_mode) {
        std::cerr << "unknown option: " << argv[2] << '\n';
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
        const auto units = zkstego::split_annex_b(annex_b);
        std::size_t decoded_first_luma_macroblocks = 0;
        for (const auto& idr : idrs) {
            if (!verbose && !macroblock_mode && &idr != &idrs.front() && &idr != &idrs.back()) {
                continue;
            }
            if (macroblock_mode) {
                if (idr.first_macroblock.mb_type != 0) {
                    throw std::invalid_argument(
                        "--macroblock currently supports I4x4 macroblocks only; encountered I16x16 syntax");
                }
                const auto macroblock = zkstego::decode_cavlc_luma_macroblock(
                    units.at(idr.nal_index).rbsp(),
                    idr.first_macroblock.residual_bit_offset,
                    idr.first_macroblock.coded_block_pattern & 0x0fU);
                auto residual_end = macroblock.next_bit_offset;
                std::uint32_t cb_chroma_dc_tc = 0;
                std::uint32_t cr_chroma_dc_tc = 0;
                std::array<std::uint32_t, 8> chroma_ac_total_coefficients{};
                if (((idr.first_macroblock.coded_block_pattern >> 4U) & 0x03U) >= 1U) {
                    const auto cb_chroma_dc = zkstego::decode_cavlc_chroma_dc_block(
                        units.at(idr.nal_index).rbsp(), residual_end);
                    const auto cr_chroma_dc = zkstego::decode_cavlc_chroma_dc_block(
                        units.at(idr.nal_index).rbsp(), cb_chroma_dc.tail.next_bit_offset);
                    cb_chroma_dc_tc = cb_chroma_dc.token.total_coefficients;
                    cr_chroma_dc_tc = cr_chroma_dc.token.total_coefficients;
                    residual_end = cr_chroma_dc.tail.next_bit_offset;
                }
                if (((idr.first_macroblock.coded_block_pattern >> 4U) & 0x03U) >= 2U) {
                    for (std::size_t component = 0; component < 2; ++component) {
                        for (std::size_t local_index = 0; local_index < 4; ++local_index) {
                            const auto x = local_index % 2;
                            const auto y = local_index / 2;
                            const auto n_a = x == 0 ? 0U : chroma_ac_total_coefficients[component * 4 + local_index - 1];
                            const auto n_b = y == 0 ? 0U : chroma_ac_total_coefficients[component * 4 + local_index - 2];
                            const auto n_c = x != 0 && y != 0 ? static_cast<int>((n_a + n_b + 1U) / 2U)
                                           : x != 0 ? static_cast<int>(n_a)
                                                    : y != 0 ? static_cast<int>(n_b)
                                                             : 0;
                            const auto block = zkstego::decode_cavlc_chroma_ac_block(
                                units.at(idr.nal_index).rbsp(), residual_end, n_c);
                            chroma_ac_total_coefficients[component * 4 + local_index] = block.token.total_coefficients;
                            residual_end = block.tail.next_bit_offset;
                        }
                    }
                }
                ++decoded_first_luma_macroblocks;
                if (&idr == &idrs.front() || &idr == &idrs.back()) {
                    std::cout << "nal=" << idr.nal_index
                              << " luma_macroblock_end=" << macroblock.next_bit_offset
                              << " total_coefficients=";
                    for (std::size_t block_index = 0; block_index < macroblock.blocks.size(); ++block_index) {
                        if (block_index != 0) std::cout << ',';
                        std::cout << macroblock.blocks[block_index].token.total_coefficients;
                    }
                    std::cout << " chroma_dc_tc=" << cb_chroma_dc_tc << ',' << cr_chroma_dc_tc
                              << " chroma_ac_tc=";
                    for (std::size_t block_index = 0; block_index < chroma_ac_total_coefficients.size(); ++block_index) {
                        if (block_index != 0) std::cout << ',';
                        std::cout << chroma_ac_total_coefficients[block_index];
                    }
                    std::cout << " residual_end=" << residual_end << '\n';
                }
            }
            if (!macroblock_mode || &idr == &idrs.front() || &idr == &idrs.back()) {
                std::cout << "nal=" << idr.nal_index
                          << " first_mb=" << idr.slice_header.first_mb_in_slice
                          << " slice_type=" << idr.slice_header.slice_type
                          << " data_bit_offset=" << idr.slice_header.data_bit_offset
                          << " cbp=" << idr.first_macroblock.coded_block_pattern
                          << " residual_bit_offset=" << idr.first_macroblock.residual_bit_offset
                          << " first_luma_tc=" << idr.first_luma_block.token.total_coefficients
                          << " first_luma_end=" << idr.first_luma_block.tail.next_bit_offset
                          << '\n';
            }
        }
        if (macroblock_mode) {
            std::cout << "decoded_first_luma_macroblocks=" << decoded_first_luma_macroblocks << '\n';
        }
    } catch (const std::exception& error) {
        std::cerr << "native IDR inspection failed: " << error.what() << '\n';
        return 1;
    }
    return 0;
}
