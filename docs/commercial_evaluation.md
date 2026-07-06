<!-- Copyright (c) 2026 Justin Arndt. All rights reserved. -->
# SAMIPE Commercial Evaluation

Terms and scope for evaluating SAMIPE — the Self-Auditing, Mathematically
Immune Processing Element — ahead of a commercial licensing decision. This
document governs what an evaluator may do with the repository under the
existing GPLv3 grant, what additionally requires a commercial arrangement,
and the pricing structure for moving from evaluation to production
integration.

Read alongside [`technical_brief.md`](technical_brief.md) (architecture,
buyer blueprints, 90-day SOW, PPA projections) and the top-level
[`README.md`](../README.md) "honesty box," which lists every caveat
governing the claims made about this project. Nothing in this document
overrides those caveats.

---

## 1. Overview

SAMIPE is dual-licensed: GNU GPLv3 for open-source, academic, and non-
commercial use, with a separate commercial license available for any
proprietary integration (see [`LICENSE`](../LICENSE)). This evaluation
document exists because a semiconductor company, silicon IP integrator, or
systems house needs a concrete, time-boxed way to assess the technology
against their own invariant-checking requirements *before* committing to a
commercial license or a 90-day integration Statement of Work (SOW).

**What the evaluation includes:**

- The complete Lean 4 proof suite — `SAMIPECore.lean` (firewall soundness,
  checker completeness, the run-certificate master theorem) and
  `AxiomAudit.lean` (machine-printed axiom footprint), buildable and
  independently re-checkable with `lake build`.
- The synthesizable Verilog RTL — the fixed-matrix firewall
  (`samipe_cde_firewall.v`), the runtime-configurable-matrix variant
  (`samipe_configurable.v`), and the CDE pre-decode interface controller
  (`samipe_interface_ctl.v`) — plus the netlist and gate-count artifacts
  (`netlist.json`, `gate_report.json`) that back the figures in the
  technical brief.
- The full Python verification pipeline: the reference firewall simulator
  (`firewall.py`), the RTL equivalence harness (`rtl_equiv.py` — complete,
  non-sampled matrix-equality checking between the netlist and the Python
  reference), the benchmark suite (`bench.py`), and the HMAC-SHA256 audit
  chain implementation (`audit/`).
- The cocotb and pure-Python test suites (`sim/test_samipe.py`,
  `sim/functional_test.py` — 31 tests) and the CI workflows that run them
  (`.github/workflows/lean-verify.yml`, `rtl-verify.yml`).
- The C/ACLE driver (`driver.c`, `samipe.h`) demonstrating the CX2
  instruction path an evaluator's own core or simulator could exercise.

An evaluator can build every proof, run every test, reproduce every
benchmark, and independently verify every figure quoted in the technical
brief — all of it is real, reproducible artifact, not marketing collateral
standing in for a locked-down demo.

---

## 2. Evaluation Scope

The dividing line between what is included in the open evaluation and what
requires a commercial license follows the same line GPLv3's copyleft draws:
anything an evaluator needs to *assess soundness and fit* is open; anything
that constitutes *proprietary production integration* is not.

### Included in evaluation (GPLv3, available today)

| Artifact | What it lets you verify |
|---|---|
| RTL (`rtl/*.v`) | Read, simulate, lint, and hand-analyze the actual synthesizable source — not a black-box netlist |
| Lean 4 proofs (`proofs/*.lean`) | Rebuild the soundness theorems yourself; run `lake build proofs.AxiomAudit` and confirm the axiom footprint independently |
| Testbenches (`sim/*.py`) | Run the 31-test functional suite and the cocotb harness against the provided RTL |
| C/ACLE driver (`impl/driver.c`, `impl/samipe.h`) | Inspect and exercise the CX2 instruction path against your own Armv8.1-M simulator or core model |
| Reference netlist (`rtl/netlist.json`, `rtl/gate_report.json`) | Cross-check the 79-gate/depth-7 figures against the RTL yourself, gate by gate |

### Requires a commercial license

| Item | Why it's excluded from the open evaluation |
|---|---|
| Proprietary cell-library mapping | Mapping the abstract 2-input-gate netlist to a specific vendor's standard-cell library (or an SFQ/ERSFQ library, per the SEEQC blueprint) is target-node synthesis work, not evaluation of the existing artifact — and is the deliverable of SOW Days 31-60, not something GPLv3 grants a path to bypass paying for |
| Custom invariant matrices | The default tiled-Hamming(7,4) SEC-DED matrix is the reference configuration; a customer's actual production invariant (their real safety, isolation, or state-consistency specification) is proprietary to them and its Lean-proof instantiation is SOW Days 1-30 work |
| Production firmware | Firmware wrapping the CDE driver for a specific product's boot sequence, RTOS integration, or safe-mode handling is proprietary integration work outside the scope of the reference `driver.c`/`samipe.h` demonstration API |
| Incorporation into a closed-source tapeout, bitstream, or firmware image | This is precisely what triggers GPLv3's copyleft obligations (source disclosure, anti-tivoization) absent a commercial license — see [`LICENSE`](../LICENSE) |

