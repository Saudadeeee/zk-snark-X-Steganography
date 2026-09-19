#include "zkstego/live.hpp"

#include <cassert>
#include <cstdint>
#include <iostream>
#include <vector>

namespace {
std::vector<std::uint8_t> nal(std::uint8_t type, const char* payload) {
    std::vector<std::uint8_t> result{0, 0, 0, 1, static_cast<std::uint8_t>(0x60 | type)};
    while (*payload) result.push_back(static_cast<std::uint8_t>(*payload++));
    return result;
}

void append(std::vector<std::uint8_t>& target, const std::vector<std::uint8_t>& source) {
    target.insert(target.end(), source.begin(), source.end());
}
}  // namespace

int main() {
    std::vector<std::uint8_t> input;
    append(input, nal(7, "sps"));
    append(input, nal(8, "pps"));
    append(input, nal(5, "idr"));

    const std::vector<std::uint8_t> payload{0xCA, 0xFE, 0x01};
    const auto output = zkstego::inject_sei_before_idr(input, payload);
    assert(output.size() > input.size());
    assert(zkstego::count_nal_type(output, 6) == 1);
    assert(zkstego::count_nal_type(output, 5) == 1);
    assert(zkstego::inject_sei_before_idr(input, {}).size() == input.size());
    std::cout << "native edge relay: 4/4 passed\n";
}
