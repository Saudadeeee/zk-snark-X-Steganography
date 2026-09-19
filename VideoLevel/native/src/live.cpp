#include "zkstego/live.hpp"

#include <array>
#include <optional>

namespace zkstego {
namespace {

struct StartCode {
    std::size_t offset;
    std::size_t length;
};

std::optional<StartCode> find_start_code(const std::vector<std::uint8_t>& bytes, std::size_t from) {
    for (std::size_t i = from; i + 3 <= bytes.size(); ++i) {
        if (i + 4 <= bytes.size() && bytes[i] == 0 && bytes[i + 1] == 0 &&
            bytes[i + 2] == 0 && bytes[i + 3] == 1) {
            return StartCode{i, 4};
        }
        if (bytes[i] == 0 && bytes[i + 1] == 0 && bytes[i + 2] == 1 &&
            (i == 0 || bytes[i - 1] != 0)) {
            return StartCode{i, 3};
        }
    }
    return std::nullopt;
}

void append_sei_length(std::vector<std::uint8_t>& output, std::size_t value) {
    while (value >= 255) {
        output.push_back(255);
        value -= 255;
    }
    output.push_back(static_cast<std::uint8_t>(value));
}

std::vector<std::uint8_t> make_user_data_sei(const std::vector<std::uint8_t>& payload) {
    // UUID identifies this as ZKStego edge metadata, not generic encoder data.
    constexpr std::array<std::uint8_t, 16> uuid{
        0x5A, 0x4B, 0x53, 0x54, 0x45, 0x47, 0x4F, 0x2D,
        0x45, 0x44, 0x47, 0x45, 0x2D, 0x30, 0x30, 0x31,
    };
    std::vector<std::uint8_t> sei{0, 0, 0, 1, 0x06};
    append_sei_length(sei, 5);  // user_data_unregistered
    append_sei_length(sei, uuid.size() + payload.size());
    sei.insert(sei.end(), uuid.begin(), uuid.end());
    sei.insert(sei.end(), payload.begin(), payload.end());
    sei.push_back(0x80);  // rbsp_trailing_bits
    return sei;
}

}  // namespace

std::size_t count_nal_type(const std::vector<std::uint8_t>& annex_b, std::uint8_t nal_type) {
    std::size_t count = 0;
    for (std::size_t cursor = 0; ; ) {
        const auto start = find_start_code(annex_b, cursor);
        if (!start || start->offset + start->length >= annex_b.size()) break;
        if ((annex_b[start->offset + start->length] & 0x1F) == nal_type) ++count;
        cursor = start->offset + start->length;
    }
    return count;
}

std::vector<std::uint8_t> inject_sei_before_idr(
    const std::vector<std::uint8_t>& annex_b,
    const std::vector<std::uint8_t>& payload) {
    if (payload.empty()) return annex_b;
    for (std::size_t cursor = 0; ; ) {
        const auto start = find_start_code(annex_b, cursor);
        if (!start || start->offset + start->length >= annex_b.size()) break;
        if ((annex_b[start->offset + start->length] & 0x1F) == 5) {
            const auto sei = make_user_data_sei(payload);
            std::vector<std::uint8_t> result;
            result.reserve(annex_b.size() + sei.size());
            result.insert(result.end(), annex_b.begin(), annex_b.begin() + static_cast<std::ptrdiff_t>(start->offset));
            result.insert(result.end(), sei.begin(), sei.end());
            result.insert(result.end(), annex_b.begin() + static_cast<std::ptrdiff_t>(start->offset), annex_b.end());
            return result;
        }
        cursor = start->offset + start->length;
    }
    return annex_b;
}

}  // namespace zkstego