**In short:** you can prove to yourself, using only what's in this
repository today, that the math is sound and the gate count is honest.
Turning that into a shipped, proprietary product is what the commercial
license and the 90-day SOW are for.

---

## 3. 30-Day Sandboxed Evaluation

A structured, time-boxed evaluation window for a prospective commercial
licensee to run the artifact against their own criteria before a licensing
decision.

### Terms

- **Duration:** 30 calendar days from the start of active evaluation,
  extendable by mutual agreement.
- **Basis:** the existing GPLv3 grant already permits everything listed
  under "what the evaluator can do" below without any additional agreement
  — the 30-day window is a *structuring* convenience (a clear point at which
  the evaluating organization commits to a licensing decision, a paid
  exclusive window, or disengagement), not a gate on access that wouldn't
  otherwise exist.
- **No production use.** The sandbox is for internal technical evaluation.
  Any output, derivative work, or integration artifact produced during the
  evaluation that ends up in a shipped product remains subject to GPLv3's
  copyleft terms unless a commercial license is separately executed before
  that use occurs.

### What the evaluator can do (within GPLv3, no additional agreement needed)

- **Simulate.** Run the cocotb testbench and the pure-Python functional
  suite against the provided RTL; run the RTL equivalence harness; write
  additional test vectors and confirm behavior against your own invariant
  hypotheses.
- **Lint.** Run Verilator or any other open-source or commercial lint tool
  against all three Verilog modules; the CI workflow (`rtl-verify.yml`)
  already demonstrates this is clean today.
- **Benchmark.** Run `bench.py` against your own hardware to reproduce (or
  challenge) the software-side wall-clock measurements underlying the
  350-520x speedup claim; the hardware side of that comparison is a
  combinational-depth analysis you can independently re-derive from the
  netlist, not a number you have to take on faith.
- **Rebuild the proofs.** Run `lake build` and `lake build
  proofs.AxiomAudit` yourself and confirm zero `sorry`, zero
  `native_decide`, and the exact three-axiom standard footprint
  (`propext`, `Classical.choice`, `Quot.sound`).
- **Analyze the RTL by hand.** Nothing about the 79-gate, depth-7 figures
  requires trusting this project's tooling — count the gates in
  `samipe_cde_firewall.v` yourself.

### What requires a contract

- **Target-cell synthesis.** Running the RTL through a proprietary
  synthesis flow (Synopsys DC, Cadence Genus, a foundry-specific FPGA
  toolchain, or an SFQ cell library) against a real PDK is the Days 31-60
  SOW deliverable — it is also, practically, something most evaluators
  cannot do without their own licensed EDA tools and PDK access regardless
  of what this project grants.
- **Production deployment.** Shipping the RTL, the proofs, the interface
  controller, or any derivative synthesis script inside a proprietary
  tapeout, FPGA bitstream, or closed-source firmware image triggers GPLv3
  copyleft unless a commercial license has been executed first. This is not
  a sandbox restriction — it is baseline GPLv3 mechanics, restated here so
  it isn't missed in an evaluation-phase readiness check.
- **Custom invariant matrix design and proof instantiation.** An evaluator
  is free to *read* the generic Lean theorems and confirm they hold for
  arbitrary `H`; formally instantiating and delivering a customer-specific
  proof artifact for a proprietary invariant matrix is Days 1-30 SOW scope.

---

## 4. IP Protection

### The copyleft moat

GPLv3 is the enforcement mechanism, not a courtesy license. Any commercial
entity that incorporates the RTL, the Lean proofs, the CDE interface
controller, or a derivative synthesis script into a proprietary processor
pipeline, FPGA bitstream, ASIC tapeout, custom instruction extension, or
closed-source firmware inherits GPLv3's copyleft obligations in full:

- **Source disclosure** — the entire derivative work, not just the parts
  touching SAMIPE, must be released under GPLv3.
- **Anti-tivoization** — hardware restrictions cannot be used to prevent
  end users from running modified versions of the covered work.

This is the structural reason a company evaluating SAMIPE for a real
product has two paths, not one workaround: build entirely in the open under
GPLv3 (viable, and free), or obtain a commercial license that lifts these
obligations for the proprietary portions of the work. There is no quiet
third path where a proprietary integration avoids both.

Justin Arndt is the sole copyright holder of this repository's contents and
is the only party who can grant the commercial licensing exemption — see
the dual-licensing notice at the top of [`LICENSE`](../LICENSE).

### NDA framework for proprietary cell libraries

