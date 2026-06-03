# ZK-Stego VideoLevel Playbook

Last updated: 2026-06-03
Branch: `main`

## Mission

The goal of this repository is to reach a system that is defensible in both
benchmarking and paper form, with:
- one clear baseline system,
- one trustworthy benchmark workflow,
- and one research roadmap that does not contradict the current claims.

This playbook keeps only:
- the current baseline we must protect,
- the work that still remains,
- the correct order of priorities,
- and the criteria for stopping or raising claims.

Anything already completed and no longer useful for decision-making has been
removed from this file.

---

## Frozen Baseline

This is the current source of truth for paper writing, benchmarks, and docs.

### Core claim now
- locked operating-point embedding
- all-intra H.264 baseline / CAVLC
- strict non-blind verification
- sidecar-assisted near-blind verification

### Do not over-claim beyond this
- broad public API mode is not yet the headline path
- inter-coded / GOP>1 is not yet a strong supported regime
- blind-core is not yet a usable system path

### Rule
- If a change makes this baseline weaker or more ambiguous, do not move it into
  the main narrative.
- Every paper claim must stay anchored to this baseline until we have stronger
  evidence.

---

## Decision Rules

These rules are here to keep us from drifting into the wrong direction.

### When a branch can be promoted into a main claim
- It has a benchmark that can be repeated through the runner.
- It has stable JSON output.
- It has clean artifact naming and schema.
- It has at least one clear end-to-end use case.
- It does not only win on a synthetic proxy; it also stands on near-real data.

### When a branch should remain a research branch
- It has good signals but is not end-to-end yet.
- Runtime is still too heavy for regular use.
- It only passes on synthetic setup.
- Major trade-offs are still unresolved.

### Global priority order
1. Keep the main baseline clean and defensible.
2. Only expand claims when benchmark evidence catches up.
3. On blind-core, prioritize telemetry and error modeling before trying new heuristics.

---

## Priority Roadmap

## P0 - Protect The Main System

This is the work that always comes first.

### P0.1 Benchmark-grade core must stay healthy
- [ ] Keep `Phase 5`, `Phase 6`, `Phase 7`, and the quick suite passing.
- [ ] Do not let blind-core experiments drift the locked operating-point path.
- [ ] If a refactor affects embed, verify, or the benchmark runner, rerun the
      minimum required suite immediately after.

### P0.2 Paper-grade workflow must stay clean
- [ ] Keep `safe_benchmark_runner.py` clean for paper-grade sections.
- [ ] Keep artifact schema and naming stable.
- [ ] Keep `README.md`, `PAPER_EVIDENCE.md`, `OPERATING_ENVELOPE.md`, and
      `ARTIFACT_POLICY.md` synchronized when the baseline changes for real.

### P0.3 Keep the narrative honest
- [ ] Do not promote blind-core to a main claim before there is a real-proof
      end-to-end blind result.
- [ ] Do not use broad public API generic mode as a headline result.

---

## P1 - Paper Readiness

This is the branch that must be finished before full paper drafting.

### P1.1 Freeze wording everywhere
- [ ] Lock manuscript wording to the frozen baseline across all main docs.
- [ ] Finish the threat model around the three verifier layers:
      - strict non-blind
      - sidecar-assisted near-blind
      - blind-core as future/research branch

### P1.2 Final paper-facing tables
- [ ] Finish the verifier-mode table.
- [ ] Finish the four-level capacity table:
      - raw safe
      - patchable usable
      - validated or operating pool
      - operating bits
- [ ] Finish the operating-point stability table.
- [ ] Finish the baseline vs ablation vs this-work comparison table.

### P1.3 Final paper-grade benchmark pass
- [ ] Re-run the full paper-grade benchmark set after the final freeze.
- [ ] Update `PAPER_EVIDENCE.md` with the final numbers.

---

## P2 - Engineering Follow-up On The Main System

These tasks do not block the paper immediately, but they still matter.

### P2.1 Broad public API
- [ ] Improve generic public API realization beyond locked operating-point mode.
- [ ] Raise realized payload in broad mode on representative all-intra assets.
- [ ] Keep diagnostics explicit about failure stage and budget collapse.

### P2.2 Inter-coded support
- [ ] Decide clearly whether to build a real inter-coded path or freeze it as unsupported.
- [ ] If built, add a separate policy for GOP>1 instead of reusing all-intra logic.

