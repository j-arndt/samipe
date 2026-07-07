<!-- Copyright (c) 2026 Justin Arndt. All rights reserved. -->
# SAMIPE Technical Brief

**Self-Auditing, Mathematically Immune Processing Element** — a Lean
4-verified F2 algebraic firewall embedded in ARM's Custom Datapath Extension
(CDE, Armv8.1-M). A parity-check matrix `H` over GF(2) validates a state
vector `s` by checking `H·s = 0` in hardware, via parallel XOR reduction
trees, in a single clock cycle.

**Read this brief with the same discipline it is written in.** Every figure
below is tagged **proven** (a Lean 4 theorem, machine-checked, zero `sorry`),
**measured** (counted from the netlist or timed on this machine, reproducible
today), or **projected** (an engineering estimate for a named target node,
not yet synthesized or fabricated). Do not collapse these categories when
quoting this document.

---

## 1. Architecture Overview

### The paradigm shift: passive execution to self-auditing validation

Conventional processors execute whatever instruction stream they are handed.
Correctness of the *system invariant* — "is this state word one the policy
actually allows?" — is delegated to software: an assertion, a bounds check,
a comparison against a whitelist, running on the same core, trusted only
because the code path that wrote it is assumed bug-free. That assumption is
the attack surface. A heuristic planner, a learned controller, or a
compromised policy engine can produce a state word that looks legitimate to
every downstream consumer, because nothing *independent* ever inspects it.

SAMIPE inverts this. The system state register is intercepted by the CDE
coprocessor pipeline and validated by a piece of hardware that has no
execution path, no instruction stream, and no way to be talked out of its
answer — a fixed linear map over GF(2). Software above the intercept point
(policy engine, planner, learned controller, RTOS task) is **never trusted**;
its output state is treated as adversarial input to the firewall on every
check.

```
          untrusted / heuristic            |        mathematically immune core
                                           |
   agent policy engine                     |        F2 parity-check matrix H
   heuristic planners ---- state word ---->|------> H * s (mod 2) = syndrome
   learned controllers                     |            |
                                           |            v
   CX2 instruction path                   |        syndrome == 0?
   (ARM CDE, coprocessor p0)              |         /          \
                                           |      pass(1)     fail(0)
                                           |        |            |
                                           |    write Rd      assert NMI
                                           |                  to NVIC
                                           |
        HMAC-SHA256 audit chain <----------+--- records every check
        (impl/audit/)                      |    matrix loads + verdicts
```

The right-hand side of the intercept has no branch, no multiply, no
comparator microcode — it is a hard-wired linear operator. There is no
"logic bug" surface in the conventional sense: the operator either is `H` or
it is not, and that equality is checked, not assumed (see §3 and the RTL
equivalence discussion below). **Proven**: the hardware gate returns 1 iff
`H·s = 0` (`SAMIPE.samipe_cde_firewall_sound`, `proofs/SAMIPECore.lean`).
Every failed check simultaneously asserts a non-maskable interrupt and is
recorded in the HMAC-SHA256 audit chain — the verdict is both immediate and
independently re-verifiable after the fact.

### Why this matters for autonomous and agentic systems

The most consequential misuse case for the untrusted layer above the
intercept is an autonomous agent or learned controller emitting a state
transition that violates a safety invariant — not through malice
necessarily, but through the ordinary failure modes of heuristic search:
reward hacking, distribution shift, adversarial input, or a plain logic
error in a planner nobody formally verified. Software-side assertion loops
catch this *if* the assertion code itself is correct and *if* it runs before
the state is acted upon. SAMIPE removes both conditionals: the checker is
proven correct independent of what produced the state, and it sits in the
CDE pipeline ahead of the write-back, so a failing state never retires
silently.

---

## 2. ARM CDE Interface

### Armv8.1-M CDE coprocessor slots

The Custom Datapath Extension is Arm's mechanism for attaching customer-
defined combinational or pipelined logic to an Armv8.1-M core through a
coprocessor-style instruction interface, without modifying the core's
decode or register file. Up to eight CDE coprocessor slots (`p0`–`p7`) are
addressable; SAMIPE is assigned `p0` by default (`SAMIPE_COPROC_ID`, see
`impl/samipe.h`) but is not architecturally bound to that slot — the
interface controller parameterizes `COPROC_ID` (`rtl/samipe_interface_ctl.v`).

The interface controller (`samipe_interface_ctl.v`) is the pre-decode bridge
between the CDE port and the firewall engine. Its port list:

