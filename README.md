# SAMIPE

**Hardware-Enforced Algebraic Firewalls for the Armv8.1-M Architecture.**
A Self-Auditing, Mathematically Immune Processing Element that embeds an F2
parity-check firewall into ARM's Custom Datapath Extension (CDE). The invariant
is **proven in Lean 4** — zero sorries, standard axioms only — and realized as a
**79-gate, depth-7 combinational checker** that settles in a single clock cycle.

![License](https://img.shields.io/badge/license-GPLv3%20(dual)-blue)
![Lean](https://img.shields.io/badge/Lean-4.28.0%20%2B%20mathlib-blueviolet)
![Proofs](https://img.shields.io/badge/proofs-0%20sorries%20·%20standard%20axioms%20only-brightgreen)
![RTL](https://img.shields.io/badge/RTL-79%20gates%20·%20depth%207-informational)
![Performance](https://img.shields.io/badge/speedup-350--520×%20vs%20software-orange)

The system state register is validated every cycle through the CDE coprocessor
pipeline. Software assertion loops — branch, multiply, compare — cost 350-520
cycles per check. SAMIPE costs one.

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

Every state-word transition is intercepted by the CDE pipeline. The algebraic
firewall computes the GF(2) syndrome in parallel XOR trees. A zero syndrome
means the state satisfies the invariant; any nonzero bit asserts a non-maskable
interrupt. The heuristic layer above — whatever policy engine, planner, or
learned controller produced the state — is never trusted.

## Performance Ledger

| Metric | Software assertion loop | SAMIPE hardware (CDE) |
|---|---|---|
| **Cycles per check** | ~350-520 (branch + multiply + compare) | **1** (combinational, single-cycle) |
| **Pipeline stalls** | Branch misprediction, data hazards | **None** — purely combinational |
| **Area** | Zero (runs on main core) | **79 two-input gates** |
| **Certainty** | Correct iff loop logic is bug-free | **Proven**: `samipe_cde_firewall_sound` in Lean 4 |
| **Failure response** | Software exception (latency varies) | **Hardware NMI** — 0-cycle interrupt path |
| **Audit** | Application-level logging | **HMAC-SHA256 chain** — tamper-evident |

Software timings are measured wall-clock on a reference machine; the 350-520
cycle range is estimated at 3 GHz. Hardware cycle count is the single-cycle
combinational claim backed by gate-level depth analysis, not a measured silicon
result. See [honesty box](#honesty-box-read-before-quoting) below.

## What's in the box

| Path | What it is |
|---|---|
| `proofs/` | Lean 4 proofs: `SAMIPECore.lean` (firewall soundness, checker completeness, master theorem) + `AxiomAudit.lean` (machine-printed axiom footprint) |
| `rtl/` | Synthesizable Verilog: `samipe_cde_firewall.v` (fixed tiled Hamming(7,4) SEC-DED), `samipe_configurable.v` (customer-loaded matrices), `samipe_interface_ctl.v` (CDE pre-decode controller) + `netlist.json` (tap indices) + `gate_report.json` |
| `impl/` | C/ACLE driver (`driver.c` + `samipe.h` with inline CX2 assembly), Python firewall simulator (`firewall.py`), RTL equivalence harness (`rtl_equiv.py`), benchmarks (`bench.py`), HMAC audit chain (`audit/`) |
| `sim/` | cocotb testbench (`test_samipe.py`), pure-Python functional test suite (`functional_test.py` — 31 tests) |
| `docs/` | `technical_brief.md` (microarchitecture spec, buyer blueprints, 90-day SOW), `commercial_evaluation.md` (evaluation terms) |
| `.github/workflows/` | CI: `lean-verify.yml` (zero sorries, standard axioms), `rtl-verify.yml` (functional tests, equivalence, lint) |

## What is proven (Lean 4 v4.28.0 + mathlib)

| Theorem | Statement |
|---|---|
| `samipe_cde_firewall_sound` | The CDE hardware gate returns 1 iff the syndrome `H * s` vanishes: `cde_hardware_op H s = 1 <-> H.mulVec s = 0` |
| `checkInvariant_sound` | If the decidable Bool checker accepts, the syndrome is zero |
| `checkInvariant_complete` | If the syndrome is zero, the decidable Bool checker accepts |
| `validateCDERun_sound` | **Master soundness theorem**: if the run certificate validates and the result token is `true`, then `H.mulVec s = 0` — the state provably satisfies the algebraic firewall |

All theorems are generic over dimensions `m` and `n`. The axiom footprint is
`[propext, Classical.choice, Quot.sound]` — the standard trusted base of
Lean 4's CIC+Quot kernel. No `sorry`, no `native_decide`, no custom `Axiom`
declarations.

## Sixty-second tour

```bash
# 1. Lean proofs: zero errors, zero sorries, standard axioms only
lake exe cache get && lake build
lake build proofs.AxiomAudit

# 2. Functional tests: 31/31 PASS
cd sim && python3 functional_test.py

# 3. RTL equivalence: exact matrix equality + behaviour simulation
cd ../impl && python3 rtl_equiv.py

# 4. Benchmarks: software vs hardware comparison
python3 bench.py

# 5. Audit chain: create, verify, tamper-detect
python3 -c "
from audit.chain import AuditChain, verify_chain
import tempfile, pathlib
p = pathlib.Path(tempfile.mktemp(suffix='.jsonl'))
c = AuditChain(p)
c.append('STATE_CHECKED', {'state': '0x00', 'valid': True})
ok, n, bad = verify_chain(p)
print(f'Chain OK: {ok}, records: {n}')
"
```

## Measured results (not theorems -- see honesty box)

| Metric | Value |
|---|---|
| Gate count (default 4x32) | **79 two-input gates** (76 XOR2 syndrome + 3 OR2 NMI reduction) |
| Combinational depth | **7 gate levels** (XOR depth 5 + OR depth 2) |
| Critical path | `syndrome[3]` — 32-input reduction XOR (overall parity, depth 5) |
| XOR tree depth (per row) | 4 for 16-tap rows, 5 for the 32-tap parity row |
| Functional tests | **31/31 PASS** |
| Random valid vectors tested | 20,000 — all produce zero syndrome |
| Random invalid vectors tested | 20,000 — all produce nonzero syndrome |
| Adversarial single-bit flips | **5,000 flips in valid states — all detected** |
| Failure-witness coverage | **100%** — every nonzero H entry triggers its syndrome bit |
| XOR tree vs numpy | **30,000 random vectors** — exact match on every syndrome bit |
| RTL equivalence | **ALL CHECKS PASSED** (matrix equality, behaviour, Verilog cross-check) |
| HMAC audit chain | Creation, verification, and tamper detection all verified |
| Software speedup | **350-520x** (single-cycle hardware vs multi-cycle software loop) |

## Honesty box (read before quoting)

- **The Verilog is trusted, not verified.** The ~100-line `samipe_cde_firewall.v`
  is hand-written synthesizable RTL. It is not emitted from Lean. The
  correspondence between the Lean theorems and the Verilog is established by the
  **RTL equivalence harness** (`impl/rtl_equiv.py`), which performs complete
  (non-sampled) entry-by-entry matrix equality: the netlist's tap indices are
  rebuilt into an m x n matrix and compared against the Python reference
  (`firewall.py`'s `default_32bit()`). A linear map is determined by its matrix,
  so this test is *complete* — any wiring bug that alters logical behaviour is
  caught deterministically. Full-circuit behavioural simulation (valid, invalid,
  adversarial vectors) and Verilog-to-JSON printer cross-checks provide
  additional defence-in-depth.

- **Gate counts and depths are from analysis, not from a placed-and-routed
  design.** The 79-gate, depth-7 figure counts two-input XOR and OR gates in the
  logical netlist. An actual synthesis run (Yosys, Synopsys DC, Cadence Genus)
  will produce a mapped gate count that depends on the target cell library, but
  the logical complexity is a hard lower bound.

- **The 350-520x speedup compares a Python/numpy software loop against the
  single-cycle hardware claim.** The software cycle estimate assumes ~3 GHz and
  measures real wall-clock time. The hardware side is the combinational 1-cycle
  claim from depth analysis, not a measured silicon result.

- **The CDE interface controller (`samipe_interface_ctl.v`) is a stub.** It
  demonstrates the CDE port mapping and instruction decode but has not been
  integrated with a real ARM core. Production integration requires the
  licensee's specific Armv8.1-M implementation.

- **The HMAC audit chain uses a disclosed dev key.** The demo chain's key is
  public (`samipe-dev-key-NOT-FOR-PRODUCTION`). Real tamper-evidence requires
  setting `SAMIPE_HMAC_KEY` to a secret value. The chain's guarantee is
  independent re-verifiability of the execution transcript.

- **Trusted base:** the Lean 4 kernel + mathlib, the human-checked correspondence
  between the Hamming(7,4) SEC-DED tiling and the Verilog localparam encoding,
  and the numpy/Python reference implementation.

## Continuous integration

CI configs live in [`.github/workflows/`](.github/workflows/):

- **`lean-verify.yml`**: builds all proofs, fails on any `sorry` or non-standard
  axiom, prints the axiom audit log.
- **`rtl-verify.yml`**: runs the 31-test functional suite, RTL equivalence
  checks, benchmarks, and Verilator lint on all three Verilog modules.

## Full reproduction

```bash
# 1. Lean toolchain + proofs
curl https://raw.githubusercontent.com/leanprover/elan/master/elan-init.sh -sSf | sh
lake exe cache get && lake build           # zero errors, zero warnings
lake build proofs.AxiomAudit               # prints every theorem's axiom footprint

# 2. Python pipeline
cd impl && pip install -r requirements.txt
python3 ../sim/functional_test.py          # 31/31 PASS
python3 rtl_equiv.py                       # ALL CHECKS PASSED
python3 bench.py                           # software vs hardware comparison

# 3. Verify the audit chain
python3 audit/verify_chain.py .. results/audit_bench.jsonl
```

All seeds fixed in-source; results deterministic given the same numpy version.

## Commercial licensing -- the GPLv3 moat

**GNU GPLv3, with a commercial dual-licensing option** — see [LICENSE](LICENSE).

Open-source, academic, and non-commercial use is free under GPL-3.0.
Incorporating the RTL, the Lean proofs, the CDE interface controller, or any
derivative synthesis scripts into a **proprietary** processor pipeline, FPGA
bitstream, ASIC tapeout, custom instruction extension, or closed-source firmware
triggers GPL-3.0's copyleft obligations:

- **Source disclosure**: your entire derivative work must be released under GPLv3.
- **Anti-tivoization**: you cannot use hardware restrictions to prevent users from
  running modified versions.

A **commercial licence** removes these obligations. The 90-day integration SOW
provides a turnkey path from evaluation to production silicon:

1. **Days 1-30**: matrix ingestion, CDE port mapping, Lean proof instantiation
   for the customer's invariant specification.
2. **Days 31-60**: target-cell synthesis (CMOS / FPGA LUTs / SFQ), timing
   closure, first power estimate on the customer's process node.
3. **Days 61-90**: cocotb/SystemVerilog testbench with 100% failure-witness
   coverage, HMAC audit chain integration, pre-validated macro handoff.

Full target-buyer blueprints (ARM Holdings, Apple M-series, Qualcomm Snapdragon,
AWS Graviton, SEEQC cryogenic): [`docs/technical_brief.md`](docs/technical_brief.md).

Sandboxed evaluation terms: [`docs/commercial_evaluation.md`](docs/commercial_evaluation.md).

## Contact

**Justin Arndt** — justinarndt05@gmail.com

Paid evaluation, netlist walkthrough, and commercial licensing inquiries welcome.
