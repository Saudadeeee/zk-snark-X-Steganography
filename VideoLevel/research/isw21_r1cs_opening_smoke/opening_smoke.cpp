#include "lwe/snark/r1cs_lattice_snark.hpp"
#include "lwe/tests/circ_lattice_params.hpp"
#include "lwe/tests/common.hpp"
#include <libsnark/gadgetlib1/gadgets/basic_gadgets.hpp>
#include <libsnark/gadgetlib1/protoboard.hpp>

#include <array>
#include <cstdint>
#include <iostream>
#include <memory>

namespace {

using namespace libsnark;
using ParameterSet = LWE::B19C20;
using ProofField = libff::Fr<Fp2_b19_pp>;
using RingParameters = Ring2_common_pp<ParameterSet::q_int>;

constexpr std::uint64_t kCommitmentModulus = (1u << 19) - 1;
constexpr std::size_t kContextBytes = 32;
constexpr std::size_t kPayloadBits = 8;
constexpr std::size_t kOpeningBits = 16;

struct Circuit {
    protoboard<ProofField> board;
    std::array<pb_variable<ProofField>, kContextBytes> context{};
    pb_variable<ProofField> commitment;
    std::array<pb_variable<ProofField>, kContextBytes * 8> context_bits{};
    std::array<pb_variable<ProofField>, 19> commitment_bits{};
    std::array<pb_variable<ProofField>, 19> commitment_prefix_ones{};
    pb_variable<ProofField> payload;
    std::array<pb_variable<ProofField>, kPayloadBits> payload_bits{};
    std::array<pb_variable<ProofField>, kOpeningBits> opening_bits{};
};

std::uint64_t opening_coefficient(std::size_t index) {
    return (104729u * static_cast<std::uint64_t>(index + 1) + 33u) %
           kCommitmentModulus;
}

std::uint64_t context_coefficient(std::size_t index) {
    return (7919u * static_cast<std::uint64_t>(index + 1) + 17u) %
           kCommitmentModulus;
}

std::uint64_t commitment_for(
    const std::array<std::uint8_t, kContextBytes> &context,
    std::uint8_t payload,
    std::uint16_t opening) {
    std::uint64_t result = 31337u * payload;
    for (std::size_t i = 0; i < context.size(); ++i) {
        result += context_coefficient(i) * context[i];
    }
    for (std::size_t i = 0; i < kOpeningBits; ++i) {
        if ((opening >> i) & 1u) {
            result += opening_coefficient(i);
        }
    }
    return result % kCommitmentModulus;
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
    const std::array<std::uint8_t, kContextBytes> &context,
    std::uint8_t payload,
    std::uint16_t opening) {
    Circuit circuit;
    auto &pb = circuit.board;

    // Public instance: the complete 32-byte verifier context and commitment.
    for (std::size_t i = 0; i < circuit.context.size(); ++i) {
        circuit.context[i].allocate(pb, "public context byte");
        pb.val(circuit.context[i]) = ProofField(context[i]);
    }
    circuit.commitment.allocate(pb, "public commitment");
    const std::uint64_t expected_commitment =
        commitment_for(context, payload, opening);
    pb.val(circuit.commitment) = ProofField(expected_commitment);
    pb.set_input_sizes(kContextBytes + 1);

    circuit.payload.allocate(pb, "private payload byte");
    pb.val(circuit.payload) = ProofField(payload);
    for (std::size_t i = 0; i < circuit.context_bits.size(); ++i) {
        circuit.context_bits[i].allocate(pb, "context byte range bit");
    }
    for (std::size_t i = 0; i < circuit.commitment_bits.size(); ++i) {
        circuit.commitment_bits[i].allocate(pb, "commitment canonical bit");
    }
    for (std::size_t i = 0; i < circuit.commitment_prefix_ones.size(); ++i) {
        circuit.commitment_prefix_ones[i].allocate(pb, "commitment canonicality prefix");
    }
    for (std::size_t i = 0; i < circuit.payload_bits.size(); ++i) {
        circuit.payload_bits[i].allocate(pb, "payload byte bit");
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
    bind_packed_bits(pb, circuit.commitment_bits, circuit.commitment, "commitment");
    assign_bits(pb, circuit.commitment_bits, expected_commitment);
    bind_packed_bits(pb, circuit.payload_bits, circuit.payload, "payload");
    assign_bits(pb, circuit.payload_bits, payload);

    pb.add_r1cs_constraint(r1cs_constraint<ProofField>(
        1, circuit.commitment_bits[0], circuit.commitment_prefix_ones[0]));
    pb.val(circuit.commitment_prefix_ones[0]) =
        pb.val(circuit.commitment_bits[0]);
    for (std::size_t i = 1; i < circuit.commitment_prefix_ones.size(); ++i) {
        pb.add_r1cs_constraint(r1cs_constraint<ProofField>(
            circuit.commitment_prefix_ones[i - 1], circuit.commitment_bits[i],
            circuit.commitment_prefix_ones[i]));
        pb.val(circuit.commitment_prefix_ones[i]) =
            pb.val(circuit.commitment_prefix_ones[i - 1]) *
            pb.val(circuit.commitment_bits[i]);
    }
    generate_r1cs_equals_const_constraint<ProofField>(
        pb, circuit.commitment_prefix_ones.back(), ProofField::zero(),
        "commitment must be less than 2^19-1");

    pb_linear_combination<ProofField> opening_lc;
    for (std::size_t i = 0; i < circuit.opening_bits.size(); ++i) {
        generate_boolean_r1cs_constraint<ProofField>(pb, circuit.opening_bits[i], "opening bit");
        const bool set = ((opening >> i) & 1u) != 0;
        pb.val(circuit.opening_bits[i]) = ProofField(set ? 1 : 0);
        opening_lc.add_term(circuit.opening_bits[i],
                             ProofField(opening_coefficient(i)));
    }

    pb_linear_combination<ProofField> commitment_lc = opening_lc;
    commitment_lc.add_term(circuit.payload, ProofField(31337u));
    for (std::size_t i = 0; i < kContextBytes; ++i) {
        commitment_lc.add_term(circuit.context[i],
                               ProofField(context_coefficient(i)));
    }
    pb.add_r1cs_constraint(
        r1cs_constraint<ProofField>(1, commitment_lc, circuit.commitment));

    return circuit;
}

} // namespace

int main() {
    const std::array<std::uint8_t, kContextBytes> context = {
        0x91, 0x3a, 0xe1, 0x20, 0x77, 0x58, 0x02, 0xb4,
        0x6c, 0xa9, 0x11, 0x08, 0xd2, 0x33, 0x4f, 0x80,
        0x29, 0xf1, 0x63, 0x05, 0x9a, 0x44, 0x18, 0xce,
        0x7d, 0x26, 0xb0, 0x52, 0x0f, 0x8b, 0xd7, 0x31};
    constexpr std::uint8_t payload = 0x5a;
    constexpr std::uint16_t opening = 0xa53c;

    Circuit circuit = make_circuit(context, payload, opening);
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
    Circuit recentered_circuit =
        make_circuit(recentered_context, payload, opening);
    if (!recentered_circuit.board.is_satisfied()) {
        std::cerr << "recentered statement should have a valid opening witness\n";
        return 2;
    }

    Circuit noncanonical_c = make_circuit(context, payload, opening);
    noncanonical_c.board.val(noncanonical_c.commitment) = ProofField::zero();
    for (std::size_t i = 0; i < noncanonical_c.commitment_bits.size(); ++i) {
        noncanonical_c.board.val(noncanonical_c.commitment_bits[i]) = ProofField::one();
        noncanonical_c.board.val(noncanonical_c.commitment_prefix_ones[i]) =
            ProofField::one();
    }
    if (noncanonical_c.board.is_satisfied()) {
        std::cerr << "non-canonical all-ones encoding of q=0 was accepted\n";
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

    if (!r1cs_lattice_snark_verify<Fp2_b19_pp, RingParameters>(
            verification_key, example.primary_input, proof)) {
        std::cerr << "ISW21 verifier rejected the honest application-shaped statement\n";
        return 5;
    }

    auto wrong_context = example.primary_input;
    wrong_context[0] += ProofField(1);
    if (r1cs_lattice_snark_verify<Fp2_b19_pp, RingParameters>(
            verification_key, wrong_context, proof)) {
        std::cerr << "ISW21 verifier accepted the proof under a changed context\n";
        return 6;
    }

    // Recenter both public values so the same witness still satisfies the
    // modified equation. The old proof must nevertheless fail because the
    // verifier checks the full primary input, not only C - H*context.
    const auto recentered_statement = recentered_circuit.board.primary_input();
    if (r1cs_lattice_snark_verify<Fp2_b19_pp, RingParameters>(
            verification_key, recentered_statement, proof)) {
        std::cerr << "ISW21 verifier accepted a recentered context/commitment pair\n";
        return 7;
    }

    auto wrong_commitment = example.primary_input;
    wrong_commitment.back() += ProofField(1);
    if (r1cs_lattice_snark_verify<Fp2_b19_pp, RingParameters>(
            verification_key, wrong_commitment, proof)) {
        std::cerr << "ISW21 verifier accepted the proof under a changed commitment\n";
        return 8;
    }

    std::cout << "HONEST_R1CS=PASS\n"
              << "ALTERED_PAYLOAD_WITNESS=REJECTED\n"
              << "NONCANONICAL_COMMITMENT=REJECTED\n"
              << "LATTICE_SNARK_HONEST_VERIFY=PASS\n"
              << "CHANGED_CONTEXT_PROOF=REJECTED\n"
              << "RECENTERED_CONTEXT_STATEMENT_PROOF=REJECTED\n"
              << "CHANGED_COMMITMENT_PROOF=REJECTED\n"
              << "constraints=" << example.constraint_system.num_constraints()
              << " public_inputs=" << example.primary_input.size() << '\n'
              << "WARNING=toy q=2^19-1 commitment, 16-bit binary opening; not secure parameters\n";

    return 0;
}
