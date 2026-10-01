#include "lwe/snark/r1cs_lattice_snark.hpp"
#include "lwe/tests/circ_lattice_params.hpp"
#include "lwe/tests/common.hpp"
#include <libsnark/gadgetlib1/gadgets/basic_gadgets.hpp>
#include <libsnark/gadgetlib1/protoboard.hpp>

#include <array>
#include <algorithm>
#include <cstdint>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <memory>
#include <stdexcept>
#include <string>
#include <system_error>
#include <vector>

namespace {

using namespace libsnark;
using ParameterSet = LWE::B19C20;
using ProofField = libff::Fr<Fp2_b19_pp>;
using RingParameters = Ring2_common_pp<ParameterSet::q_int>;
using Proof = r1cs_lattice_snark_proof<
    Fp2_b19_pp, RingParameters, ParameterSet>;

constexpr std::uint64_t kCommitmentModulus = (1u << 19) - 1;
constexpr std::size_t kCommitmentModulusBits = 19;
constexpr std::size_t kCommitmentRows = 128;
constexpr auto kCoefficientBoundExclusive =
    ParameterSet::rescale_q + ParameterSet::p_int + 1;
static_assert(kCoefficientBoundExclusive <= (__uint128_t(1) << 41),
              "B19C20 response coefficient bound must fit in 41 bits");
constexpr std::size_t kResponseCoefficientBits = 41;
constexpr std::size_t kResponseCoefficientCount =
    (ParameterSet::n + ParameterSet::pt_dim + ParameterSet::tau) * 2;
constexpr std::size_t kResponseBitCount =
    kResponseCoefficientBits * kResponseCoefficientCount;
constexpr std::size_t kResponseByteCount = (kResponseBitCount + 7) / 8;
constexpr std::size_t kContextBytes = 32;
constexpr std::size_t kPayloadBytes = 32;
constexpr std::size_t kPayloadBits = kPayloadBytes * 8;
constexpr std::size_t kBitsPerByte = 8;
constexpr std::size_t kContextBits = kContextBytes * kBitsPerByte;
constexpr std::size_t kMessageBits = kPayloadBits + kContextBits;
constexpr std::size_t kOpeningBits =
    kCommitmentRows * (kCommitmentModulusBits + 3);
constexpr std::size_t kOpeningBytes = (kOpeningBits + kBitsPerByte - 1) / kBitsPerByte;

struct Circuit {
    protoboard<ProofField> board;
    std::array<pb_variable<ProofField>, kContextBytes> context{};
    std::array<pb_variable<ProofField>, kContextBytes * 8> context_bits{};
    std::array<pb_variable<ProofField>, kCommitmentRows> commitment{};
    std::array<pb_variable<ProofField>, kPayloadBytes> payload_bytes{};
    std::array<pb_variable<ProofField>, kPayloadBits> payload_bits{};
    std::array<pb_variable<ProofField>, kOpeningBits> opening_bits{};
};

struct KtxCommitmentKey {
    std::vector<std::uint64_t> message_matrix;
    std::vector<std::uint64_t> randomness_matrix;
};

KtxCommitmentKey generate_ktx_commitment_key(
    LWERandomness::PseudoRandomGenerator &prg) {
    KtxCommitmentKey key{
        std::vector<std::uint64_t>(kCommitmentRows * kMessageBits),
        std::vector<std::uint64_t>(kCommitmentRows * kOpeningBits)};
    for (auto &coefficient : key.message_matrix) {
        coefficient = static_cast<std::uint64_t>(prg.bounded(kCommitmentModulus));
    }
    for (auto &coefficient : key.randomness_matrix) {
        coefficient = static_cast<std::uint64_t>(prg.bounded(kCommitmentModulus));
    }
    return key;
}

std::vector<std::uint8_t> serialize_response(const Proof &proof) {
    std::vector<std::uint8_t> bytes(kResponseByteCount, 0);
    std::size_t bit_position = 0;
    const auto append = [&](const auto &coefficient) {
        const auto value = coefficient.value;
        if (value >= kCoefficientBoundExclusive) {
            return false;
        }
        for (std::size_t bit = 0; bit < kResponseCoefficientBits; ++bit) {
            if (((value >> bit) & 1u) != 0) {
                bytes[bit_position / 8] |= static_cast<std::uint8_t>(
                    1u << (bit_position % 8));
            }
            ++bit_position;
        }
        return true;
    };
    for (const auto &element : proof.response.a_vec.vec) {
        if (!append(element.c0) || !append(element.c1)) {
            return {};
        }
    }
    for (const auto &element : proof.response.c_vec.vec) {
        if (!append(element.c0) || !append(element.c1)) {
            return {};
        }
    }
    if (bit_position != kResponseBitCount) {
        return {};
    }
    return bytes;
}

bool deserialize_response(const std::vector<std::uint8_t> &bytes, Proof &proof) {
    if (bytes.size() != kResponseByteCount) {
        return false;
    }
    const auto used_bits_in_last_byte = kResponseBitCount % 8;
    if (used_bits_in_last_byte != 0 &&
        (bytes.back() >> used_bits_in_last_byte) != 0) {
        return false;
    }

    Proof decoded;
    std::size_t bit_position = 0;
    const auto read = [&](auto &coefficient) {
        __uint128_t value = 0;
        for (std::size_t bit = 0; bit < kResponseCoefficientBits; ++bit) {
            const auto set =
                (bytes[bit_position / 8] >> (bit_position % 8)) & 1u;
            if (set != 0) {
                value |= (__uint128_t(1) << bit);
            }
            ++bit_position;
        }
        if (value >= kCoefficientBoundExclusive) {
            return false;
        }
        coefficient.value = value;
        return true;
    };
    for (auto &element : decoded.response.a_vec.vec) {
        if (!read(element.c0) || !read(element.c1)) {
            return false;
        }
    }
    for (auto &element : decoded.response.c_vec.vec) {
        if (!read(element.c0) || !read(element.c1)) {
            return false;
        }
    }
    if (bit_position != kResponseBitCount) {
        return false;
    }
    proof = decoded;
    return true;
}

template <typename UInt>
bool write_little_endian(std::ostream &output, UInt value, std::size_t width) {
    for (std::size_t i = 0; i < width; ++i) {
        const auto byte = static_cast<std::uint8_t>(value & 0xffu);
        output.put(static_cast<char>(byte));
        if (!output) {
            return false;
        }
        value >>= 8;
    }
    return value == 0;
}

template <typename UInt>
bool read_little_endian(std::istream &input, UInt &value, std::size_t width) {
    value = 0;
    for (std::size_t i = 0; i < width; ++i) {
        const auto next = input.get();
        if (next == std::char_traits<char>::eof()) {
            return false;
        }
        value |= static_cast<UInt>(static_cast<std::uint8_t>(next)) << (8 * i);
    }
    return true;
}

bool write_proof_field(std::ostream &output, const ProofField &value) {
    return write_little_endian(
               output, value.c0.value % ParameterSet::p_int, sizeof(std::uint64_t)) &&
           write_little_endian(
               output, value.c1.value % ParameterSet::p_int, sizeof(std::uint64_t));
}

bool read_proof_field(std::istream &input, ProofField &value) {
    std::uint64_t c0 = 0;
    std::uint64_t c1 = 0;
    if (!read_little_endian(input, c0, sizeof(c0)) ||
        !read_little_endian(input, c1, sizeof(c1)) ||
        c0 >= ParameterSet::p_int || c1 >= ParameterSet::p_int) {
        return false;
    }
    value.c0.value = c0;
    value.c1.value = c1;
    return true;
}

constexpr std::size_t kVerificationPrefixSize =
    kContextBytes + kCommitmentRows + 1;
constexpr std::size_t kVerifierKeySRows = ParameterSet::pt_dim + ParameterSet::tau;
constexpr std::size_t kVerifierKeyTRows = ParameterSet::tau;

bool write_verifier_key(
    const std::string &path,
    const r1cs_lattice_snark_verification_key<
        Fp2_b19_pp, RingParameters, ParameterSet> &key) {
    std::ofstream output(path, std::ios::binary | std::ios::trunc);
    constexpr char magic[] = "ISWVK001";
    if (!output) {
        return false;
    }
    std::error_code initial_permission_error;
    std::filesystem::permissions(
        path,
        std::filesystem::perms::owner_read | std::filesystem::perms::owner_write,
        std::filesystem::perm_options::replace,
        initial_permission_error);
    if (initial_permission_error || !output.write(magic, sizeof(magic) - 1) ||
        !write_little_endian(output, static_cast<std::uint32_t>(ParameterSet::n), 4) ||
        !write_little_endian(output, static_cast<std::uint32_t>(kVerifierKeySRows), 4) ||
        !write_little_endian(output, static_cast<std::uint32_t>(kVerifierKeyTRows), 4) ||
        !write_little_endian(output, static_cast<std::uint32_t>(ParameterSet::pt_dim), 4) ||
        !write_little_endian(output, static_cast<std::uint32_t>(ParameterSet::query_num), 4) ||
        !write_little_endian(output, static_cast<std::uint32_t>(kVerificationPrefixSize), 4)) {
        return false;
    }

    for (const auto &row : key.sk.S_T.mat) {
        for (const auto &element : row) {
            const auto write_ring = [&](const auto &component) {
                // Preserve the upstream uint128 storage exactly: its Gaussian
                // samples may use two's-complement encodings and Ring operators
                // do not normalize after every intermediate operation.
                return write_little_endian(output, component.value, 16);
            };
            if (!write_ring(element.c0) || !write_ring(element.c1)) {
                return false;
            }
        }
    }
    for (const auto &row : key.sk.T_mat.mat) {
        for (const auto &element : row) {
            if (!write_proof_field(output, element)) {
                return false;
            }
        }
    }

    const auto write_prefixes = [&output](
        const std::vector<libff::Fr_vector<Fp2_b19_pp>> &prefixes) {
        if (prefixes.size() != ParameterSet::query_num) {
            std::cerr << "unexpected verifier-key prefix count=" << prefixes.size()
                      << '\n';
            return false;
        }
        for (const auto &prefix : prefixes) {
            if (prefix.size() != kVerificationPrefixSize) {
                std::cerr << "unexpected verifier-key prefix length="
                          << prefix.size() << " expected="
                          << kVerificationPrefixSize << '\n';
                return false;
            }
            for (const auto &element : prefix) {
                if (!write_proof_field(output, element)) {
                    return false;
                }
            }
        }
        return true;
    };
    if (!write_prefixes(key.A_prefix) || !write_prefixes(key.B_prefix) ||
        !write_prefixes(key.C_prefix) || key.Z_s.size() != ParameterSet::query_num) {
        return false;
    }
    for (const auto &element : key.Z_s) {
        if (!write_proof_field(output, element)) {
            return false;
        }
    }
    output.flush();
    if (!output) {
        return false;
    }
    output.close();
    std::error_code permission_error;
    std::filesystem::permissions(
        path,
        std::filesystem::perms::owner_read | std::filesystem::perms::owner_write,
        std::filesystem::perm_options::replace,
        permission_error);
    return !permission_error;
}

bool read_verifier_key(
    const std::string &path,
    r1cs_lattice_snark_verification_key<
        Fp2_b19_pp, RingParameters, ParameterSet> &key) {
    std::ifstream input(path, std::ios::binary);
    constexpr char expected_magic[] = "ISWVK001";
    char magic[sizeof(expected_magic) - 1]{};
    std::array<std::uint32_t, 6> dimensions{};
    if (!input || !input.read(magic, sizeof(magic)) ||
        !std::equal(std::begin(magic), std::end(magic), std::begin(expected_magic))) {
        return false;
    }
    for (auto &dimension : dimensions) {
        if (!read_little_endian(input, dimension, sizeof(dimension))) {
            return false;
        }
    }
    const std::array<std::uint32_t, 6> expected_dimensions = {
        static_cast<std::uint32_t>(ParameterSet::n),
        static_cast<std::uint32_t>(kVerifierKeySRows),
        static_cast<std::uint32_t>(kVerifierKeyTRows),
        static_cast<std::uint32_t>(ParameterSet::pt_dim),
        static_cast<std::uint32_t>(ParameterSet::query_num),
        static_cast<std::uint32_t>(kVerificationPrefixSize)};
    if (dimensions != expected_dimensions) {
        return false;
    }

    for (auto &row : key.sk.S_T.mat) {
        for (auto &element : row) {
            const auto read_ring = [&input](auto &component) {
                __uint128_t value = 0;
                if (!read_little_endian(input, value, 16)) {
                    return false;
                }
                component.value = value;
                return true;
            };
            if (!read_ring(element.c0) || !read_ring(element.c1)) {
                return false;
            }
        }
    }
    for (auto &row : key.sk.T_mat.mat) {
        for (auto &element : row) {
            if (!read_proof_field(input, element)) {
                return false;
            }
        }
    }

    const auto read_prefixes = [&input](
        std::vector<libff::Fr_vector<Fp2_b19_pp>> &prefixes) {
        prefixes.resize(ParameterSet::query_num);
        for (auto &prefix : prefixes) {
            prefix.resize(kVerificationPrefixSize);
            for (auto &element : prefix) {
                if (!read_proof_field(input, element)) {
                    return false;
                }
            }
        }
        return true;
    };
    if (!read_prefixes(key.A_prefix) || !read_prefixes(key.B_prefix) ||
        !read_prefixes(key.C_prefix)) {
        return false;
    }
    key.Z_s.resize(ParameterSet::query_num);
    for (auto &element : key.Z_s) {
        if (!read_proof_field(input, element)) {
            return false;
        }
    }
    return input.peek() == std::char_traits<char>::eof();
}

bool write_extracted_proof(
    const std::string &path,
    const libff::Fr_vector<Fp2_b19_pp> &statement,
    const std::vector<std::uint8_t> &response) {
    if (statement.size() != kContextBytes + kCommitmentRows ||
        response.size() != kResponseByteCount) {
        return false;
    }
    std::ofstream output(path, std::ios::binary | std::ios::trunc);
    constexpr char magic[] = "ISWPF001";
    if (!output || !output.write(magic, sizeof(magic) - 1) ||
        !write_little_endian(output, static_cast<std::uint32_t>(statement.size()), 4)) {
        return false;
    }
    for (const auto &element : statement) {
        if (!write_proof_field(output, element)) {
            return false;
        }
    }
    if (!write_little_endian(output, static_cast<std::uint32_t>(response.size()), 4) ||
        !output.write(reinterpret_cast<const char *>(response.data()),
                      static_cast<std::streamsize>(response.size()))) {
        return false;
    }
    output.flush();
    return static_cast<bool>(output);
}

bool parse_context_hex(
    const std::string &hex,
    std::array<std::uint8_t, kContextBytes> &context) {
    if (hex.size() != 2 * context.size()) {
        return false;
    }
    const auto hex_digit = [](char character) -> int {
        if (character >= '0' && character <= '9') {
            return character - '0';
        }
        if (character >= 'a' && character <= 'f') {
            return character - 'a' + 10;
        }
        if (character >= 'A' && character <= 'F') {
            return character - 'A' + 10;
        }
        return -1;
    };
    for (std::size_t i = 0; i < context.size(); ++i) {
        const int high = hex_digit(hex[2 * i]);
        const int low = hex_digit(hex[2 * i + 1]);
        if (high < 0 || low < 0) {
            return false;
        }
        context[i] = static_cast<std::uint8_t>((high << 4) | low);
    }
    return true;
}

bool verify_extracted_proof(
    const std::string &proof_path,
    const std::string &key_path,
    const std::array<std::uint8_t, kContextBytes> &expected_context) {
    r1cs_lattice_snark_verification_key<
        Fp2_b19_pp, RingParameters, ParameterSet> verification_key;
    if (!read_verifier_key(key_path, verification_key)) {
        std::cerr << "invalid, truncated, or incompatible verifier-key file\n";
        return false;
    }
    std::ifstream input(proof_path, std::ios::binary);
    constexpr char expected_magic[] = "ISWPF001";
    char magic[sizeof(expected_magic) - 1]{};
    std::uint32_t statement_size = 0;
    if (!input || !input.read(magic, sizeof(magic)) ||
        !std::equal(std::begin(magic), std::end(magic), std::begin(expected_magic)) ||
        !read_little_endian(input, statement_size, sizeof(statement_size)) ||
        statement_size != kContextBytes + kCommitmentRows) {
        std::cerr << "invalid or incompatible proof envelope\n";
        return false;
    }
    libff::Fr_vector<Fp2_b19_pp> statement(statement_size);
    for (auto &element : statement) {
        if (!read_proof_field(input, element)) {
            std::cerr << "invalid public-input encoding\n";
            return false;
        }
    }
    for (std::size_t i = 0; i < expected_context.size(); ++i) {
        if (statement[i] != ProofField(expected_context[i])) {
            std::cerr << "proof context does not match verifier session\n";
            return false;
        }
    }
    std::uint32_t response_size = 0;
    if (!read_little_endian(input, response_size, sizeof(response_size)) ||
        response_size != kResponseByteCount) {
        std::cerr << "invalid response length\n";
        return false;
    }
    std::vector<std::uint8_t> encoded_response(response_size);
    if (!input.read(reinterpret_cast<char *>(encoded_response.data()),
                    static_cast<std::streamsize>(encoded_response.size())) ||
        input.peek() != std::char_traits<char>::eof()) {
        std::cerr << "truncated proof envelope or trailing data\n";
        return false;
    }
    Proof proof;
    if (!deserialize_response(encoded_response, proof)) {
        std::cerr << "invalid proof response encoding\n";
        return false;
    }
    try {
        if (!r1cs_lattice_snark_verify<Fp2_b19_pp, RingParameters>(
                verification_key, statement, proof)) {
            std::cerr << "proof verification rejected\n";
            return false;
        }
    } catch (const std::exception &error) {
        std::cerr << "proof verification rejected malformed input: "
                  << error.what() << '\n';
        return false;
    }
    std::cout << "SEPARATE_PROCESS_LATTICE_VERIFY=PASS\n";
    return true;
}

std::array<std::uint64_t, kCommitmentRows> commitment_for(
    const KtxCommitmentKey &key,
    const std::array<std::uint8_t, kContextBytes> &context,
    const std::array<std::uint8_t, kPayloadBytes> &payload,
    const std::array<std::uint8_t, kOpeningBytes> &opening) {
    std::array<std::uint64_t, kCommitmentRows> result{};
    for (std::size_t row = 0; row < kCommitmentRows; ++row) {
        std::uint64_t accumulator = 0;
        for (std::size_t i = 0; i < kPayloadBits; ++i) {
            if ((payload[i / kBitsPerByte] >> (i % kBitsPerByte)) & 1u) {
                accumulator += key.message_matrix[row * kMessageBits + i];
            }
        }
        for (std::size_t i = 0; i < kContextBits; ++i) {
            if ((context[i / kBitsPerByte] >> (i % kBitsPerByte)) & 1u) {
                accumulator += key.message_matrix[
                    row * kMessageBits + kPayloadBits + i];
            }
        }
        for (std::size_t i = 0; i < kOpeningBits; ++i) {
            if ((opening[i / kBitsPerByte] >> (i % kBitsPerByte)) & 1u) {
                accumulator += key.randomness_matrix[
                    row * kOpeningBits + i];
            }
        }
        result[row] = accumulator % kCommitmentModulus;
    }
    return result;
}

template <std::size_t N>
void bind_packed_bits(
    protoboard<ProofField> &board,
    const std::array<pb_variable<ProofField>, N> &bits,
    const pb_variable<ProofField> &packed,
    const std::string &label) {
    pb_linear_combination<ProofField> packed_lc;
    for (std::size_t i = 0; i < N; ++i) {
        generate_boolean_r1cs_constraint<ProofField>(board, bits[i], label + " bit");
        packed_lc.add_term(bits[i], static_cast<integer_coeff_t>(1u << i));
    }
    board.add_r1cs_constraint(r1cs_constraint<ProofField>(
        1, packed_lc, packed));
}

template <typename BitArray>
void assign_bits(
    protoboard<ProofField> &board,
    const BitArray &bits,
    std::uint64_t value) {
    for (std::size_t i = 0; i < bits.size(); ++i) {
        board.val(bits[i]) = ProofField((value >> i) & 1u);
    }
}

Circuit make_circuit(
    const KtxCommitmentKey &key,
    const std::array<std::uint8_t, kContextBytes> &context,
    const std::array<std::uint8_t, kPayloadBytes> &payload,
    const std::array<std::uint8_t, kOpeningBytes> &opening) {
    Circuit circuit;
    auto &pb = circuit.board;

    // Public instance: the context bytes and KTX commitment vector.
    for (std::size_t i = 0; i < circuit.context.size(); ++i) {
        circuit.context[i].allocate(pb, "public context byte");
        pb.val(circuit.context[i]) = ProofField(context[i]);
    }
    const auto expected_commitment = commitment_for(key, context, payload, opening);
    for (std::size_t row = 0; row < kCommitmentRows; ++row) {
        circuit.commitment[row].allocate(pb, "public commitment coordinate");
        pb.val(circuit.commitment[row]) = ProofField(expected_commitment[row]);
    }
    pb.set_input_sizes(kContextBytes + kCommitmentRows);

    for (auto &payload_byte : circuit.payload_bytes) {
        payload_byte.allocate(pb, "private payload byte");
    }
    for (std::size_t i = 0; i < circuit.context_bits.size(); ++i) {
        circuit.context_bits[i].allocate(pb, "context byte range bit");
    }
    for (auto &payload_bit : circuit.payload_bits) {
        payload_bit.allocate(pb, "payload byte bit");
    }
    for (std::size_t byte = 0; byte < kPayloadBytes; ++byte) {
        std::array<pb_variable<ProofField>, kBitsPerByte> bits{};
        for (std::size_t bit = 0; bit < bits.size(); ++bit) {
            bits[bit] = circuit.payload_bits[byte * kBitsPerByte + bit];
        }
        pb.val(circuit.payload_bytes[byte]) = ProofField(payload[byte]);
        bind_packed_bits(pb, bits, circuit.payload_bytes[byte], "payload");
        assign_bits(pb, bits, payload[byte]);
    }
    for (std::size_t i = 0; i < circuit.opening_bits.size(); ++i) {
        circuit.opening_bits[i].allocate(pb, "bounded opening bit");
    }

    for (std::size_t byte = 0; byte < kContextBytes; ++byte) {
        std::array<pb_variable<ProofField>, 8> bits{};
        for (std::size_t bit = 0; bit < bits.size(); ++bit) {
            bits[bit] = circuit.context_bits[byte * 8 + bit];
        }
        bind_packed_bits(pb, bits, circuit.context[byte], "context");
        assign_bits(pb, bits, context[byte]);
    }
    for (std::size_t i = 0; i < circuit.opening_bits.size(); ++i) {
        generate_boolean_r1cs_constraint<ProofField>(pb, circuit.opening_bits[i], "opening bit");
        const bool set = ((opening[i / kBitsPerByte] >> (i % kBitsPerByte)) & 1u) != 0;
        pb.val(circuit.opening_bits[i]) = ProofField(set ? 1 : 0);
    }

    for (std::size_t row = 0; row < kCommitmentRows; ++row) {
        pb_linear_combination<ProofField> commitment_lc;
        for (std::size_t i = 0; i < kPayloadBits; ++i) {
            commitment_lc.add_term(
                circuit.payload_bits[i],
                ProofField(key.message_matrix[row * kMessageBits + i]));
        }
        for (std::size_t i = 0; i < kContextBits; ++i) {
            commitment_lc.add_term(
                circuit.context_bits[i],
                ProofField(key.message_matrix[
                    row * kMessageBits + kPayloadBits + i]));
        }
        for (std::size_t i = 0; i < kOpeningBits; ++i) {
            commitment_lc.add_term(
                circuit.opening_bits[i],
                ProofField(key.randomness_matrix[row * kOpeningBits + i]));
        }
        pb.add_r1cs_constraint(r1cs_constraint<ProofField>(
            1, commitment_lc, circuit.commitment[row]));
    }

    return circuit;
}

} // namespace

