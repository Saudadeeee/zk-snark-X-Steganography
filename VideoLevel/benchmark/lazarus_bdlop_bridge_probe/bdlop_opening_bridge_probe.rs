use algebra::ring::PolyVec;
use algebra::sampling::{poly_gaussian, poly_uniform};
use labrador::{
    composite_prove, composite_verify, ComKey, PrincipalStatement, SparseConstraint,
    SparseEntry, Witness, Rq,
};
use sha3::{Digest, Sha3_256};

const MU: usize = 3;
const LAMBDA: usize = 3;
const ELL: usize = 4;
const D: usize = MU + LAMBDA + ELL;
const BETASQ: u128 = 5_000_000;
const BITS_PER_BYTE: usize = 8;
const CONSTRAINT_COUNT: usize = MU
    + ELL
    + ELL
    + ELL * BITS_PER_BYTE
    + 63 * (ELL + ELL * BITS_PER_BYTE);
const KEY_SEED: [u8; 32] = [0x31; 32];
const OPEN_SEED: [u8; 32] = [0x52; 32];

fn scalar(value: i64) -> Rq {
    let mut coefficients = [0i64; 64];
    coefficients[0] = value;
    Rq::from_centered(&coefficients)
}

fn pin_constant_coefficients(constraints: &mut Vec<SparseConstraint>, part: usize, rank: usize) {
    for offset in 0..rank {
        for degree in 1..64 {
            constraints.push(SparseConstraint {
                ct_only: true,
                entries: vec![SparseEntry {
                    part,
                    off: offset,
                    phi: vec![Rq::monomial(64 - degree)],
                }],
                a: vec![],
                b: Rq::zero(),
            });
        }
    }
}

fn matrix(rows: usize, domain: u64) -> Vec<Vec<Rq>> {
    (0..rows)
        .map(|row| {
            (0..D)
                .map(|col| poly_uniform::<64>(&KEY_SEED, domain + (row * D + col) as u64))
                .collect()
        })
        .collect()
}

fn statement_hash(c0: &[Rq], cm: &[Rq], context: &[u8]) -> [u8; 32] {
    let mut hash = Sha3_256::new();
    hash.update(b"zkstego/bdlop-opening-bridge-probe/byte-v2/");
    hash.update(KEY_SEED);
    hash.update((BETASQ as u64).to_be_bytes());
    hash.update((MU as u64).to_be_bytes());
    hash.update((LAMBDA as u64).to_be_bytes());
    hash.update((ELL as u64).to_be_bytes());
    for p in c0.iter().chain(cm.iter()) {
        for coefficient in p.coeffs {
            hash.update((coefficient.value() as u64).to_be_bytes());
        }
    }
    hash.update((context.len() as u64).to_be_bytes());
    hash.update(context);
    hash.finalize().into()
}

