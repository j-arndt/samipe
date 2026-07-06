-- Copyright (c) 2026 Justin Arndt. All rights reserved.
-- Licensed under the GNU GPLv3. For commercial licensing and proprietary
-- hardware mapping, see the LICENSE file (dual-licensing notice at top).
/-
# AxiomAudit -- Axiom Footprint Audit for SAMIPE Proofs

Prints the axiom dependencies of every main theorem in `SAMIPECore`.

## Expected axiom footprint

The theorems rely on at most three standard Lean 4 / Mathlib axioms:

- `propext` : propositional extensionality (built into Lean's kernel)
- `Classical.choice` : classical choice (used by Mathlib's `Decidable` instances
  and `noncomputable` definitions)
- `Quot.sound` : quotient soundness (built into Lean's kernel)

These are the standard trusted axioms of the CIC+Quot foundation that Lean 4
uses. No `sorry`, no `native_decide`, no `Axiom` declarations appear.
-/

import proofs.SAMIPECore

#print axioms SAMIPE.samipe_cde_firewall_sound
#print axioms SAMIPE.checkInvariant_sound
#print axioms SAMIPE.checkInvariant_complete
#print axioms SAMIPE.validateCDERun_sound