| Port | Direction | Width | Purpose |
|---|---|---|---|
| `cde_valid` | in | 1 | CDE instruction valid this cycle |
| `cde_opcode` | in | 4 | CDE opcode field |
| `cde_acc` | in | 32 | Accumulator input (`Rd` value) |
| `cde_imm` | in | 13 | Immediate operand (sub-operation selector) |
| `cde_rn` | in | 32 | Source register — the state word to validate |
| `cde_result` | out | 32 | Result written back to `Rd` |
| `cde_ready` | out | 1 | Controller ready for next instruction |
| `nmi_out` | out | 1 | Non-maskable interrupt to the NVIC |

Two sub-operations are decoded from `cde_imm`: `OP_VALIDATE` (`0x0000`) runs
the firewall against `cde_rn` and returns pass/fail; `OP_STATUS` (`0x0001`)
returns the last computed result without re-running a check, for
diagnostic read-back. An unrecognized immediate passes the accumulator
through unchanged rather than faulting — a deliberately conservative default
for a pre-production controller.

**Honesty note:** `samipe_interface_ctl.v` demonstrates CDE port mapping and
instruction decode; it has not been integrated with a real Armv8.1-M RTL
core. Wiring it into a licensee's specific core implementation is Days 1–30
work in the SOW (§7).

### CX2 instruction encoding

The CDE instruction family relevant here is `CX2` — a two-register,
immediate-carrying coprocessor instruction:

```
cx2  p<cp>, <Rd>, <Rn>, #<imm>
```

- `cp` — coprocessor number (`p0` for SAMIPE by default)
- `Rd` — destination/accumulator register (receives the pass/fail result)
- `Rn` — source register (the state word under test)
- `imm` — sub-operation selector (`0x0000` VALIDATE, `0x0001` STATUS)

The firewall's registered output means the result is available one cycle
after issue — `cde_result_out` is a clocked register in
`samipe_cde_firewall.v`, not a pure combinational output at the CDE
boundary. Software issuing `CX2` should account for this one-cycle
registration latency in addition to the checker's own zero-additional-cycle
combinational evaluation.

### ACLE intrinsics and the C driver

The Arm C Language Extensions (ACLE) define compiler intrinsics for CDE
instructions; where a toolchain's ACLE support for a given `CX2` shape is
unavailable, inline assembly is the fallback path, which is what the
reference driver in this repository uses today. `impl/driver.c` implements
`samipe_cx2()`:

```c
static inline uint32_t samipe_cx2(uint32_t state_val, uint32_t imm)
{
    uint32_t result;
    __asm__ volatile (
        "cx2 p0, %0, %1, #0x0000"
        : "=r" (result)     /* %0: output — Rd (result) */
        : "r"  (state_val)  /* %1: input  — Rn (state)  */
        :
    );
    return result;
}
```

The public API (`impl/samipe.h`) exposes four entry points built on this
primitive:

- `validate_system_state_hardware(state_val)` — single-state check
- `execute_secure_agent_trajectory(trajectory, len)` — per-step validation
  with early-exit on the first invariant violation (the agentic-safety
  entry point)
- `validate_batch(states, count, results)` — validates every element,
  does *not* short-circuit, useful for post-hoc audit of a full trajectory
- `samipe_read_status()` — diagnostic STATUS read-back via `OP_STATUS`

A production ACLE header (`__builtin_arm_cde_cx2`, or whatever a given
vendor toolchain names the generic `CX2` builtin) would replace the inline
assembly directly; the calling convention and immediate encoding are
unchanged.

---

## 3. H-Matrix Encoding

### Tiled Hamming(7,4) SEC-DED across four blocks

The default 32-bit configuration (`rtl/samipe_cde_firewall.v`,
`impl/firewall.py:default_32bit()`) tiles the classical Hamming(7,4)
parity-check structure across four contiguous 7-bit blocks of the 32-bit
state word (bits `[27:0]`) and adds a fourth row that is overall parity
across all 32 bits. This is the standard SEC-DED (single-error-correct,
double-error-detect) extension of Hamming(7,4).

Within each 7-bit block, using 1-indexed bit positions `1..7`, the three
classical Hamming parity rows check:

| Row | Checks 1-indexed positions where... | Positions (1-indexed) |
|---|---|---|
| `h0` | bit 0 of the index is set | {1, 3, 5, 7} |
| `h1` | bit 1 of the index is set | {2, 3, 6, 7} |
| `h2` | bit 2 of the index is set | {4, 5, 6, 7} |

Converted to 0-indexed positions within a block, these become `h0 = {0, 2,
4, 6}`, `h1 = {1, 2, 5, 6}`, `h2 = {3, 4, 5, 6}` — exactly the `ROW_0`,
`ROW_1`, `ROW_2` localparams in the RTL. Tiled at offsets 0, 7, 14, 21 across
the 32-bit word, each row picks up 16 taps total (4 per block x 4 blocks):

