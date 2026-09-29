// Isolated ISW21 feasibility probe; not production protocol code.
#include "lwe/snark/r1cs_lattice_snark.hpp"
#include "lwe/tests/common.hpp"
#include "lwe/tests/circ_lattice_params.hpp"

#include <libsnark/gadgetlib1/gadgets/hashes/sha256/sha256_gadget.hpp>

#include <openssl/sha.h>

#include <algorithm>
#include <array>
#include <chrono>
#include <cstdint>
#include <iostream>
#include <memory>
#include <string>
#include <vector>

using namespace libsnark;
using namespace LWE;

namespace {

using param_set = LWE::B19C20;
using ring_pp = Ring2_common_pp<param_set::q_int>;
using field_t = libff::Fr<Fp2_b19_pp>;
using payload_bytes = std::array<std::uint8_t, 32>;
using opening_bytes = std::array<std::uint8_t, 32>;
using domain_bytes = std::array<std::uint8_t, 32>;

libff::bit_vector to_bits(const std::uint8_t* bytes, std::size_t length) {
    libff::bit_vector bits;
    bits.reserve(length * 8);
    for (std::size_t index = 0; index < length; ++index) {
        for (int shift = 7; shift >= 0; --shift) {
            bits.push_back(((bytes[index] >> shift) & 1U) != 0U);
        }
    }
    return bits;
}

libff::bit_vector padding_block(std::uint64_t message_bits) {
    libff::bit_vector bits(SHA256_block_size, false);
    bits[0] = true;
    for (std::size_t byte_index = 0; byte_index < 8; ++byte_index) {
        const auto byte = static_cast<std::uint8_t>(
            message_bits >> (56U - static_cast<unsigned>(byte_index * 8U)));
        for (int bit_index = 0; bit_index < 8; ++bit_index) {
            const auto target = SHA256_block_size - 64U + byte_index * 8U +
                                static_cast<std::size_t>(bit_index);
            bits[target] = ((byte >> (7 - bit_index)) & 1U) != 0U;
        }
    }
    return bits;
}

std::array<std::uint8_t, SHA256_DIGEST_LENGTH> commitment(
    const domain_bytes& domain,
    const opening_bytes& opening,
    const payload_bytes& payload) {
    std::array<std::uint8_t, 96> preimage{};
    std::copy(domain.begin(), domain.end(), preimage.begin());
    std::copy(opening.begin(), opening.end(), preimage.begin() + 32);
    std::copy(payload.begin(), payload.end(), preimage.begin() + 64);

    std::array<std::uint8_t, SHA256_DIGEST_LENGTH> digest{};
    SHA256(preimage.data(), preimage.size(), digest.data());
    return digest;
}

void add_equal_constant(protoboard<field_t>& board,
                        const pb_variable<field_t>& variable,
                        bool expected) {
    board.add_r1cs_constraint(r1cs_constraint<field_t>(
        field_t::one(), variable, expected ? field_t::one() : field_t::zero()));
}

void add_equal_variables(protoboard<field_t>& board,
                         const pb_variable<field_t>& left,
                         const pb_variable<field_t>& right) {
    board.add_r1cs_constraint(
        r1cs_constraint<field_t>(field_t::one(), left - right, field_t::zero()));
}

}  // namespace

