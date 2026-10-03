#pragma once

// Shared CLI file helpers. Arguments are carried as UTF-8 std::string on
// every platform; on Windows the tools enter through wmain and convert the
// UTF-16 command line, so paths such as "D:/.../Đồ Án/..." round-trip
// losslessly and are opened through std::filesystem::path / _wfopen_s.

#include "zkstego/cavlc_stream.hpp"

#include <cstdint>
#include <cstdio>
#include <cwchar>
#include <filesystem>
#include <fstream>
#include <stdexcept>
#include <string>
#include <vector>

#ifdef _WIN32
#ifndef NOMINMAX
#define NOMINMAX
#endif
#ifndef WIN32_LEAN_AND_MEAN
#define WIN32_LEAN_AND_MEAN
#endif
#include <windows.h>
#endif

namespace zkstego::cli {

inline std::filesystem::path utf8_path(const std::string& text) {
    const std::u8string utf8(reinterpret_cast<const char8_t*>(text.data()), text.size());
    return std::filesystem::path(utf8);
}

// Path handed to the OS. On Windows, absolute paths near MAX_PATH (260) fail in
// the classic Win32 APIs unless they use the extended-length "\\?\" form.
inline std::filesystem::path os_path(const std::string& text) {
    auto path = utf8_path(text);
#ifdef _WIN32
    constexpr std::size_t kClassicPathLimit = 240;
    const std::wstring raw = path.native();
    if (raw.size() < kClassicPathLimit || raw.rfind(L"\\\\?\\", 0) == 0) return path;
    path = std::filesystem::absolute(path).lexically_normal();
    path.make_preferred();
    const std::wstring absolute = path.native();
    if (absolute.rfind(L"\\\\", 0) == 0) return std::filesystem::path(L"\\\\?\\UNC\\" + absolute.substr(2));
    return std::filesystem::path(L"\\\\?\\" + absolute);
#else
    return path;
#endif
}

#ifdef _WIN32
inline std::string wide_to_utf8(const wchar_t* text) {
    const auto length = static_cast<int>(std::wcslen(text));
    if (length == 0) return {};
    const auto size = WideCharToMultiByte(CP_UTF8, WC_ERR_INVALID_CHARS, text, length, nullptr, 0, nullptr, nullptr);
    if (size <= 0) throw std::invalid_argument("command-line argument is not valid UTF-16");
    std::string output(static_cast<std::size_t>(size), '\0');
    if (WideCharToMultiByte(CP_UTF8, WC_ERR_INVALID_CHARS, text, length, output.data(), size, nullptr, nullptr) != size) {
        throw std::invalid_argument("command-line argument conversion failed");
    }
    return output;
}

inline std::vector<std::string> utf8_arguments(const int argc, wchar_t* argv[]) {
    std::vector<std::string> arguments;
    arguments.reserve(static_cast<std::size_t>(argc));
    for (int index = 0; index < argc; ++index) arguments.push_back(wide_to_utf8(argv[index]));
    return arguments;
}
#else
inline std::vector<std::string> utf8_arguments(const int argc, char* argv[]) {
    return {argv, argv + argc};
}
#endif

// Reads a whole file, refusing anything above maximum_bytes before allocating.
inline std::vector<std::uint8_t> read_binary_file(
    const std::string& path, const std::size_t maximum_bytes = kMaxAnnexBFileBytes) {
    std::ifstream input(os_path(path), std::ios::binary | std::ios::ate);
    if (!input) throw std::invalid_argument("cannot open input video");
    const auto end = input.tellg();
    if (end < 0) throw std::invalid_argument("cannot determine input video size");
    if (static_cast<std::uintmax_t>(end) > maximum_bytes) {
        throw std::invalid_argument("input video exceeds the configured size limit");
    }
    input.seekg(0, std::ios::beg);
    std::vector<std::uint8_t> bytes(static_cast<std::size_t>(end));
    if (!bytes.empty() &&
        !input.read(reinterpret_cast<char*>(bytes.data()), static_cast<std::streamsize>(bytes.size()))) {
        throw std::invalid_argument("failed while reading input video");
    }
    return bytes;
}

// Exclusively creates a new file ("x" mode) so an existing path is never
// overwritten, then writes all bytes.
inline void write_new_binary_file(const std::string& path, const std::vector<std::uint8_t>& bytes) {
    std::FILE* output = nullptr;
#ifdef _WIN32
    const auto native = os_path(path);
    if (_wfopen_s(&output, native.c_str(), L"wbx") != 0 || output == nullptr) {
        throw std::invalid_argument("cannot exclusively create output video");
    }
#else
    const auto native = os_path(path);
    output = std::fopen(path.c_str(), "wbx");
    if (output == nullptr) throw std::invalid_argument("cannot exclusively create output video");
#endif
    const auto written = std::fwrite(bytes.data(), 1U, bytes.size(), output);
    const auto closed = std::fclose(output);
    if (written != bytes.size() || closed != 0) {
        // Never leave a truncated video behind: this call created the file.
        std::error_code ignored;
        std::filesystem::remove(native, ignored);
        throw std::invalid_argument("failed while writing output video");
    }
}

}  // namespace zkstego::cli