- **ROW_0** taps: `{0,2,4,6, 7,9,11,13, 14,16,18,20, 21,23,25,27}` — mask
  `0x0AB56AD5`
- **ROW_1** taps: `{1,2,5,6, 8,9,12,13, 15,16,19,20, 22,23,26,27}` — mask
  `0x0CD9B366`
- **ROW_2** taps: `{3,4,5,6, 10,11,12,13, 17,18,19,20, 24,25,26,27}` — mask
  `0x0F1E3C78`
- **ROW_3** (overall parity, SEC-DED extension): all 32 bits — mask
  `0xFFFFFFFF`

Bits `[31:28]` fall outside the three tiled Hamming blocks (which cover only
`[27:0]`) but are still covered by ROW_3's overall parity, so every bit in
the 32-bit word participates in at least one syndrome check. The exact tap
lists, mask values, and per-row descriptions are the machine-readable
contract in `rtl/netlist.json`, which is what the RTL-equivalence harness
(`impl/rtl_equiv.py`) checks against the Python reference — not a narrative
description, an actual entry-by-entry matrix comparison.

### Why this detects and corrects single errors, and detects double errors

The syndrome `(s0, s1, s2)` from a single 7-bit Hamming(7,4) block encodes
the 1-indexed *position* of a single flipped bit directly in binary: if bit
`k` (1-indexed) is corrupted, `s0` is bit 0 of `k`, `s1` is bit 1 of `k`,
`s2` is bit 2 of `k`. A nonzero 3-bit syndrome is therefore not just a
detection flag — it names the corrupted position, which is what "correction"
means for Hamming(7,4): flip the bit the syndrome names. All syndrome
computation here is a linear map over GF(2) (`H.mulVec s` in the Lean model,
`^(state & ROW_i)` — Verilog reduction-XOR — in the RTL), so this positional
decoding is exact, not heuristic.

The classical limitation of plain Hamming(7,4) is that it is blind to
*double*-bit errors within a block: two simultaneous flips can produce a
syndrome that is either zero (misread as "no error") or that names a *third*,
wrong position (misread as "single error, wrong correction"). ROW_3's
overall parity closes this gap. Any single-bit error flips overall parity
(odd number of flipped bits changes parity); any double-bit error, which the
per-block syndrome may or may not catch, is guaranteed to leave overall
parity even *only* when the flip count across the checked word is even —
which is exactly the double-error case a global parity bit is designed to
catch when combined with the positional syndrome from the Hamming rows. In
combination: `(s0, s1, s2)` locates and corrects a single-bit error inside a
block; if `(s0, s1, s2) = 0` but overall parity is nonzero, no single-block
Hamming error explains the observed corruption — the state is flagged
invalid without a (wrong) correction being applied. This is the standard
SEC-DED construction; SAMIPE's contribution is realizing it as a hardware
firewall gate rather than an error-correcting memory codec, and proving the
zero-syndrome-iff-valid property formally rather than asserting it.

**Proven** (generic over dimensions, not specific to this `H`):
`SAMIPE.samipe_cde_firewall_sound` — `cde_hardware_op H s = 1 ↔ H.mulVec s =
0`; `SAMIPE.checkInvariant_sound` / `checkInvariant_complete` — the
decidable Bool checker agrees with the syndrome exactly in both directions;
`SAMIPE.validateCDERun_sound` — the run-certificate master theorem: if a
CDE run certificate validates and its result token is `true`, the state
provably lies in `ker(H)`. All four theorems hold for *any* GF(2) matrix `H`
of any dimensions `m x n` — the specific tiled-Hamming choice for the
default 32-bit configuration is one instantiation, not a precondition of the
proofs. `samipe_configurable.v` exists precisely so a customer can load a
different `H` (their own invariant specification) without touching the
proof structure — see Days 1–30 in §7.

**Measured**: 20,000 random valid vectors (states in `ker(H)`) all produce
a zero syndrome; 20,000 random invalid vectors all produce nonzero syndrome;
5,000 adversarial single-bit flips injected into valid states are all
detected; every nonzero entry in `H` was individually exercised and shown to
flip its corresponding syndrome bit (100% failure-witness coverage, `80`
covered nonzero entries in the default 4x32 matrix — 16+16+16+32 across the four rows — `sim/functional_test.py`,
`test_failure_witness_coverage`).

---

## 4. Timing Analysis

The checker is purely combinational — there is no state machine, no
multi-cycle sequencing, no pipeline stage internal to the syndrome
computation itself. Each `syndrome[i]` is a `reduction_XOR(state_reg_val &
ROW_i)`, synthesized as a balanced binary XOR tree of depth `ceil(log2(row
weight))`.

