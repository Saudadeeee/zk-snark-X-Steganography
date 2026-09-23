#include "zkstego/cavlc_stream.hpp"

#include <algorithm>
#include <array>
#include <cstdio>
#include <fstream>
#include <iostream>
#include <iterator>
#include <limits>
#include <optional>
#include <stdexcept>
#include <string>
#include <vector>

int main(int argc, char* argv[]) {
    if (argc < 2 || argc > 6) {
        std::cerr << "usage: zkstego_idr_inspect <annex-b-h264> [--verbose|--macroblock|--slice] [--nal-index <index>] [--flip-first-sign <new-output>]\n";
        return 2;
    }
    bool verbose = false;
    bool macroblock_mode = false;
    bool slice_mode = false;
    std::optional<std::size_t> selected_nal_index;
    std::optional<std::string> flip_first_sign_output;
    for (int argument_index = 2; argument_index < argc; ++argument_index) {
        const std::string argument{argv[argument_index]};
        if (argument == "--verbose") {
            verbose = true;
        } else if (argument == "--macroblock") {
            macroblock_mode = true;
        } else if (argument == "--slice") {
            slice_mode = true;
        } else if (argument == "--flip-first-sign") {
            if (++argument_index >= argc) {
                std::cerr << "--flip-first-sign requires a new output path\n";
                return 2;
            }
            flip_first_sign_output = argv[argument_index];
            if (flip_first_sign_output->empty()) {
                std::cerr << "--flip-first-sign output must be a new path\n";
                return 2;
            }
        } else if (argument == "--nal-index") {
            if (++argument_index >= argc) {
                std::cerr << "--nal-index requires a non-negative NAL index\n";
                return 2;
            }
            try {
                const auto index_text = std::string{argv[argument_index]};
                if (index_text.empty() || index_text.front() == '-') {
                    throw std::invalid_argument("negative index");
                }
                std::size_t consumed = 0;
                const auto parsed = std::stoull(index_text, &consumed);
                if (consumed != index_text.size()) throw std::invalid_argument("trailing text");
                if (parsed > std::numeric_limits<std::size_t>::max()) {
                    throw std::out_of_range("NAL index is out of range");
                }
                selected_nal_index = static_cast<std::size_t>(parsed);
            } catch (const std::exception&) {
                std::cerr << "--nal-index requires a non-negative NAL index\n";
                return 2;
            }
        } else {
            std::cerr << "unknown option: " << argument << '\n';
            return 2;
        }
    }
    if (flip_first_sign_output.has_value() && selected_nal_index.has_value()) {
        std::cerr << "--flip-first-sign cannot be combined with --nal-index\n";
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
        if (flip_first_sign_output.has_value()) {
            const auto slices = zkstego::decode_baseline_i_idr_slices(annex_b);
            const auto candidates = zkstego::collect_cavlc_trailing_one_sign_candidates(slices);
            if (candidates.empty()) throw std::invalid_argument("input has no trailing-one sign candidates");
            const auto& candidate = candidates.front();
            const auto units = zkstego::split_annex_b(annex_b);
            const auto rbsp = units.at(candidate.nal_index).rbsp();
            const auto original_bit = static_cast<std::uint8_t>(
                (rbsp[candidate.rbsp_bit_offset / 8U] >> (7U - candidate.rbsp_bit_offset % 8U)) & 1U);
            const auto patched = zkstego::patch_annex_b_rbsp_plan(annex_b, {
                {candidate.nal_index, {{candidate.rbsp_bit_offset, {static_cast<std::uint8_t>(1U - original_bit)}}}},
            });
            // "x" requests exclusive creation, closing the existence/open
            // race and refusing an output path that appeared after CLI parse.
            std::FILE* output = nullptr;
#ifdef _MSC_VER
            if (fopen_s(&output, flip_first_sign_output->c_str(), "wbx") != 0 || output == nullptr) {
                throw std::invalid_argument("cannot exclusively create requested output path");
            }
#else
            output = std::fopen(flip_first_sign_output->c_str(), "wbx");
            if (output == nullptr) {
                throw std::invalid_argument("cannot exclusively create requested output path");
            }
#endif
            const auto bytes_written = std::fwrite(patched.data(), 1U, patched.size(), output);
            const auto close_status = std::fclose(output);
            if (bytes_written != patched.size() || close_status != 0) {
                throw std::invalid_argument("failed while writing patched output");
            }
            std::cout << "patched_nal=" << candidate.nal_index
                      << " macroblock=" << candidate.macroblock_address
                      << " rbsp_bit=" << candidate.rbsp_bit_offset
                      << " output_bytes=" << patched.size() << '\n';
            return 0;
        }
        const auto idrs = zkstego::inspect_baseline_idr_headers(annex_b);
        std::cout << "idr_count=" << idrs.size() << '\n';
        if (slice_mode) {
            const auto slices = zkstego::decode_baseline_i_idr_slices(annex_b);
            std::size_t decoded_macroblocks = 0;
            for (const auto& slice : slices) {
                if (selected_nal_index.has_value() && slice.nal_index != *selected_nal_index) continue;
                decoded_macroblocks += slice.macroblocks.size();
                std::cout << "nal=" << slice.nal_index
                          << " macroblocks=" << slice.macroblocks.size()
                          << " trailing_bit=" << slice.rbsp_trailing_bit_offset << '\n';
            }
            if (selected_nal_index.has_value() && decoded_macroblocks == 0U) {
                throw std::invalid_argument("selected NAL is not an inspectable full I IDR slice");
            }
            std::cout << "decoded_i_macroblocks=" << decoded_macroblocks << '\n';
            return 0;
        }
        const auto units = zkstego::split_annex_b(annex_b);
        std::size_t decoded_first_luma_macroblocks = 0;
        for (const auto& idr : idrs) {
            if (selected_nal_index.has_value() && idr.nal_index != *selected_nal_index) {
                continue;
            }
            if (!verbose && !macroblock_mode && &idr != &idrs.front() && &idr != &idrs.back()) {
                continue;
            }
            if (macroblock_mode) {
                try {
                    if (idr.first_macroblock.mb_type != 0) {
                        throw std::invalid_argument(
                            "--macroblock currently supports I4x4 macroblocks only; encountered I16x16 syntax");
                    }
                    const auto macroblock = zkstego::decode_cavlc_luma_macroblock(
                    units.at(idr.nal_index).rbsp(),
                    idr.first_macroblock.residual_bit_offset,
                    idr.first_macroblock.coded_block_pattern & 0x0fU);
                auto residual_end = macroblock.next_bit_offset;
                if (selected_nal_index.has_value()) {
                    std::cout << "nal=" << idr.nal_index
                              << " luma_macroblock_end=" << residual_end << '\n';
                    for (std::size_t block_index = 0; block_index < macroblock.blocks.size(); ++block_index) {
                        const auto& block = macroblock.blocks[block_index];
                        std::cout << "nal=" << idr.nal_index
                                  << " luma_block=" << block_index
                                  << " tc=" << block.token.total_coefficients
                                  << " end=" << block.tail.next_bit_offset << '\n';
                    }
                }
                std::uint32_t cb_chroma_dc_tc = 0;
                std::uint32_t cr_chroma_dc_tc = 0;
                std::array<std::uint32_t, 8> chroma_ac_total_coefficients{};
                if (((idr.first_macroblock.coded_block_pattern >> 4U) & 0x03U) >= 1U) {
                    try {
                        const auto cb_chroma_dc = zkstego::decode_cavlc_chroma_dc_block(
                            units.at(idr.nal_index).rbsp(), residual_end);
                        const auto cr_chroma_dc = zkstego::decode_cavlc_chroma_dc_block(
                            units.at(idr.nal_index).rbsp(), cb_chroma_dc.tail.next_bit_offset);
                        cb_chroma_dc_tc = cb_chroma_dc.token.total_coefficients;
                        cr_chroma_dc_tc = cr_chroma_dc.token.total_coefficients;
                        residual_end = cr_chroma_dc.tail.next_bit_offset;
                        if (selected_nal_index.has_value()) {
                            std::cout << "nal=" << idr.nal_index
                                      << " chroma_dc_tc=" << cb_chroma_dc_tc << ',' << cr_chroma_dc_tc
                                      << " chroma_dc_end=" << residual_end << '\n';
                        }
                    } catch (const std::exception& error) {
                        throw std::invalid_argument(
                            "chroma DC at bit " + std::to_string(residual_end) + ": " + error.what());
                    }
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
                            zkstego::CavlcDecodedLumaBlock block;
                            try {
                                block = zkstego::decode_cavlc_chroma_ac_block(
                                    units.at(idr.nal_index).rbsp(), residual_end, n_c);
                            } catch (const std::exception& error) {
                                std::string prior_counts;
                                for (std::size_t prior = 0; prior < chroma_ac_total_coefficients.size(); ++prior) {
                                    if (prior != 0) prior_counts += ',';
                                    prior_counts += std::to_string(chroma_ac_total_coefficients[prior]);
                                }
                                const auto rbsp = units.at(idr.nal_index).rbsp();
                                std::string next_bits;
                                constexpr std::size_t kDiagnosticBits = 24;
                                const auto available_bits = rbsp.size() * 8U - residual_end;
                                const auto bit_count = std::min(kDiagnosticBits, available_bits);
                                next_bits.reserve(bit_count);
                                for (std::size_t bit_index = 0; bit_index < bit_count; ++bit_index) {
                                    const auto absolute_bit = residual_end + bit_index;
                                    const auto bit = static_cast<unsigned>(
                                        (rbsp[absolute_bit / 8U] >> (7U - absolute_bit % 8U)) & 1U);
                                    next_bits.push_back(bit == 0U ? '0' : '1');
                                }
                                throw std::invalid_argument(
                                    "chroma AC component " + std::to_string(component) +
                                    " block " + std::to_string(local_index) +
                                    " at bit " + std::to_string(residual_end) +
                                    " nC=" + std::to_string(n_c) +
                                    " priorTC=" + prior_counts +
                                    " nextBits=" + next_bits + ": " + error.what());
                            }
                            chroma_ac_total_coefficients[component * 4 + local_index] = block.token.total_coefficients;
                            residual_end = block.tail.next_bit_offset;
                            if (selected_nal_index.has_value()) {
                                std::cout << "nal=" << idr.nal_index
                                          << " chroma_ac_component=" << component
                                          << " block=" << local_index
                                          << " nC=" << n_c
                                          << " tc=" << block.token.total_coefficients
                                          << " end=" << residual_end << '\n';
                            }
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
                } catch (const std::exception& error) {
                    throw std::invalid_argument(
                        "CAVLC first-macroblock inspection failed at NAL " + std::to_string(idr.nal_index) +
                        ": " + error.what());
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
        if (selected_nal_index.has_value() && decoded_first_luma_macroblocks == 0 && macroblock_mode) {
            throw std::invalid_argument("selected NAL is not an inspectable IDR macroblock");
        }
    } catch (const std::exception& error) {
        std::cerr << "native IDR inspection failed: " << error.what() << '\n';
        return 1;
    }
    return 0;
}
