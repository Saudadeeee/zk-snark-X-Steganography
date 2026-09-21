#include "zkstego/cavlc_stream.hpp"

#include <stdexcept>

namespace zkstego {

namespace {

std::size_t start_code_length_at(const std::vector<std::uint8_t>& bytes, std::size_t offset) {
    if (offset + 3 <= bytes.size() && bytes[offset] == 0 && bytes[offset + 1] == 0 && bytes[offset + 2] == 1) {
        return 3;
    }
    if (offset + 4 <= bytes.size() && bytes[offset] == 0 && bytes[offset + 1] == 0 &&
        bytes[offset + 2] == 0 && bytes[offset + 3] == 1) {
        return 4;
    }
    return 0;
}

}  // namespace

H264BaselineSps parse_baseline_sps(const std::vector<std::uint8_t>& rbsp) {
    RbspBitReader reader(rbsp);
    H264BaselineSps sps;
    sps.profile_idc = static_cast<std::uint8_t>(reader.read_bits(8));
    static_cast<void>(reader.read_bits(8));  // constraint flags and reserved bits
    sps.level_idc = static_cast<std::uint8_t>(reader.read_bits(8));
    sps.sequence_parameter_set_id = reader.read_ue();
    if (sps.profile_idc != 66 && sps.profile_idc != 77 && sps.profile_idc != 88) {
        throw std::invalid_argument("native SPS parser currently supports CAVLC baseline/main profiles only");
    }
    sps.log2_max_frame_num_minus4 = reader.read_ue();
    sps.pic_order_cnt_type = reader.read_ue();
    if (sps.pic_order_cnt_type == 0) {
        sps.log2_max_pic_order_cnt_lsb_minus4 = reader.read_ue();
    } else if (sps.pic_order_cnt_type == 1) {
        throw std::invalid_argument("native SPS parser does not yet support pic_order_cnt_type 1");
    } else if (sps.pic_order_cnt_type != 2) {
        throw std::invalid_argument("invalid SPS pic_order_cnt_type");
    }
    static_cast<void>(reader.read_ue());  // max_num_ref_frames
    static_cast<void>(reader.read_bit());  // gaps_in_frame_num_value_allowed_flag
    sps.pic_width_in_mbs_minus1 = reader.read_ue();
    sps.pic_height_in_map_units_minus1 = reader.read_ue();
    sps.frame_mbs_only_flag = reader.read_bit() != 0;
    return sps;
}

H264BaselinePps parse_baseline_pps(const std::vector<std::uint8_t>& rbsp) {
    RbspBitReader reader(rbsp);
    H264BaselinePps pps;
    pps.pic_parameter_set_id = reader.read_ue();
    pps.sequence_parameter_set_id = reader.read_ue();
    pps.entropy_coding_mode_flag = reader.read_bit() != 0;
    if (pps.entropy_coding_mode_flag) {
        throw std::invalid_argument("native CAVLC path rejects CABAC PPS");
    }
    static_cast<void>(reader.read_bit());  // bottom_field_pic_order_in_frame_present_flag
    pps.num_slice_groups_minus1 = reader.read_ue();
    if (pps.num_slice_groups_minus1 != 0) {
        throw std::invalid_argument("native CAVLC path does not support PPS slice groups");
    }
    pps.num_ref_idx_l0_default_active_minus1 = reader.read_ue();
    pps.num_ref_idx_l1_default_active_minus1 = reader.read_ue();
    static_cast<void>(reader.read_bit());  // weighted_pred_flag
    static_cast<void>(reader.read_bits(2));  // weighted_bipred_idc
    pps.pic_init_qp_minus26 = reader.read_se();
    static_cast<void>(reader.read_se());  // pic_init_qs_minus26
    static_cast<void>(reader.read_se());  // chroma_qp_index_offset
    pps.deblocking_filter_control_present_flag = reader.read_bit() != 0;
    static_cast<void>(reader.read_bit());  // constrained_intra_pred_flag
    pps.redundant_pic_cnt_present_flag = reader.read_bit() != 0;
    return pps;
}

H264BaselineIdrSliceHeader parse_baseline_idr_slice_header(
    const std::vector<std::uint8_t>& rbsp,
    const H264BaselineSps& sps,
    const H264BaselinePps& pps) {
    if (!sps.frame_mbs_only_flag || pps.entropy_coding_mode_flag || pps.num_slice_groups_minus1 != 0) {
        throw std::invalid_argument("native IDR parser requires frame-only CAVLC without slice groups");
    }
    if (sps.pic_order_cnt_type != 2) {
        throw std::invalid_argument("native IDR parser currently requires pic_order_cnt_type 2");
    }
    RbspBitReader reader(rbsp);
    H264BaselineIdrSliceHeader header;
    header.first_mb_in_slice = reader.read_ue();
    header.slice_type = reader.read_ue();
    if (header.slice_type > 4) {
        header.slice_type -= 5;
    }
    header.pic_parameter_set_id = reader.read_ue();
    header.frame_num = reader.read_bits(static_cast<std::size_t>(sps.log2_max_frame_num_minus4) + 4);
    header.idr_pic_id = reader.read_ue();
    if (pps.redundant_pic_cnt_present_flag) {
        static_cast<void>(reader.read_ue());
    }
    const auto slice_type_modulo = header.slice_type % 5;
    if (slice_type_modulo != 2 && slice_type_modulo != 4) {
        throw std::invalid_argument("native IDR parser currently supports I and SI slices only");
    }
    static_cast<void>(reader.read_bit());  // no_output_of_prior_pics_flag
    static_cast<void>(reader.read_bit());  // long_term_reference_flag
    header.slice_qp_delta = reader.read_se();
    if (pps.deblocking_filter_control_present_flag) {
        const auto disable_deblocking_filter_idc = reader.read_ue();
        if (disable_deblocking_filter_idc != 1) {
            static_cast<void>(reader.read_se());
            static_cast<void>(reader.read_se());
        }
    }
    header.data_bit_offset = reader.position();
    return header;
}

std::vector<std::uint8_t> ebsp_to_rbsp(const std::vector<std::uint8_t>& ebsp) {
    std::vector<std::uint8_t> rbsp;
    rbsp.reserve(ebsp.size());
    std::size_t zeros = 0;
    for (std::size_t index = 0; index < ebsp.size(); ++index) {
        const auto byte = ebsp[index];
        if (zeros >= 2 && byte == 0x03 && index + 1 < ebsp.size() && ebsp[index + 1] <= 0x03) {
            zeros = 0;
            continue;
        }
        rbsp.push_back(byte);
        zeros = byte == 0 ? zeros + 1 : 0;
    }
    return rbsp;
}

std::vector<std::uint8_t> rbsp_to_ebsp(const std::vector<std::uint8_t>& rbsp) {
    std::vector<std::uint8_t> ebsp;
    ebsp.reserve(rbsp.size() + rbsp.size() / 64);
    std::size_t zeros = 0;
    for (const auto byte : rbsp) {
        if (zeros >= 2 && byte <= 0x03) {
            ebsp.push_back(0x03);
            zeros = 0;
        }
        ebsp.push_back(byte);
        zeros = byte == 0 ? zeros + 1 : 0;
    }
    return ebsp;
}

std::vector<std::uint8_t> AnnexBNalUnit::rbsp() const {
    return ebsp_to_rbsp(payload);
}

std::vector<AnnexBNalUnit> split_annex_b(const std::vector<std::uint8_t>& annex_b) {
    std::vector<AnnexBNalUnit> units;
    std::size_t cursor = 0;
    while (cursor < annex_b.size()) {
        const auto marker_length = start_code_length_at(annex_b, cursor);
        if (marker_length == 0) {
            ++cursor;
            continue;
        }
        const auto start = cursor;
        const auto header_offset = cursor + marker_length;
        if (header_offset >= annex_b.size()) break;
        cursor = header_offset + 1;
        while (cursor < annex_b.size() && start_code_length_at(annex_b, cursor) == 0) ++cursor;

        const auto header = annex_b[header_offset];
        AnnexBNalUnit unit;
        unit.start_offset = start;
        unit.start_code_size = marker_length;
        unit.forbidden_zero_bit = static_cast<std::uint8_t>((header >> 7) & 0x01);
        unit.nal_ref_idc = static_cast<std::uint8_t>((header >> 5) & 0x03);
        unit.nal_unit_type = static_cast<std::uint8_t>(header & 0x1f);
        unit.payload.assign(annex_b.begin() + static_cast<std::ptrdiff_t>(header_offset + 1),
                            annex_b.begin() + static_cast<std::ptrdiff_t>(cursor));
        units.push_back(std::move(unit));
    }
    return units;
}

std::vector<std::uint8_t> assemble_annex_b(const std::vector<AnnexBNalUnit>& units) {
    std::size_t total_size = 0;
    for (const auto& unit : units) {
        if (unit.start_code_size != 3 && unit.start_code_size != 4) {
            throw std::invalid_argument("Annex-B NAL start code must be three or four bytes");
        }
        if (unit.forbidden_zero_bit > 1 || unit.nal_ref_idc > 3 || unit.nal_unit_type > 31) {
            throw std::invalid_argument("Annex-B NAL header fields are out of range");
        }
        total_size += unit.start_code_size + 1 + unit.payload.size();
    }

    std::vector<std::uint8_t> annex_b;
    annex_b.reserve(total_size);
    for (const auto& unit : units) {
        annex_b.insert(annex_b.end(), unit.start_code_size - 1, 0x00);
        annex_b.push_back(0x01);
        const auto header = static_cast<std::uint8_t>(
            (unit.forbidden_zero_bit << 7) | (unit.nal_ref_idc << 5) | unit.nal_unit_type);
        annex_b.push_back(header);
        annex_b.insert(annex_b.end(), unit.payload.begin(), unit.payload.end());
    }
    return annex_b;
}

std::vector<std::uint8_t> apply_fixed_length_patches(
    const std::vector<std::uint8_t>& source,
    const std::vector<FixedLengthBitPatch>& patches) {
    auto output = source;
    const auto total_bits = output.size() * 8;
    for (const auto& patch : patches) {
        if (patch.bit_offset > total_bits || patch.bits.size() > total_bits - patch.bit_offset) {
            throw std::out_of_range("CAVLC bit patch is outside RBSP bounds");
        }
        for (std::size_t index = 0; index < patch.bits.size(); ++index) {
            if (patch.bits[index] > 1) throw std::invalid_argument("CAVLC patch bits must be zero or one");
            const auto absolute = patch.bit_offset + index;
            const auto byte_index = absolute / 8;
            const auto mask = static_cast<std::uint8_t>(1U << (7 - (absolute % 8)));
            if (patch.bits[index]) output[byte_index] |= mask;
            else output[byte_index] &= static_cast<std::uint8_t>(~mask);
        }
    }
    return output;
}

std::vector<std::uint8_t> patch_annex_b_nal_rbsp(
    const std::vector<std::uint8_t>& annex_b,
    const std::size_t nal_index,
    const std::vector<FixedLengthBitPatch>& patches) {
    auto units = split_annex_b(annex_b);
    if (nal_index >= units.size()) {
        throw std::out_of_range("Annex-B NAL index is outside the segment");
    }
    auto rbsp = units[nal_index].rbsp();
    rbsp = apply_fixed_length_patches(rbsp, patches);
    units[nal_index].payload = rbsp_to_ebsp(rbsp);
    return assemble_annex_b(units);
}

std::vector<std::uint8_t> patch_annex_b_rbsp_plan(
    const std::vector<std::uint8_t>& annex_b,
    const std::vector<AnnexBRbspPatchPlan>& plan) {
    auto units = split_annex_b(annex_b);
    std::vector<bool> touched(units.size(), false);
    for (const auto& entry : plan) {
        if (entry.nal_index >= units.size()) {
            throw std::out_of_range("Annex-B patch plan NAL index is outside the segment");
        }
        auto rbsp = touched[entry.nal_index]
            ? ebsp_to_rbsp(units[entry.nal_index].payload)
            : units[entry.nal_index].rbsp();
        units[entry.nal_index].payload = rbsp_to_ebsp(apply_fixed_length_patches(rbsp, entry.patches));
        touched[entry.nal_index] = true;
    }
    return assemble_annex_b(units);
}

}  // namespace zkstego