| Syndrome row | Tap (row weight) count | XOR tree depth |
|---|---|---|
| `syndrome[0]` (ROW_0, tiled Hamming h0) | 16 | 4 |
| `syndrome[1]` (ROW_1, tiled Hamming h1) | 16 | 4 |
| `syndrome[2]` (ROW_2, tiled Hamming h2) | 16 | 4 |
| `syndrome[3]` (ROW_3, overall parity) | 32 | **5** |

`syndrome[3]` — the 32-input overall-parity reduction — is the **critical
path**: `ceil(log2(32)) = 5` levels of two-input XOR gates, one level deeper
than the three 16-tap Hamming rows (`ceil(log2(16)) = 4`). After the four
syndrome bits are available, a reduction-OR tree determines whether any
syndrome bit is set (`syndrome_zero` in the RTL is a 4-input equality-to-zero
check, functionally an OR-of-4 gated to the NMI path): `ceil(log2(4)) = 2`
additional gate levels.

**Total combinational depth: `5 (XOR, syndrome[3]) + 2 (OR, NMI reduction) =
7` gate levels** — this is the number reported in `rtl/gate_report.json`
(`max_xor_tree_depth: 5`, `nmi_or_tree_depth: 2`,
`total_combinational_depth: 7`) and in `rtl/netlist.json`'s
`xor_tree.max_depth`.

**Single-cycle guarantee.** Because the entire syndrome-plus-NMI-reduction
path is combinational logic with no internal clocked stage, the checker
settles to a stable output within one clock period, for *any* clock
frequency at which the target technology's 7-gate-deep critical path meets
timing closure. This is a claim about logical topology (a hard, technology-
independent lower bound: 7 gate levels between input and output, period),
not a specific nanosecond figure — the actual delay in picoseconds/
nanoseconds depends on the cell library and process node the customer
targets, which is exactly what Days 31–60 of the SOW (§7) establishes.
**Measured** (from the netlist, reproducible today): the depth-7, single-
critical-path topology. **Not measured**: post-synthesis, post-place-and-
route timing on any specific process node — see §8.

The `samipe_interface_ctl.v` wrapper adds one clock cycle of register
latency on top of this (the firewall's `cde_result_out` is itself a clocked
output, and the interface controller re-registers it), which is a
pipelining choice for CDE handshake compliance, not a limitation of the
combinational checker core.

---

## 5. Gate Count Breakdown

| Component | Count | Description |
|---|---|---|
| XOR2 gates (syndrome layer) | **76** | Two-input XOR gates forming the four reduction trees: 15 per 16-tap row x 3 rows (45) + 31 for the 32-tap parity row = 76 |
| OR2 gates (NMI reduction) | **3** | Two-input OR gates reducing the 4-bit syndrome to a single NMI assert signal |
| **Total 2-input gates** | **79** | Full combinational checker, default 4x32 configuration |

This is a **measured** figure — a direct count of two-input logical gates
in the hand-written synthesizable netlist (`rtl/samipe_cde_firewall.v`,
cross-checked against `rtl/gate_report.json` and `rtl/netlist.json`), *not*
a post-synthesis mapped-cell-library gate count. An actual Yosys / Synopsys
DC / Cadence Genus synthesis run against a specific standard-cell library
will produce a different mapped gate count (technology cells rarely map
1:1 to abstract 2-input XOR/OR primitives — many libraries have 3- and
4-input XOR cells, for instance, which would *reduce* the mapped count
below 79). **The 79-gate, depth-7 figure is a hard lower bound on logical
complexity**, independent of target library — see the honesty box in
`README.md`.

For scale, the same benchmark harness that produces the 79-gate figure for
the default 4x32 matrix also reports smaller configurations exercised in
this repo: an 11-gate checker for the 3x7 pure Hamming(7,4) matrix (9 XOR2 +
2 OR2, depth 4), and a 15-gate checker for a 16x16 identity matrix (0 XOR2 —
identity rows are single-tap, i.e. wires, not gates — + 15 OR2, depth 5).
These numbers scale with matrix dimensions and row weight, not with a fixed
architectural overhead, which is the basis for the PPA scaling discussion in
§8.

### Comparison to typical CDE accelerator blocks

Public Arm CDE reference material and third-party CDE accelerator writeups
(cryptographic primitives, DSP kernels, custom ALU extensions) typically
describe blocks in the hundreds to low thousands of gates, often with
multi-cycle latching for multiply-accumulate or lookup-table stages. SAMIPE
sits at the extreme low end of that range — 79 gates is smaller than a
single 32-bit adder's carry chain in most cell libraries — while remaining
strictly single-cycle and requiring no internal state beyond the CDE
protocol's own output register. This is a direct consequence of the
architecture: a parity-check firewall is a linear map, and linear maps over
GF(2) synthesize to XOR trees with no multiplier, no memory, and no control
FSM. The tradeoff is scope: SAMIPE checks one class of invariant (GF(2)
linear codes over a state vector) extremely cheaply; it is not a general-
purpose coprocessor.