### P2.3 Performance
- [ ] Reduce runtime for patchability measurement.
- [ ] Reduce runtime for the heaviest blind diagnostics.

---

## P3 - Blind-Core Research Playbook

Blind-core is still a research branch, but this is the correct way to keep
pushing it without going in circles.

### Current blind-core position

Blind-core already has:
- validated-pool-proxy self-consistency between cover and stego,
- prefix-level feasibility under heavy redundancy,
- structured partial-payload success on synthetic proof prefixes,
- and a very strong structured partial-payload result:
  - synthetic `[length][message][129B proof_prefix]` can be recovered exactly
    with hotspot-focused protection.

Blind-core still does not have:
- blind full payload end-to-end usability,
- blind proof verification end-to-end,
- or a safe mainline claim on real proof bytes.

### Known operating envelopes

#### Synthetic proof-prefix envelope
- Exact structured partial-payload success is confirmed at:
  - `[length][message][16B proof_prefix]`
  - `[length][message][24B proof_prefix]`
  - `[length][message][32B proof_prefix]`
  - `[length][message][48B proof_prefix]`
  - `[length][message][64B proof_prefix]`
  - `[length][message][80B proof_prefix]`
- Baseline break region begins at:
  - `84B`
  - `88B`
  - `96B`
  - `112B`
  - `129B`
- Targeted repair results:
  - `proof_tail_triplicate16` repairs `84B` and `96B`
  - `proof_hotspot_triplicate80_8` repairs `112B` and `129B`
- Failed repair branches:
  - `proof_triplicate`
  - `proof_interleaved`
  - `proof_byte_stride4`
  - larger tail variants such as `tail32` and `tail64`

#### Real-proof envelope
- Current real-proof branch observations:
  - `96B` real proof prefix can reach perfect proof-prefix recovery while header still fails
  - `112B` real proof prefix currently misses one proof byte
  - `129B` real proof prefix currently misses multiple earlier proof bytes
- Current known tension:
  - strengthening header redundancy can restore decoded length
  - but may damage message/proof recovery
- Current implication:
  - real-proof header robustness and real-proof proof-prefix robustness must be optimized separately before recombining them

### State of the synthetic branch

The synthetic branch currently shows:
- exact structured partial-payload success up to
  `[length][message][80B proof_prefix]` with the baseline coding,
- the first break region beginning at `84B`,
- `proof_tail_triplicate16` repairs `84B` and `96B`,
- `proof_hotspot_triplicate80_8` repairs:
  - `112B`
  - `129B`

This means:
- blind-core is no longer blocked at synchronization,
- and coding/protection can expand the operating envelope significantly.

### State of the real-proof branch

The real-proof branch currently shows:
- the synthetic hotspot map does not transfer directly to real proof bytes,
- `96B` real proof prefix can reach `96/96B` on the proof prefix while still
  failing at the header,
- `112B` real proof prefix currently fails at proof byte `79`,
- `129B` real proof prefix currently fails at several earlier bytes,
- raising `header_redundancy` to `8` fixes decoded length but collapses the
  message/proof branch.
- isolated real-proof header diagnostics show:
  - `header_redundancy = 4` passes in header-only mode,
  - `header_redundancy = 8` also passes in header-only mode,
  - `header_redundancy = 12` already fails in header-only mode.

This means:
- the real-proof blind branch must be split into:
  - header robustness
  - proof-prefix robustness
- the immediate issue is not raw header coding strength by itself,
  but the interaction between header and body/proof placement.
- header/body decoupling is not yet a proven fix:
  - `body_gap_blocks = 0` leaves header broken and drops proof-prefix recovery to `89/96B`
  - `body_gap_blocks = 2` can degrade the same `96B` case even further
  - so the decoupling path must be treated as experimental, not yet promoted

### Confirmed failure patterns

These are not assumptions. They are already observed and should guide future work.

- Synthetic branch:
  - the first dominant mismatch was repeatedly observed at byte index `82`
  - local targeted protection works better than global repetition or simple permutation
- Real-proof branch:
  - the dominant synthetic mismatch pattern does not transfer directly
  - proof-prefix mismatch locations move earlier for longer real proof prefixes
  - header failure can appear even when proof-prefix recovery is already perfect for the tested prefix length

### What not to do next

