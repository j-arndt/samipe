-- Copyright (c) 2026 Justin Arndt. All rights reserved.
-- Licensed under the GNU GPLv3. For commercial licensing and proprietary
-- hardware mapping, see the LICENSE file (dual-licensing notice at top).
/-
# SAMIPECore -- Self-Auditing, Mathematically Immune Processing Element

SAMIPE embeds an F2 algebraic firewall into ARM's Custom Datapath Extension
(CDE). The core invariant: a parity-check matrix H over F2 = ZMod 2 validates
a state vector s by checking H . s = 0 (zero syndrome = valid state).

This module specializes the generic F2 parity-check framework (proved in
`QLDPC.GenericCert`) to the SAMIPE CDE use case where the target syndrome
is always the zero vector.

## Main results

- `cde_hardware_op` / `samipe_cde_firewall_sound`: the hardware gate returns 1
  iff the syndrome vanishes.
- `checkInvariant` / `checkInvariant_sound` / `checkInvariant_complete`:
  decidable Bool checker with both directions proved.
- `CDERunCert` / `validateCDERun` / `validateCDERun_sound`: run-level
  certificate and master soundness theorem.

Zero sorries. All proofs are constructive over generic dimensions `m`, `n`.
-/

import Mathlib

open Matrix Finset

namespace SAMIPE

variable {m n : ℕ}

/-! ## Section 1: The F2 field and CDE hardware operation -/

/-- The CDE hardware gate: returns `1 : ZMod 2` when the syndrome `H * s`
    vanishes (valid state), `0` otherwise. Models the single-cycle parity
    check implemented in the CDE coprocessor pipeline. -/
noncomputable def cde_hardware_op (H : Matrix (Fin m) (Fin n) (ZMod 2))
    (s : Fin n → ZMod 2) : ZMod 2 :=
  if H.mulVec s = 0 then 1 else 0

/-- **CDE firewall soundness**: the hardware gate returns 1 if and only if
    the state vector lies in the kernel of H. -/
theorem samipe_cde_firewall_sound (H : Matrix (Fin m) (Fin n) (ZMod 2))
    (s : Fin n → ZMod 2) :
    cde_hardware_op H s = 1 ↔ H.mulVec s = 0 := by
  unfold cde_hardware_op
  constructor
  · intro h
    split_ifs at h with hc
    · exact hc
    · -- h : (0 : ZMod 2) = 1, which is absurd
      exact absurd h (by decide)
  · intro h
    simp [h]

/-! ## Section 2: Decidable Bool checker -/

/-- Bool-valued invariant checker. Uses `Decidable` instance on vector
    equality over `ZMod 2`. -/
def checkInvariant (H : Matrix (Fin m) (Fin n) (ZMod 2))
    (s : Fin n → ZMod 2) : Bool :=
  decide (H.mulVec s = 0)

/-- Soundness: if the checker accepts, the syndrome is zero. -/
theorem checkInvariant_sound (H : Matrix (Fin m) (Fin n) (ZMod 2))
    (s : Fin n → ZMod 2)
    (h : checkInvariant H s = true) : H.mulVec s = 0 := by
  simpa [checkInvariant, decide_eq_true_eq] using h

/-- Completeness: if the syndrome is zero, the checker accepts. -/
theorem checkInvariant_complete (H : Matrix (Fin m) (Fin n) (ZMod 2))
    (s : Fin n → ZMod 2)
    (h : H.mulVec s = 0) : checkInvariant H s = true := by
  simpa [checkInvariant, decide_eq_true_eq] using h

/-! ## Section 3: CDE run certificate and master theorem -/

/-- A CDE run certificate bundles the parity-check matrix, the state vector
    under test, and the single-bit result token emitted by the CDE pipeline. -/
structure CDERunCert (m n : ℕ) where
  H      : Matrix (Fin m) (Fin n) (ZMod 2)
  state  : Fin n → ZMod 2
  result : Bool

/-- Validate a CDE run certificate: the result token must agree with the
    decidable syndrome check. -/
def validateCDERun (rc : CDERunCert m n) : Bool :=
  rc.result == checkInvariant rc.H rc.state

/-- **Master soundness theorem**: if the validator accepts and the result
    token is `true`, then the syndrome `H * s` is provably zero. This is the
    top-level guarantee that a CDE-accepted state vector satisfies the
    algebraic firewall. -/
theorem validateCDERun_sound (rc : CDERunCert m n)
    (hv : validateCDERun rc = true)
    (hr : rc.result = true) :
    rc.H.mulVec rc.state = 0 := by
  unfold validateCDERun at hv
  simp [hr, Bool.beq_eq_true_iff] at hv
  exact checkInvariant_sound rc.H rc.state hv

end SAMIPE