---

## 6. Target Buyer Blueprints

Each blueprint below states the bottleneck the target organization plausibly
faces, the specific value SAMIPE offers against it, and what is proven vs.
what a partner engagement would need to characterize. None of these claims
assume a relationship with the named organization exists; they are framed as
technical fit arguments for evaluation, structured the same way the sister
QLDPC decoder-certification project (`../qldpc/docs/technical_brief.md`)
frames its own buyer sections.

### ARM Holdings — architecture IP licensing, extending the Cortex-M85 security story

**Fit.** Arm's Armv8.1-M / Cortex-M85 line already ships TrustZone, MPU, and
PACBTI as layered security primitives — all software-configurable, all
running on the same execution core they protect. SAMIPE is a complementary,
*orthogonal* trust primitive: a hardware element with no execution path of
its own, sitting in the CDE coprocessor slot Arm's own architecture defines
for exactly this kind of customer extension. It does not compete with
TrustZone or PACBTI; it adds a class of guarantee — "this state word
satisfies an algebraic invariant, full stop, independent of what code path
produced it" — that neither addresses.

**Value to Arm.** A reference CDE macro with a machine-checked soundness
proof (zero `sorry`, standard axioms only) is marketing and technical
collateral for the CDE ecosystem story: "here is what a rigorously verified
third-party CDE extension looks like, and here is the toolchain (Lean 4 +
RTL equivalence harness) that gets you there." Licensing or reference-
integrating SAMIPE into Cortex-M85-adjacent security documentation
strengthens Arm's pitch to safety-critical customers (automotive,
industrial, medical) evaluating Armv8.1-M for invariant-checked control
loops.

**What is proven vs. what integration requires.** Proven: the firewall
soundness theorems, generic over any GF(2) matrix. Measured: the 79-gate/
depth-7 topology for the reference 4x32 matrix. Not yet done: integration
with a real Cortex-M85 (or any specific Armv8.1-M) RTL core — the interface
controller is a stub demonstrating port mapping, not a validated core
integration. That is exactly the Days 1–30 deliverable in §7.

### Apple — M-series secure enclave hardening, Neural Engine state validation

**Fit.** Apple's Secure Enclave and Neural Engine both maintain internal
state that must satisfy invariants no untrusted code path should be able to
violate — key material integrity in the enclave, activation/weight buffer
consistency in the Neural Engine's on-die state during inference. Apple
does not use Armv8.1-M CDE in shipping M-series silicon today; the fit
argument here is architectural transferability, not an existing integration
path. The underlying primitive — a small, fixed, hardware-verified linear
checker gating a state write-back — is instruction-set-independent. The
GF(2) syndrome-check core (`samipe_cde_firewall.v`) has no Armv8.1-M-specific
logic in its combinational path; only the interface controller
(`samipe_interface_ctl.v`) is CDE-shaped, and that layer is the one that
would be re-targeted to whatever coprocessor or custom-instruction hook a
given Apple silicon team's core supports.

**Value to Apple.** Neural Engine activation corruption (from a soft error,
a firmware bug, or a compromised model-loading path) that goes undetected
until a downstream consumer misbehaves is a class of failure a cheap,
proven, always-on hardware syndrome check can close at the point of write-
back — before the corrupted state ever leaves the checked boundary. The same
argument applies to Secure Enclave state transitions where key-material
consistency is exactly the kind of linear-algebraic invariant a parity-check
matrix expresses naturally.

**What is proven vs. what integration requires.** Proven and measured
components transfer directly (the soundness theorems and gate-level
topology are ISA-agnostic). Not done, and explicitly out of scope for this
repository: any Apple-silicon-specific interface mapping, any Secure Enclave
or Neural Engine architectural detail (none of which is public or assumed
here), and any statement that Apple uses or has evaluated this technology.
This section is a fit argument for outreach, not a claim of an existing
relationship.

### Qualcomm — Snapdragon edge AI safety for autonomous systems