fn bdlop_instance(context: &[u8]) -> (PrincipalStatement, Witness, Vec<Rq>, Vec<Rq>) {
    // BDLOP shape: d=mu+lambda+ell Gaussian randomness polynomials,
    // B0 has mu rows, Bm has ell rows, and Tm_i=<Bm_i,r>+m_i.
    let b0 = matrix(MU, 0x1000);
    let bm = matrix(ELL, 0x2000);
    let randomness: Vec<Rq> = (0..D)
        .map(|i| poly_gaussian::<64>(5, &OPEN_SEED, 0x3000 + i as u64))
        .collect();
    // Fixed-width, little-endian bit decomposition per byte-valued message
    // slot. Constraints below prove every bit is boolean and reconstruct m.
    let message_bytes = [1u8, 2, 255, 0];
    let message = message_bytes.map(|value| scalar(i64::from(value)));
    let bits: Vec<Rq> = message_bytes
        .iter()
        .flat_map(|byte| {
            (0..BITS_PER_BYTE).map(move |bit| scalar(i64::from((byte >> bit) & 1)))
        })
        .collect();

    let mut t0 = Vec::with_capacity(MU);
    for row in &b0 {
        t0.push(
            row.iter()
                .zip(&randomness)
                .fold(Rq::zero(), |acc, (a, r)| &acc + &(a * r)),
        );
    }
    let mut tm = Vec::with_capacity(ELL);
    for (row, m) in bm.iter().zip(&message) {
        let inner_product = row
            .iter()
            .zip(&randomness)
            .fold(Rq::zero(), |acc, (a, r)| &acc + &(a * r));
        tm.push(&inner_product + m);
    }

    let mut constraints = Vec::with_capacity(CONSTRAINT_COUNT);
    for (row, target) in b0.iter().zip(&t0) {
        constraints.push(SparseConstraint {
            ct_only: false,
            entries: vec![SparseEntry {
                part: 0,
                off: 0,
                phi: row.clone(),
            }],
            a: vec![],
            b: target.clone(),
        });
    }
    for (i, (row, target)) in bm.iter().zip(&tm).enumerate() {
        constraints.push(SparseConstraint {
            ct_only: false,
            entries: vec![
                SparseEntry {
                    part: 0,
                    off: 0,
                    phi: row.clone(),
                },
                SparseEntry {
                    part: 1,
                    off: i,
                    phi: vec![Rq::one()],
                },
            ],
            a: vec![],
            b: target.clone(),
        });
    }

    for byte_index in 0..ELL {
        let mut entries = vec![SparseEntry {
            part: 1,
            off: byte_index,
            phi: vec![Rq::one()],
        }];
        for bit_index in 0..BITS_PER_BYTE {
            entries.push(SparseEntry {
                part: 2 + byte_index * BITS_PER_BYTE + bit_index,
                off: 0,
                phi: vec![scalar(-(1i64 << bit_index))],
            });
        }
        constraints.push(SparseConstraint {
            ct_only: false,
            entries,
            a: vec![],
            b: Rq::zero(),
        });
    }
    let bit_constraint_start = constraints.len();
    for bit_index in 0..bits.len() {
        let part = 2 + bit_index;
        constraints.push(SparseConstraint {
            ct_only: false,
            entries: vec![SparseEntry {
                part,
                off: 0,
                phi: vec![scalar(-1)],
            }],
            a: vec![(part, part, Rq::one())],
            b: Rq::zero(),
        });
    }
    pin_constant_coefficients(&mut constraints, 1, ELL);
    for part in 2..2 + bits.len() {
        pin_constant_coefficients(&mut constraints, part, 1);
    }
    assert_eq!(constraints.len(), CONSTRAINT_COUNT);

    let mut parts = vec![
        PolyVec::from_polys(randomness),
        PolyVec::from_polys(message.to_vec()),
    ];
    parts.extend(bits.into_iter().map(|bit| PolyVec::from_polys(vec![bit])));
    let witness = Witness::new(parts);
    assert_eq!(bit_constraint_start, MU + 2 * ELL);
    let statement = PrincipalStatement {
        n: std::iter::once(D)
            .chain(std::iter::once(ELL))
            .chain(std::iter::repeat_n(1, ELL * BITS_PER_BYTE))
            .collect(),
        cnst: constraints,
        betasq: BETASQ,
        h: statement_hash(&t0, &tm, context),
    };
    (statement, witness, t0, tm)
}

#[test]
fn bdlop_opening_relation_proves_on_labrador_ring() {
    let context = b"session=fixture-02;codec=h264-baseline-cavlc;relation=bdlop-open-v1";
    let (statement, witness, t0, tm) = bdlop_instance(context);
    eprintln!("opening_normsq={}", witness.total_normsq());
    assert!(witness.total_normsq() <= BETASQ);

    let key = ComKey::new([0x71; 32]);
    let proof = composite_prove(&key, &statement, &witness)
        .expect("bounded BDLOP-shaped opening should prove");
    composite_verify(&key, &statement, &proof)
        .expect("proof should verify for the fixed BDLOP-shaped statement");

    // The first reconstructed byte is 1. Making its low bit non-boolean is
    // rejected by the dedicated b^2-b=0 constraint, even before proof logic.
    let mut non_boolean_bit = witness.clone();
    non_boolean_bit.parts[2].polys[0] = scalar(2);
    assert!(!statement.cnst[MU + 2 * ELL].check(&non_boolean_bit));
    assert!(labrador::principal::principal_verify(&statement, &non_boolean_bit).is_err());

    // 256 is outside the one-byte range and cannot satisfy the 8-bit
    // reconstruction equation for this witness encoding.
    let mut out_of_range_byte = witness.clone();
    out_of_range_byte.parts[1].polys[0] = scalar(256);
    assert!(!statement.cnst[MU + ELL].check(&out_of_range_byte));
    assert!(labrador::principal::principal_verify(&statement, &out_of_range_byte).is_err());

    let mut wrong_context = statement.clone();
    wrong_context.h = statement_hash(&t0, &tm, b"different-session");
    assert!(composite_verify(&key, &wrong_context, &proof).is_err());

    let mut changed_target = statement.clone();
    let old_target = changed_target.cnst[0].b.clone();
    changed_target.cnst[0].b = &old_target + &Rq::one();
    assert!(composite_verify(&key, &changed_target, &proof).is_err());
}