int main() {
    static_assert(sizeof(param_set::q_int) > 0);

    auto prg = std::make_unique<LWERandomness::PseudoRandomGenerator>();
    auto sampler = std::make_unique<LWERandomness::DiscreteGaussian>(
        param_set::width, LWE::expand, *prg);
    public_params_init<Fp2_b19_pp, ring_pp>(prg.get(), sampler.get());

    domain_bytes domain{};
    constexpr char domain_tag[] = "zkstego/payload/sha256/v1";
    std::copy_n(reinterpret_cast<const std::uint8_t*>(domain_tag),
                sizeof(domain_tag) - 1, domain.begin());
    opening_bytes opening{};
    payload_bytes payload{};
    for (std::size_t index = 0; index < opening.size(); ++index) {
        opening[index] = static_cast<std::uint8_t>(index);
        payload[index] = static_cast<std::uint8_t>(0xA5U ^ index);
    }
    const auto domain_bits = to_bits(domain.data(), domain.size());

    protoboard<field_t> board;
    digest_variable<field_t> public_commitment(
        board, SHA256_digest_size, "public_commitment");
    digest_variable<field_t> private_domain(
        board, SHA256_digest_size, "fixed_domain");
    digest_variable<field_t> private_opening(
        board, SHA256_digest_size, "private_opening");
    digest_variable<field_t> private_payload(
        board, SHA256_digest_size, "private_payload");
    digest_variable<field_t> intermediate(
        board, SHA256_digest_size, "sha256_first_block");

    sha256_two_to_one_hash_gadget<field_t> first_block(
        board, private_domain, private_opening, intermediate,
        "sha256_domain_and_opening");

    block_variable<field_t> final_block(
        board, SHA256_block_size, "sha256_payload_and_padding");
    pb_linear_combination_array<field_t> previous_state;
    previous_state.reserve(intermediate.bits.size());
    for (const auto& bit : intermediate.bits) {
        previous_state.emplace_back(bit);
    }
    sha256_compression_function_gadget<field_t> final_compression(
        board, previous_state, final_block.bits, public_commitment,
        "sha256_final_block");

    public_commitment.generate_r1cs_constraints();
    private_domain.generate_r1cs_constraints();
    private_opening.generate_r1cs_constraints();
    private_payload.generate_r1cs_constraints();
    intermediate.generate_r1cs_constraints();
    first_block.generate_r1cs_constraints();
    final_block.generate_r1cs_constraints();
    final_compression.generate_r1cs_constraints();

    for (std::size_t index = 0; index < private_domain.bits.size(); ++index) {
        add_equal_constant(board, private_domain.bits[index],
                           domain_bits[index]);
    }
    for (std::size_t index = 0; index < private_payload.bits.size(); ++index) {
        add_equal_variables(board, final_block.bits[index],
                            private_payload.bits[index]);
    }
    const auto fixed_padding = padding_block(96U * 8U);
    for (std::size_t index = 0; index < fixed_padding.size(); ++index) {
        add_equal_constant(board, final_block.bits[256U + index],
                           fixed_padding[index]);
    }

    board.set_input_sizes(SHA256_digest_size);
    private_domain.generate_r1cs_witness(domain_bits);
    private_opening.generate_r1cs_witness(
        to_bits(opening.data(), opening.size()));
    private_payload.generate_r1cs_witness(
        to_bits(payload.data(), payload.size()));
    final_block.generate_r1cs_witness([&] {
        auto bits = to_bits(payload.data(), payload.size());
        const auto padding = padding_block(96U * 8U);
        bits.insert(bits.end(), padding.begin(), padding.end());
        return bits;
    }());
    first_block.generate_r1cs_witness();
    final_compression.generate_r1cs_witness();

    const auto expected_digest = commitment(domain, opening, payload);
    if (public_commitment.get_digest() !=
        to_bits(expected_digest.data(), expected_digest.size())) {
        std::cerr << "R1CS SHA-256 gadget disagrees with OpenSSL SHA-256\n";
        return 1;
    }
    if (!board.is_satisfied()) {
        std::cerr << "correct private opening/payload did not satisfy R1CS\n";
        return 1;
    }

    auto constraint_system = board.get_constraint_system();
    std::cout << "relation=sha256-domain-opening-payload-fixed32-v1\n"
              << "constraints=" << constraint_system.num_constraints() << '\n'
              << "public_input_bits=" << SHA256_digest_size << '\n'
              << "private_payload_bytes=" << payload.size() << '\n'
              << "private_opening_bytes=" << opening.size() << '\n';

    r1cs_lattice_snark_crs<Fp2_b19_pp, ring_pp, param_set> crs;
    r1cs_lattice_snark_verification_key<Fp2_b19_pp, ring_pp, param_set> vk;
    const auto setup_start = std::chrono::steady_clock::now();
    r1cs_lattice_snark_generator<Fp2_b19_pp, ring_pp, param_set>(
        constraint_system, crs, vk);
    const auto setup_end = std::chrono::steady_clock::now();

    const auto prove_start = std::chrono::steady_clock::now();
    const auto proof = r1cs_lattice_snark_prove<Fp2_b19_pp, ring_pp, param_set>(
        crs, board.primary_input(), board.auxiliary_input());
    const auto prove_end = std::chrono::steady_clock::now();
    if (!r1cs_lattice_snark_verify<Fp2_b19_pp, ring_pp, param_set>(
            vk, board.primary_input(), proof)) {
        std::cerr << "ISW21 verifier rejected the application-relation proof\n";
        return 1;
    }
    const auto verify_end = std::chrono::steady_clock::now();

    auto changed_public_input = board.primary_input();
    changed_public_input[0] = field_t::one() - changed_public_input[0];
    if (r1cs_lattice_snark_verify<Fp2_b19_pp, ring_pp, param_set>(
            vk, changed_public_input, proof)) {
        std::cerr << "ISW21 verifier accepted a changed public digest\n";
        return 1;
    }

    auto changed_payload_bit = board.val(private_payload.bits[0]);
    board.val(private_payload.bits[0]) =
        changed_payload_bit == field_t::zero() ? field_t::one() : field_t::zero();
    board.val(final_block.bits[0]) = board.val(private_payload.bits[0]);
    if (board.is_satisfied()) {
        std::cerr << "R1CS accepted a mutated payload under the original digest\n";
        return 1;
    }

    const auto elapsed_ms = [](auto start, auto end) {
        return std::chrono::duration<double, std::milli>(end - start).count();
    };
    std::cout << "proof_verified=true\n"
              << "changed_public_digest_rejected=true\n"
              << "changed_payload_unsatisfied=true\n"
              << "setup_ms=" << elapsed_ms(setup_start, setup_end) << '\n'
              << "prove_ms=" << elapsed_ms(prove_start, prove_end) << '\n'
              << "verify_ms=" << elapsed_ms(prove_end, verify_end) << '\n'
              << "proof_serialization=not_implemented\n"
              << "security_status=ISW21 research prototype; designated verifier; unaudited\n";
    return 0;
}