int main(int argc, char **argv) {
    std::string response_output_path;
    std::string verifier_key_output_path;
    std::string extracted_proof_output_path;
    std::string verify_proof_path;
    std::string verifier_key_input_path;
    std::string expected_context_hex;
    std::string prover_context_hex;
    for (int i = 1; i < argc; ++i) {
        const std::string option(argv[i]);
        if (i + 1 >= argc) {
            std::cerr << "missing value for " << option << '\n';
            return 19;
        }
        const std::string value(argv[++i]);
        if (option == "--response-output") {
            response_output_path = value;
        } else if (option == "--export-verifier-key") {
            verifier_key_output_path = value;
        } else if (option == "--export-extracted-proof") {
            extracted_proof_output_path = value;
        } else if (option == "--verify-extracted-proof") {
            verify_proof_path = value;
        } else if (option == "--verifier-key") {
            verifier_key_input_path = value;
        } else if (option == "--expected-context-hex") {
            expected_context_hex = value;
        } else if (option == "--prover-context-hex") {
            prover_context_hex = value;
        } else {
            std::cerr << "unknown option: " << option << '\n';
            return 19;
        }
    }
    const bool exporting_split_process_files =
        !verifier_key_output_path.empty() || !extracted_proof_output_path.empty();
    const bool verifying_split_process_files = !verify_proof_path.empty();
    std::array<std::uint8_t, kContextBytes> expected_context{};
    if ((exporting_split_process_files &&
         (verifier_key_output_path.empty() || extracted_proof_output_path.empty())) ||
        (verifying_split_process_files &&
         (verifier_key_input_path.empty() || exporting_split_process_files ||
          !response_output_path.empty() ||
          !parse_context_hex(expected_context_hex, expected_context))) ||
        (!verifying_split_process_files &&
         (!verifier_key_input_path.empty() || !expected_context_hex.empty())) ||
        (verifying_split_process_files && !prover_context_hex.empty())) {
        std::cerr << "usage: isw21_r1cs_opening_smoke "
                     "[--response-output FILE] [--prover-context-hex 64_HEX_DIGITS] "
                     "[--export-verifier-key FILE --export-extracted-proof FILE] | "
                     "[--verify-extracted-proof FILE --verifier-key FILE "
                     "--expected-context-hex 64_HEX_DIGITS]\n";
        return 19;
    }
    if (verifying_split_process_files) {
        auto prg = std::make_unique<LWERandomness::PseudoRandomGenerator>();
        auto dg = std::make_unique<LWERandomness::DiscreteGaussian>(
            ParameterSet::width, LWE::expand, *prg);
        public_params_init<Fp2_b19_pp, RingParameters>(prg.get(), dg.get());
        return verify_extracted_proof(
                   verify_proof_path, verifier_key_input_path, expected_context)
                   ? 0
                   : 22;
    }

    std::array<std::uint8_t, kContextBytes> context = {
        0x91, 0x3a, 0xe1, 0x20, 0x77, 0x58, 0x02, 0xb4,
        0x6c, 0xa9, 0x11, 0x08, 0xd2, 0x33, 0x4f, 0x80,
        0x29, 0xf1, 0x63, 0x05, 0x9a, 0x44, 0x18, 0xce,
        0x7d, 0x26, 0xb0, 0x52, 0x0f, 0x8b, 0xd7, 0x31};
    if (!prover_context_hex.empty() &&
        !parse_context_hex(prover_context_hex, context)) {
        std::cerr << "invalid prover context; expected exactly 64 hex digits\n";
        return 19;
    }
    std::array<std::uint8_t, kPayloadBytes> payload{};
    std::array<std::uint8_t, kOpeningBytes> opening{};
    LWERandomness::PseudoRandomGenerator commitment_prg;
    const KtxCommitmentKey commitment_key =
        generate_ktx_commitment_key(commitment_prg);
    for (std::size_t i = 0; i < kPayloadBytes; ++i) {
        payload[i] = static_cast<std::uint8_t>(0x5au + 29u * i);
    }
    for (auto &byte : opening) {
        byte = static_cast<std::uint8_t>(commitment_prg.bounded(1u << kBitsPerByte));
    }

    Circuit circuit = make_circuit(commitment_key, context, payload, opening);
    if (!circuit.board.is_satisfied()) {
        const auto constraints = circuit.board.get_constraint_system();
        const auto assignment = circuit.board.full_variable_assignment();
        for (std::size_t i = 0; i < constraints.constraints.size(); ++i) {
            const auto &constraint = constraints.constraints[i];
            if (constraint.a.evaluate(assignment) * constraint.b.evaluate(assignment) !=
                constraint.c.evaluate(assignment)) {
                std::cerr << "unsatisfied R1CS constraint index=" << i << '\n';
                break;
            }
        }
        std::cerr << "honest opening does not satisfy the R1CS relation\n";
        return 1;
    }

    auto recentered_context = context;
    recentered_context[0] = static_cast<std::uint8_t>(recentered_context[0] + 1);
    Circuit recentered_circuit = make_circuit(
        commitment_key, recentered_context, payload, opening);
    if (!recentered_circuit.board.is_satisfied()) {
        std::cerr << "recentered statement should have a valid opening witness\n";
        return 2;
    }

    Circuit altered_commitment = make_circuit(
        commitment_key, context, payload, opening);
    altered_commitment.board.val(altered_commitment.commitment[0]) +=
        ProofField::one();
    if (altered_commitment.board.is_satisfied()) {
        std::cerr << "altered KTX commitment unexpectedly satisfies the R1CS\n";
        return 3;
    }

    // Negative witness check: alter one secret payload bit without changing
    // the public commitment. The R1CS must reject this witness.
    circuit.board.val(circuit.payload_bits[0]) =
        ProofField(1) - circuit.board.val(circuit.payload_bits[0]);
    if (circuit.board.is_satisfied()) {
        std::cerr << "altered payload unexpectedly satisfies the R1CS relation\n";
        return 4;
    }
    circuit.board.val(circuit.payload_bits[0]) =
        ProofField(1) - circuit.board.val(circuit.payload_bits[0]);

    // Negative opening check: an altered secret opening must not open the
    // unchanged public commitment while the payload stays unchanged.
    circuit.board.val(circuit.opening_bits[0]) =
        ProofField(1) - circuit.board.val(circuit.opening_bits[0]);
    if (circuit.board.is_satisfied()) {
        std::cerr << "altered opening unexpectedly satisfies the R1CS relation\n";
        return 5;
    }
    circuit.board.val(circuit.opening_bits[0]) =
        ProofField(1) - circuit.board.val(circuit.opening_bits[0]);

    using namespace LWE;
    auto prg = std::make_unique<LWERandomness::PseudoRandomGenerator>();
    auto dg = std::make_unique<LWERandomness::DiscreteGaussian>(
        ParameterSet::width, LWE::expand, *prg);
    public_params_init<Fp2_b19_pp, RingParameters>(prg.get(), dg.get());

    r1cs_example<ProofField> example(
        circuit.board.get_constraint_system(),
        circuit.board.primary_input(),
        circuit.board.auxiliary_input());
    r1cs_lattice_snark_crs<Fp2_b19_pp, RingParameters, ParameterSet> crs;
    r1cs_lattice_snark_verification_key<
        Fp2_b19_pp, RingParameters, ParameterSet> verification_key;
    r1cs_lattice_snark_generator<Fp2_b19_pp, RingParameters, ParameterSet>(
        example.constraint_system, crs, verification_key);
    const auto proof = r1cs_lattice_snark_prove<
        Fp2_b19_pp, RingParameters, ParameterSet>(
            crs, example.primary_input, example.auxiliary_input);
    const auto verify = [&](const auto &public_input, const auto &candidate) {
        try {
            return r1cs_lattice_snark_verify<Fp2_b19_pp, RingParameters>(
                verification_key, public_input, candidate);
        } catch (const std::runtime_error &) {
            // The upstream verifier reports some malformed ciphertexts by
            // throwing instead of returning false. Treat that as rejection.
            return false;
        }
    };
    if (!verify(example.primary_input, proof)) {
        std::cerr << "ISW21 verifier rejected the honest application-shaped statement\n";
        return 5;
    }

    std::uint64_t coefficient_count = 0;
    std::uint64_t maximum_coefficient_bits = 0;
    bool coefficients_within_41_bit_bound = true;
    const auto observe_coefficient = [&](const auto &coefficient) {
        ++coefficient_count;
        auto value = coefficient.value;
        if (value >= kCoefficientBoundExclusive) {
            coefficients_within_41_bit_bound = false;
        }
        std::uint64_t bits = 0;
        while (value != 0) {
            ++bits;
            value >>= 1;
        }
        if (bits > maximum_coefficient_bits) {
            maximum_coefficient_bits = bits;
        }
    };
    for (const auto &element : proof.response.a_vec.vec) {
        observe_coefficient(element.c0);
        observe_coefficient(element.c1);
    }
    for (const auto &element : proof.response.c_vec.vec) {
        observe_coefficient(element.c0);
        observe_coefficient(element.c1);
    }
    constexpr std::uint64_t expected_coefficient_count =
        (ParameterSet::n + ParameterSet::pt_dim + ParameterSet::tau) * 2;
    if (coefficient_count != expected_coefficient_count) {
        std::cerr << "unexpected proof response coefficient count\n";
        return 10;
    }
    if (!coefficients_within_41_bit_bound) {
        std::cerr << "proof response coefficient exceeded derived bound\n";
        return 9;
    }
    std::uint64_t fixed_coefficient_width = 0;
    auto maximum_coefficient = kCoefficientBoundExclusive - 1;
    while (maximum_coefficient != 0) {
        ++fixed_coefficient_width;
        maximum_coefficient >>= 1;
    }
    const auto fixed_width_bits = coefficient_count * fixed_coefficient_width;
    const auto fixed_width_bytes = (fixed_width_bits + 7) / 8;

    const auto encoded_response = serialize_response(proof);
    if (encoded_response.size() != fixed_width_bytes ||
        encoded_response.size() != kResponseByteCount) {
        std::cerr << "response codec produced an unexpected byte length\n";
        return 11;
    }
    Proof decoded_proof;
    if (!deserialize_response(encoded_response, decoded_proof) ||
        serialize_response(decoded_proof) != encoded_response ||
        !verify(example.primary_input, decoded_proof)) {
        std::cerr << "canonical response round-trip failed\n";
        return 12;
    }

    auto truncated_response = encoded_response;
    truncated_response.pop_back();
    if (deserialize_response(truncated_response, decoded_proof)) {
        std::cerr << "response codec accepted a truncated encoding\n";
        return 13;
    }
    auto nonzero_padding_response = encoded_response;
    nonzero_padding_response.back() |= 0x80;
    if (deserialize_response(nonzero_padding_response, decoded_proof)) {
        std::cerr << "response codec accepted nonzero trailing padding\n";
        return 14;
    }
    auto out_of_range_response = encoded_response;
    for (std::size_t byte = 0; byte < 5; ++byte) {
        out_of_range_response[byte] = 0xff;
    }
    out_of_range_response[5] |= 0x01;
    if (deserialize_response(out_of_range_response, decoded_proof)) {
        std::cerr << "response codec accepted an out-of-range coefficient\n";
        return 15;
    }

    std::size_t tamper_coefficient_index = 0;
    bool tamper_coefficient_found = false;
    const auto find_tamper_coefficient = [&](const auto &coefficient) {
        if (!tamper_coefficient_found && coefficient.value > 0 &&
            coefficient.value + 1 < kCoefficientBoundExclusive) {
            tamper_coefficient_found = true;
        } else if (!tamper_coefficient_found) {
            ++tamper_coefficient_index;
        }
    };
    for (const auto &element : proof.response.a_vec.vec) {
        find_tamper_coefficient(element.c0);
        find_tamper_coefficient(element.c1);
    }
    for (const auto &element : proof.response.c_vec.vec) {
        find_tamper_coefficient(element.c0);
        find_tamper_coefficient(element.c1);
    }
    if (!tamper_coefficient_found) {
        std::cerr << "could not find a response coefficient safe to tamper\n";
        return 16;
    }
    auto tampered_response = encoded_response;
    const auto tamper_bit_position =
        tamper_coefficient_index * kResponseCoefficientBits;
    tampered_response[tamper_bit_position / 8] ^= static_cast<std::uint8_t>(
        1u << (tamper_bit_position % 8));
    if (!deserialize_response(tampered_response, decoded_proof)) {
        std::cerr << "modified in-range response did not decode canonically\n";
        return 17;
    }
    if (verify(example.primary_input, decoded_proof)) {
        std::cerr << "ISW21 verifier accepted a modified serialized response\n";
        return 18;
    }

    auto wrong_context = example.primary_input;
    wrong_context[0] += ProofField(1);
    if (verify(wrong_context, proof)) {
        std::cerr << "ISW21 verifier accepted the proof under a changed context\n";
        return 6;
    }

    // Recenter both public values so the same witness still satisfies the
    // modified equation. The old proof must nevertheless fail because the
    // verifier checks the full primary input, not only C - H*context.
    const auto recentered_statement = recentered_circuit.board.primary_input();
    if (verify(recentered_statement, proof)) {
        std::cerr << "ISW21 verifier accepted a recentered context/commitment pair\n";
        return 7;
    }

    auto wrong_commitment = example.primary_input;
    wrong_commitment.back() += ProofField(1);
    if (verify(wrong_commitment, proof)) {
        std::cerr << "ISW21 verifier accepted the proof under a changed commitment\n";
        return 8;
    }

    if (!response_output_path.empty()) {
        std::ofstream response_file(
            response_output_path, std::ios::binary | std::ios::trunc);
        if (!response_file ||
            !response_file.write(
                reinterpret_cast<const char *>(encoded_response.data()),
                static_cast<std::streamsize>(encoded_response.size()))) {
            std::cerr << "failed to write serialized proof response\n";
            return 20;
        }
        response_file.flush();
        if (!response_file) {
            std::cerr << "failed to flush serialized proof response\n";
            return 21;
        }
    }
    if (exporting_split_process_files) {
        if (!write_verifier_key(verifier_key_output_path, verification_key)) {
            std::cerr << "failed to write canonical verifier-key file\n";
            return 23;
        }
        if (!write_extracted_proof(
                extracted_proof_output_path,
                example.primary_input,
                encoded_response)) {
            std::cerr << "failed to write canonical extracted-proof file\n";
            return 24;
        }
    }

    std::cout << "HONEST_R1CS=PASS\n"
              << "ALTERED_PAYLOAD_WITNESS=REJECTED\n"
              << "COMMITMENT_EQUATION_MISMATCH=REJECTED\n"
              << "LATTICE_SNARK_HONEST_VERIFY=PASS\n"
              << "CHANGED_CONTEXT_PROOF=REJECTED\n"
              << "RECENTERED_CONTEXT_STATEMENT_PROOF=REJECTED\n"
              << "CHANGED_COMMITMENT_PROOF=REJECTED\n"
              << "PROOF_RESPONSE_ROUNDTRIP=PASS\n"
              << "TAMPERED_SERIALIZED_RESPONSE=REJECTED\n"
              << "MALFORMED_RESPONSE_ENCODINGS=REJECTED\n"
              << "SERIALIZED_RESPONSE_BYTES=" << encoded_response.size()
              << " (response only; no statement/envelope)\n"
              << (response_output_path.empty()
                      ? std::string{}
                      : "RESPONSE_FILE_WRITTEN_BYTES=" +
                            std::to_string(encoded_response.size()) + "\n")
              << (exporting_split_process_files
                      ? "SPLIT_PROCESS_EXPORT=PASS\n"
                      : std::string{})
              << "RESPONSE_COEFFICIENTS=" << coefficient_count << '\n'
              << "MAX_OBSERVED_COEFFICIENT_BITS="
              << maximum_coefficient_bits << '\n'
              << "DERIVED_COEFFICIENT_BOUND_EXCLUSIVE="
              << static_cast<std::uint64_t>(kCoefficientBoundExclusive)
              << '\n'
              << "FIXED_WIDTH_BOUND_BITS_PER_COEFFICIENT="
              << fixed_coefficient_width << '\n'
              << "FIXED_WIDTH_RESPONSE_UPPER_BOUND_BITS="
              << fixed_width_bits << '\n'
              << "FIXED_WIDTH_RESPONSE_UPPER_BOUND_BYTES="
              << fixed_width_bytes << " (response only)\n"
              << "constraints=" << example.constraint_system.num_constraints()
              << " public_inputs=" << example.primary_input.size() << '\n'
              << "PAYLOAD_BYTES=" << kPayloadBytes << '\n'
              << "OPENING_BITS=" << kOpeningBits << '\n'
              << "KTX_COMMITMENT_ROWS=" << kCommitmentRows << '\n'
              << "KTX_MESSAGE_BITS=" << kMessageBits << '\n'
              << "KTX_RANDOMNESS_SURPLUS_BITS="
              << kOpeningBits - kCommitmentRows * kCommitmentModulusBits << '\n'
              << "RELATION=KTX-style SIS commitment to payload and context\n"
              << "ALTERED_OPENING=REJECTED\n"
              << "WARNING=KTX candidate parameters are not independently estimated or reviewed\n";

    return 0;
}