Do not continue by:
- trying more blind heuristics without telemetry,
- increasing global redundancy before understanding the error map,
- or reusing the synthetic hotspot map as if it were valid for real proof bytes.

Also avoid:
- treating synthetic proof-prefix success as if it were equivalent to real-proof success,
- adding global redundancy before confirming which branch it damages,
- or mixing benchmark-grade baseline claims with blind-core experimental results.

### Correct next blind-core steps

#### P3.1 Stabilize the real-proof header path
- [ ] Measure a header-specific error map on the real-proof branch.
- [ ] Design header protection that does not damage the body/proof branch.
- [ ] Immediate target:
      - `96B real proof prefix` must pass both header and proof prefix at the same time.
- [ ] Record the smallest header coding change that preserves proof-prefix recovery.
- [ ] Use the header-only result as a guardrail:
      - do not keep increasing redundancy globally once `4` and `8` are already clean in isolation.
- [ ] Do not lock in any body-gap policy until it is repeatable across reruns.

#### P3.2 Build a real-proof error map
- [ ] Collect mismatch indices on real proof prefixes at:
      - `96B`
      - `112B`
      - `129B`
- [ ] Check whether mismatches are stable by byte or by segment.
- [ ] Only after that, design new segmented proof-prefix protection.
- [ ] Keep synthetic and real-proof error maps separate in analysis notes and benchmark outputs.
- [ ] Rebuild the real-proof error map after applying the body-gap decoupling that fixes `96B`.

#### P3.3 Segmented protection on real proof bytes
- [ ] Try segmented protection based on the real error map, not the synthetic one.
- [ ] Target order:
      - bring `96B` real proof branch to `partial_contract=True`
      - then bring `112B`
      - then bring `129B`
- [ ] Prefer local repairs that minimize collateral damage to header and message recovery.
- [ ] Reject any repair that improves one metric by collapsing another.

#### P3.4 Only then attempt blind full payload
- [ ] When `129B real proof prefix` passes stably, reconnect a full proof-bearing
      partial payload.
- [ ] Only after that, attempt blind `unpack()` and blind verify end-to-end.
- [ ] Do not skip directly from partial-prefix success to full blind verification.

### Blind-core stop criteria

Keep blind-core as future work if:
- runtime is still too heavy to iterate on,
- the real-proof branch cannot hold header and proof prefix simultaneously,
- or telemetry still does not show a stable error pattern.

Also stop escalation if:
- every new fix only trades errors between header and proof without net improvement,
- or benchmark cost becomes too high to support deliberate iteration.

Promote blind-core to a major future direction only if:
- real-proof `96B+` passes stably,
- `129B` real proof prefix can be recovered correctly and repeatably,
- and there is at least one blind payload contract that is close to end-to-end,
  not just a synthetic proxy.

---

## Immediate Next Steps

This is the best working order from the current state.

### Mainline
- [ ] Keep the main baseline clean and the paper-grade workflow stable.
- [ ] Finish the remaining paper-facing tables.

### Blind-core
- [ ] Re-validate the `96B` real-proof branch until one local contract is repeatable.
- [ ] Only after that, test the same contract on `112B` and `129B`.
- [ ] If no repeatable local contract exists, return to header-specific placement/coding before more segmented proof-prefix work.

### Next concrete blind-core run order
1. Re-run the `96B real proof` branch until the local contract is stable and repeatable.
2. If the contract is not repeatable, stop and redesign header-specific protection first.
3. If the contract is repeatable, test `112B`.
4. Then test `129B`.
5. Only then try new segmented protection for the remaining real-proof failures.

---

## Exit Conditions

## Exit to paper writing
- [ ] The main docs and benchmark outputs tell the same story.
- [ ] Paper-grade sections run through the runner without ambiguity.
- [ ] Claim-to-evidence mapping is stable.

## Exit to "blind-core is more than future work"
- [ ] The real-proof branch can hold header and proof prefix together at a meaningful level.
- [ ] `129B` real proof prefix can be recovered correctly and repeatably.
- [ ] There is at least one blind contract that is close to end-to-end, not just a synthetic proxy.

## Exit to "blind-core can influence the paper narrative"
- [ ] There is at least one repeatable real-proof result beyond `96B` with both header and proof-prefix success.
- [ ] The result survives rerun through benchmark code, not only one-off experiments.
- [ ] The blind-core claim can be stated without contradicting the frozen baseline.