Target-cell synthesis (SOW Days 31-60, §7 of the technical brief)
necessarily involves the evaluator's own proprietary standard-cell library,
PDK, or SFQ cell definitions. None of that proprietary material needs to
flow toward the SAMIPE side of the engagement for the RTL-retargeting and
timing-closure work to happen — the retargeting is done using the
evaluator's own toolchain, on the evaluator's own infrastructure, with the
open SAMIPE RTL as the input. Where an NDA is warranted, it protects:

- The evaluator's cell-library characteristics, timing models, and any
  process-node-specific parameters disclosed incidentally during
  synthesis debugging or timing-closure conversations.
- Any customer-specific invariant matrix `H` and its associated Lean proof
  instantiation, prior to the commercial license (which would separately
  govern IP ownership of that deliverable) being executed.
- Specific power, timing, or area figures produced during a paid
  engagement, which are the evaluator's competitive information about their
  own silicon, not SAMIPE's to disclose.

An NDA is offered on request ahead of any technical discussion that would
require disclosing proprietary cell-library or process-node detail —
contact information is in §7 below.

---

## 5. Pricing Tiers

Three tiers, structured for increasing commitment and increasing exclusivity
of access to the technology and the author's direct engineering time.

### Tier 1 — 90-Day Statement of Work: **$250,000 – $750,000**

The fixed-scope integration engagement detailed in full in §7 of
[`technical_brief.md`](technical_brief.md): Days 1-30 matrix ingestion and
CDE port mapping, Days 31-60 target-cell synthesis and timing closure, Days
61-90 testbench delivery, audit-chain integration, and macro handoff. Price
within the range depends on scope specifics — number of distinct invariant
matrices to prove and integrate, complexity of the target core integration,
whether target-cell synthesis is against a commodity CMOS library, an FPGA
fabric, or a cryogenic SFQ library (the SEEQC case is meaningfully more
specialized engineering than a standard-cell CMOS retarget), and the
customer's own timeline compression requirements. This tier does not
include a commercial IP license for open-ended reuse beyond the specific
integration delivered — see Tier 2 for that.

### Tier 2 — Perpetual IP License: **$3.5M – $8M per core line**

A perpetual commercial license removing GPLv3's copyleft obligations for a
defined core line or product family — the customer may incorporate the RTL,
proofs, and interface controller into proprietary tapeouts, bitstreams, or
firmware for that core line indefinitely, without the source-disclosure or
anti-tivoization requirements that would otherwise attach. Price within the
range scales with the scope of the license (single product line vs. a
broader core-family grant) and whether the license includes ongoing access
to updates and proof-maintenance as the Lean/mathlib toolchain evolves.
This tier is typically paired with, but does not require, a Tier 1
engagement to actually complete the integration — a customer with in-house
capability to do their own RTL retargeting and testbench work could acquire
the IP license alone.

### Tier 3 — Exclusive Acquisition: **$35M – $75M**

Full, exclusive acquisition of the SAMIPE IP — the RTL, the Lean proof
corpus, the CDE interface architecture, and (subject to negotiation) the
author's direct involvement in a transition period. This is the appropriate
tier for an acquirer seeking to own the technology outright, including the
right to relicense, extend, or discontinue the open GPLv3 distribution
going forward, rather than operate alongside an ongoing open-source release.
Price depends heavily on deal structure (cash vs. equity, transition-period
consulting terms, and whether the acquisition includes the companion QLDPC
decoder-certification project's related IP as a package).

---

## 6. Paid Exclusive Evaluation Option

For an organization that wants more than the open 30-day sandbox — a
committed, exclusive window during which the author does not engage in
parallel evaluation or licensing conversations with a competing party for
the same core-line use case — a paid exclusive evaluation is available:

**$25,000 retainer for a 60-day exclusive window.**

This buys:

- 60 calendar days of exclusivity: no parallel commercial-licensing or
  acquisition conversation with a directly competing evaluator for the same
  target use case during the window.
- Direct engineering time from the author for a netlist walkthrough,
  Q&A on the Lean proof structure, and guidance on how a customer's specific
  invariant would map onto the `H`-matrix framework (i.e., a technical
  pre-scoping conversation ahead of committing to a full Tier 1 SOW).
- The retainer is creditable toward a subsequent Tier 1, 2, or 3 engagement
  if the evaluation converts to a signed contract within the exclusive
  window or a reasonable follow-on period — it is a good-faith deposit
  against a real deal, not a separate standalone fee stacked on top of the
  SOW pricing in §5.

This option exists for evaluators who need certainty that their competitive
evaluation window isn't being run in parallel with a rival's, which the open
GPLv3 sandbox (available to anyone, simultaneously, by design) cannot offer
by itself.

---

## 7. Contact

**Justin Arndt**
justinarndt05@gmail.com

Paid evaluation, netlist walkthrough, NDA requests, and commercial
licensing inquiries — including Tier 1/2/3 scoping and the paid exclusive
evaluation option — are welcome directly at the address above.