**Fit.** Snapdragon platforms targeting robotics, drones, and automotive
ADAS increasingly run learned controllers and planners on-device, at the
edge, where the "trusted supervisor" for a safety invariant cannot be a
cloud round-trip — it has to be local and fast. SAMIPE's stated use case
(`impl/samipe.h`'s `execute_secure_agent_trajectory`) is exactly this: per-
step hardware validation of an autonomous agent's planned state trajectory,
with immediate hardware NMI and audit-chain recording on the first
violation, no software round-trip required.

**Value to Qualcomm.** 350-520x fewer cycles per invariant check (§8; a
software-vs-hardware comparison, not a claim about Qualcomm's specific
software stack) translates directly into either lower power draw for the
same check rate or a higher achievable check rate for the same power
envelope — both are first-order concerns for battery- or thermally-
constrained edge autonomy platforms. The HMAC-SHA256 audit chain
(`impl/audit/`) additionally gives a tamper-evident record of every
validation performed on-device, which is relevant to any safety case that
needs to reconstruct "what did the system check, and when" after an
incident.

**What is proven vs. what integration requires.** Proven: firewall
soundness. Measured: gate count, depth, and the software-loop-vs-hardware-
claim cycle comparison (§8 — the software side is real wall-clock
measurement; the hardware side is combinational-depth analysis, not
silicon). Not done: any Snapdragon-specific CDE or coprocessor-equivalent
integration, any autonomous-system-specific invariant matrix design (a
robotics or ADAS safety invariant is not the tiled-Hamming SEC-DED matrix
shipped by default — it would be a customer-supplied `H`, loaded via
`samipe_configurable.v`, and proven sound for that specific matrix in Lean
as part of the engagement).

### AWS — Graviton cloud infrastructure, zero-overhead tenant isolation

**Fit.** Graviton is Arm-based server silicon; multi-tenant cloud
infrastructure has a standing interest in isolation guarantees that do not
depend on the correctness of a hypervisor's or guest kernel's software
enforcement path alone. A hardware-checked invariant on state transitions
relevant to isolation boundaries (e.g., a tagged-state or capability-style
invariant expressible as a GF(2) linear code) is a defense-in-depth layer
that runs regardless of what the software stack above it is doing —
including if that software stack itself is compromised.

**Value to AWS.** "Zero-overhead" here is the honest framing: the checker
adds no cycles beyond the single cycle it always costs (§4), so a per-
transition validation gate does not compete for the multi-cycle software
assertion budget a hypervisor would otherwise need. At cloud scale, cycles
saved per tenant-isolation check multiply directly into either lower
aggregate CPU spend on isolation enforcement or headroom to check more
invariants at the same budget. The audit chain's independent re-
verifiability is also relevant to any customer-facing attestation or
compliance story around what isolation checks actually ran.

**What is proven vs. what integration requires.** Proven: the algebraic
soundness of the checker for any customer-specified isolation invariant
expressible as a GF(2) linear code. Not done: any Graviton-specific
integration (Graviton's actual core microarchitecture and any CDE-equivalent
extension mechanism it does or doesn't expose are not addressed by this
repository), and no claim that AWS uses or has evaluated this. Framed as a
fit argument, matching the framing used for Apple above.

### SEEQC — cryogenic SFQ integration

**Fit.** SEEQC's cryogenic digital control layer runs Single Flux Quantum
(SFQ) logic beside superconducting qubits at millikelvin temperatures, where
every additional gate has a thermal and area cost that has no equivalent at
room temperature. SAMIPE's 79-gate combinational core is small enough to be
a plausible candidate for direct SFQ-cell mapping — the same order of
magnitude as the checker macros already explored for cryogenic QLDPC decoder
certification in the companion project at `../qldpc/` (see
`../qldpc/docs/technical_brief.md`, §1 "SEEQC — cryogenic on-chip
firewall"), which reports measured gate counts of 1,038 ([[72,12,6]] code)
and 2,082 ([[144,12,12]] code) two-input gates for its own Lean-verified
syndrome checkers at combinational depths of roughly 10 and 11 gate levels
respectively.

**Cross-reference: QLDPC decoder certification.** The `qldpc` repository is
the more directly relevant SEEQC engagement for quantum error-correction
workloads specifically — it certifies BP-OSD / clustering decoder outputs
against bivariate-bicycle-code parity checks with a two-sided (success *and*
failure) certificate scheme, proven in Lean 4 with the same zero-`sorry`,
standard-axioms discipline used here. SAMIPE is the more general-purpose
sibling: the same GF(2)-linear-checker architecture, applied to an arbitrary
customer-specified state invariant rather than specifically to QLDPC
syndrome decoding, and packaged for the classical Armv8.1-M CDE interface
rather than a bespoke SFQ syndrome bus. A SEEQC engagement touching both the
classical control-plane state (SAMIPE) and the quantum syndrome-decode path
(qldpc) would share the underlying Lean proof methodology and the RTL-
equivalence verification discipline, even though the two checkers protect
different layers of the stack.

**Value to SEEQC.** A classical-side firewall (SAMIPE) validating control-
plane state transitions in the room-temperature-to-cryostat boundary
hardware, paired with a syndrome-decode certifier (qldpc) validating the
quantum error-correction path itself, is a coherent two-layer trust story:
neither the classical control logic nor the decoder output reaching the
qubits is trusted by assumption — both are gated by a proven, small,
independently-checkable hardware element.

**What is proven vs. what a SEEQC engagement would characterize.** Proven:
firewall soundness (SAMIPE) and, in the companion repo, decoder-certificate
soundness (qldpc) — both generic Lean theorems, not SEEQC-specific.
Measured: gate counts and combinational depth for the reference
configurations in both repositories, on an abstract 2-input-gate netlist —
*not* mapped to any SFQ cell library. Explicitly not done, in either
repository: SFQ cell-library mapping, cryogenic timing closure, or any power
estimate at 10 mK — the qldpc brief states this plainly ("we do not claim a
power figure — characterizing draw on SEEQC's cells is Milestone 2 work"),
and the same honesty standard applies here. SAMIPE has not been synthesized
against RSFQ/ERSFQ libraries at all as of this brief; that would be new
scope, not a reuse of the qldpc project's existing SFQ synthesis exploration
(`../qldpc/simulations/synth_sfq.ys`).

---

## 7. 90-Day Statement of Work

A fixed-scope, fixed-fee integration engagement taking a customer from
"evaluated the open-source repository" to "production-ready, target-cell-
mapped macro with a validated test suite." Structured in three 30-day
milestones, mirroring the engagement model used for the companion QLDPC
decoder-certification project.

### Days 1–30 — Matrix ingestion and port mapping

- Ingest the customer's actual invariant specification and express it as a
  GF(2) parity-check matrix `H` (or a small family of matrices, if the
  customer's invariant is context-dependent — e.g., different `H` per
  operating mode, loaded at runtime via the `samipe_configurable.v` path).
- Instantiate the generic Lean 4 soundness proofs
  (`samipe_cde_firewall_sound`, `checkInvariant_sound/complete`,
  `validateCDERun_sound`) against the customer's specific matrix dimensions
  `m x n`, producing a customer-specific but machine-checked proof artifact
  — not a re-derivation from scratch, since the theorems are already generic
  over `m, n`.
- Define the CDE port mapping for the customer's specific Armv8.1-M core
  implementation: coprocessor slot assignment, opcode/immediate encoding for
  any customer-specific sub-operations beyond VALIDATE/STATUS, and NMI
  routing into the customer's actual NVIC configuration.
- **Deliverable:** customer-specific Lean proof build, an updated netlist
  (`netlist.json`-equivalent) for the customer's matrix, and a written CDE
  interface specification for their core.

### Days 31–60 — Target-cell synthesis and timing

- Retarget the RTL from an abstract 2-input-gate description to the
  customer's actual synthesis target: a specific CMOS standard-cell library,
  FPGA LUT fabric, or (per the SEEQC blueprint above) an SFQ/ERSFQ cell
  library.
- Run the customer's synthesis toolchain (Yosys, Synopsys DC, Cadence Genus,
  or an FPGA vendor's place-and-route flow) to produce a real mapped gate
  count and, for the first time in the engagement, a timing-closed
  critical-path delay at the customer's target clock frequency.
- Produce the first power estimate for the customer's process node —
  something this repository explicitly does not claim today (see §8).
- **Deliverable:** synthesis/mapping scripts for the customer's target,
  timing closure report, first power estimate.

### Days 61–90 — Testbench, audit chain, and handoff

- Deliver a cocotb or SystemVerilog testbench achieving 100% failure-
  witness-injection coverage against the customer's matrix — every nonzero
  entry in the customer's `H` individually exercised and confirmed to flip
  its corresponding syndrome bit, matching the coverage discipline already
  demonstrated in `sim/functional_test.py` for the reference matrix.
- Integrate the HMAC-SHA256 audit chain (`impl/audit/`) with the customer's
  key-management practice (replacing the disclosed development key,
  `samipe-dev-key-NOT-FOR-PRODUCTION`, with a real secret) and validate
  tamper-detection against the customer's actual logging pipeline.
- Hand off a pre-validated macro package: RTL, proofs, testbench, timing/
  power report, and integration documentation, ready for tapeout or
  bitstream inclusion.
- **Deliverable:** full test suite with coverage report, integrated audit
  chain, complete macro handoff package.

Commercial terms, evaluation-sandbox scope, and pricing tiers for this
engagement are in [`commercial_evaluation.md`](commercial_evaluation.md).

---

## 8. PPA Projections

Power, Performance, and Area are treated with three distinct confidence
levels below — **measured** (from the netlist, today), **proven** (a Lean
theorem, a claim about logical structure, not physical characteristics), and
**projected** (an engineering estimate for a named target node, explicitly
not yet synthesized or fabricated). Do not read a projected figure as a
measured one.

### Area — projected

The measured gate count for the default 4x32 configuration is **79 two-
input gates** (76 XOR2 + 3 OR2, §5). Using representative 2-input XOR2 and
OR2 standard-cell areas on a modern 7nm process (XOR2 cells typically run
larger than a basic NAND2/OR2 due to their internal transistor count — order
of magnitude 1.5-2x a minimum-size 2-input gate in most 7nm libraries), a
back-of-envelope projection for the combinational core alone lands in the
**~400-600 um² range**. This is explicitly a projection, not a placed-and-
routed area report: real area depends on the specific 7nm PDK, cell library
variant (high-density vs. high-performance), routing overhead, and any
buffering inserted to meet the depth-7 critical path's fanout requirements.
A real synthesis run (Days 31-60 of the SOW) is the only way to convert this
into a number a tapeout decision can rely on. Note also that this figure
covers the `samipe_cde_firewall` combinational core only — the interface
controller (`samipe_interface_ctl.v`) and any customer-specific CDE
port-mapping logic are additional area not included in this 400-600 um²
estimate.

### Power — projected

No power analysis has been run for this design — the same honesty standard
applied to the companion QLDPC project's SEEQC section applies here.
Qualitatively: a 79-gate combinational block with no clocked internal state
(beyond the single output register in `samipe_cde_firewall_sound`'s
registered result path) and a shallow depth-7 critical path is a small
dynamic-power contributor relative to a typical CPU core's per-cycle switching
activity — most of a modern core's power budget is dominated by much larger
structures (register files, caches, execution units) that dwarf a 79-gate
checker. A **projected sub-microwatt** dynamic power figure at moderate
clock frequencies (low hundreds of MHz to a few GHz, typical for an
Armv8.1-M target) is a reasonable order-of-magnitude estimate given the gate
count and switching activity of a checker that only toggles when a CDE
VALIDATE instruction actually issues — but this is an estimate, not a
SPICE-simulated or silicon-measured number. A real power estimate,
technology- and activity-factor-specific, is a Days 31-60 SOW deliverable
(§7), matching the qldpc project's own stated position that "characterizing
draw on [a partner's] cells is Milestone 2 work."

### Performance — measured (topology) / projected (frequency-dependent latency)

**Measured, and technology-independent:** the checker is single-cycle at
any target clock frequency, because its logical critical path is a fixed 7
gate levels (§4) — this is a statement about combinational depth, true
regardless of what process node or cell library eventually implements it.
Any clock period long enough for 7 gate delays plus registration overhead to
settle meets timing; there is no multi-cycle sequencing to accelerate or
degrade with frequency scaling.

**Projected, frequency-dependent:** the *absolute* nanosecond latency of
that single cycle (i.e., what clock frequency the depth-7 path actually
supports before failing timing closure) depends entirely on the target
technology's gate delay and any buffering/routing parasitics — figures this
repository does not claim because they require an actual synthesis and
timing-closure run against a specific PDK. What can be stated with
confidence, because it follows directly from the depth-7 topology and not
from any process assumption: whatever clock frequency the customer's core
already runs at, the checker adds **zero additional cycles** to a state
validation, versus the 350-520 cycles measured for an equivalent software
assertion loop on this project's reference benchmark
(`impl/bench.py`, `impl/results/benchmark.json` — a real wall-clock Python/
numpy measurement compared against the combinational single-cycle claim,
not measured silicon on the hardware side). That comparison yields the
**350-520x** speedup figure quoted throughout this project's materials.

| PPA dimension | Status | Figure |
|---|---|---|
| Gate count (default 4x32) | **measured** | 79 two-input gates (76 XOR2 + 3 OR2) |
| Combinational depth | **measured** | 7 gate levels |
| Firewall soundness | **proven** (Lean 4) | `H·s = 0 ↔` hardware gate returns 1, for any `H` |
| Area, 7nm | **projected** | ~400-600 um² (combinational core only) |
| Power, moderate clock | **projected** | sub-microwatt, order-of-magnitude estimate |
| Cycles per check | **measured (topology)** | 1, at any target frequency |
| Absolute latency (ns) | **not yet established** | requires target-node synthesis (SOW Days 31-60) |
| Speedup vs. software loop | **measured** (software side) / **claimed** (hardware side) | 350-520x |

---

*This brief pairs with [`commercial_evaluation.md`](commercial_evaluation.md)
for evaluation terms and pricing, and with the top-level
[`README.md`](../README.md) "honesty box" for the complete list of trust-
boundary caveats governing every claim in this project.*
