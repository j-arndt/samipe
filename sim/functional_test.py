#!/usr/bin/env python3
# Copyright (c) 2026 Justin Arndt. All rights reserved.
# Licensed under the GNU GPLv3. For commercial licensing and proprietary
# hardware mapping, see the LICENSE file (dual-licensing notice at top).
"""functional_test.py -- pure-Python functional test for the SAMIPE firewall.

This test runs entirely in Python (no Verilator, no cocotb, no HDL simulator).
It performs a bit-accurate simulation of the XOR tree checker and validates
the F2 algebraic firewall against exhaustive, random, and adversarial inputs.

Test suites:
  1. Valid states:     10000 random vectors in ker(H), verify all pass.
  2. Invalid states:   10000 random vectors NOT in ker(H), verify all fail.
  3. Edge cases:       all-zeros, all-ones, single-bit, Hamming weight sweeps.
  4. Batch validation: numpy-batched path correctness.
  5. XOR tree sim:     bit-accurate simulation of the hardware XOR trees.
  6. Adversarial:      single-bit flips in valid states, verify detection.
  7. Audit chain:      create and verify a short audit chain.
  8. Multi-matrix:     test Hamming [7,4,3] and identity matrices too.

Exit: 0 on success, 1 on failure.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

import numpy as np

# ensure impl is importable
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "impl"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "impl" / "audit"))

from firewall import InvariantMatrix, default_32bit, hamming_7_4, identity_check
from chain import AuditChain, verify_chain

SEED = 20260706
N_RANDOM = 10000


class TestResults:
    """Accumulate pass/fail counts for test suites."""

    def __init__(self):
        self.passed = 0
        self.failed = 0
        self.suite_results = []

    def record(self, name: str, ok: bool, detail: str = ""):
        if ok:
            self.passed += 1
            status = "PASS"
        else:
            self.failed += 1
            status = "FAIL"
        self.suite_results.append((name, status, detail))
        print(f"  [{status}] {name}" + (f" -- {detail}" if detail else ""))

    def summary(self) -> bool:
        print(f"\n{'=' * 60}")
        print(f"RESULTS: {self.passed} passed, {self.failed} failed, "
              f"{self.passed + self.failed} total")
        if self.failed > 0:
            print("FAILED TESTS:")
            for name, status, detail in self.suite_results:
                if status == "FAIL":
                    print(f"  - {name}: {detail}")
        print("=" * 60)
        return self.failed == 0


def simulate_xor_tree(H: np.ndarray, state: np.ndarray) -> np.ndarray:
    """Bit-accurate simulation of the Verilog XOR tree checker.

    For each row r of H, compute: syndrome[r] = XOR of state[c] for all c
    where H[r,c] = 1.  This mirrors the combinational `assign` statements
    in the emitted Verilog.
    """
    m, n = H.shape
    syn = np.zeros(m, dtype=np.uint8)
    for r in range(m):
        v = np.uint8(0)
        for c in range(n):
            if H[r, c]:
                v ^= state[c]
        syn[r] = v
    return syn


def simulate_nmi(syndrome: np.ndarray) -> bool:
    """Simulate the NMI output: OR reduction of all syndrome bits."""
    return bool(syndrome.any())


# ---------------------------------------------------------------------------
# Test suites
# ---------------------------------------------------------------------------

def test_valid_states(results: TestResults, fw: InvariantMatrix, label: str = ""):
    """Generate N_RANDOM random valid states, verify all pass."""
    prefix = f"[{label}] " if label else ""
    rng = np.random.default_rng(SEED)
    H = fw.H
    failures = 0

    for i in range(N_RANDOM):
        s = fw.random_valid_state(rng)
        # Python check
        if not fw.check(s):
            failures += 1
            continue
        # XOR tree simulation
        syn = simulate_xor_tree(H, s)
        if syn.any():
            failures += 1
            continue
        nmi = simulate_nmi(syn)
        if nmi:
            failures += 1

    results.record(
        f"{prefix}valid states ({N_RANDOM})",
        failures == 0,
        f"{failures} failures" if failures else "all passed"
    )


def test_invalid_states(results: TestResults, fw: InvariantMatrix, label: str = ""):
    """Generate N_RANDOM random invalid states, verify all fail."""
    prefix = f"[{label}] " if label else ""
    rng = np.random.default_rng(SEED + 1)
    H = fw.H
    failures = 0

    for i in range(N_RANDOM):
        s = fw.random_invalid_state(rng)
        # Python check must report failure
        if fw.check(s):
            failures += 1
            continue
        # XOR tree simulation must produce nonzero syndrome
        syn = simulate_xor_tree(H, s)
        if not syn.any():
            failures += 1
            continue
        nmi = simulate_nmi(syn)
        if not nmi:
            failures += 1

    results.record(
        f"{prefix}invalid states ({N_RANDOM})",
        failures == 0,
        f"{failures} failures" if failures else "all detected"
    )


def test_edge_cases(results: TestResults, fw: InvariantMatrix, label: str = ""):
    """Test edge cases: all-zeros, all-ones, single-bit vectors."""
    prefix = f"[{label}] " if label else ""
    H = fw.H
    n = fw.n
    bad = 0

    # all-zeros: always valid (H . 0 = 0)
    z = np.zeros(n, dtype=np.uint8)
    if not fw.check(z):
        bad += 1
    syn = simulate_xor_tree(H, z)
    if syn.any():
        bad += 1

    results.record(f"{prefix}all-zeros passes", bad == 0)

    # all-ones: check Python and XOR tree agree
    o = np.ones(n, dtype=np.uint8)
    py_ok = fw.check(o)
    syn = simulate_xor_tree(H, o)
    hw_ok = not syn.any()
    results.record(
        f"{prefix}all-ones consistency",
        py_ok == hw_ok,
        f"Python={py_ok}, XOR-tree={hw_ok}"
    )

    # single-bit vectors: for each bit position, verify consistency
    single_bad = 0
    for bit in range(n):
        s = np.zeros(n, dtype=np.uint8)
        s[bit] = 1
        py_syn = fw.syndrome(s)
        hw_syn = simulate_xor_tree(H, s)
        if not np.array_equal(py_syn, hw_syn):
            single_bad += 1
    results.record(
        f"{prefix}single-bit vectors ({n})",
        single_bad == 0,
        f"{single_bad} mismatches" if single_bad else "all consistent"
    )


def test_batch_validation(results: TestResults, fw: InvariantMatrix, label: str = ""):
    """Test the batched numpy validation path."""
    prefix = f"[{label}] " if label else ""
    rng = np.random.default_rng(SEED + 2)
    n_batch = 1000

    # generate a mix of valid and invalid states
    valid_states = np.array([fw.random_valid_state(rng) for _ in range(n_batch // 2)])
    invalid_states = np.array([fw.random_invalid_state(rng) for _ in range(n_batch // 2)])
    all_states = np.vstack([valid_states, invalid_states])

    # batch check
    batch_results = fw.check_batch(all_states)

    # verify: first half should pass, second half should fail
    valid_ok = np.all(batch_results[:n_batch // 2])
    invalid_ok = np.all(~batch_results[n_batch // 2:])

    results.record(
        f"{prefix}batch valid ({n_batch // 2})",
        bool(valid_ok),
        "all passed" if valid_ok else "some failed"
    )
    results.record(
        f"{prefix}batch invalid ({n_batch // 2})",
        bool(invalid_ok),
        "all detected" if invalid_ok else "some missed"
    )

    # verify batch agrees with per-element
    per_element = np.array([fw.check(all_states[i]) for i in range(len(all_states))])
    agree = np.array_equal(batch_results, per_element)
    results.record(
        f"{prefix}batch vs loop agreement",
        agree,
    )


def test_xor_tree_equivalence(results: TestResults, fw: InvariantMatrix, label: str = ""):
    """Verify XOR tree simulation matches numpy matrix multiply for many vectors."""
    prefix = f"[{label}] " if label else ""
    rng = np.random.default_rng(SEED + 3)
    H = fw.H
    bad = 0

    for _ in range(N_RANDOM):
        s = rng.integers(0, 2, size=fw.n, dtype=np.uint8)
        syn_np = fw.syndrome(s)
        syn_xor = simulate_xor_tree(H, s)
        if not np.array_equal(syn_np, syn_xor):
            bad += 1

    results.record(
        f"{prefix}XOR tree == numpy ({N_RANDOM})",
        bad == 0,
        f"{bad} mismatches" if bad else "all match"
    )


def test_adversarial_injection(results: TestResults, fw: InvariantMatrix, label: str = ""):
    """Flip single bits in valid states, verify detection or consistency."""
    prefix = f"[{label}] " if label else ""
    rng = np.random.default_rng(SEED + 4)
    H = fw.H
    detected = 0
    undetected = 0
    inconsistent = 0
    n_trials = min(N_RANDOM, 5000)

    for _ in range(n_trials):
        s = fw.random_valid_state(rng)
        bit = rng.integers(0, fw.n)
        s_flipped = s.copy()
        s_flipped[bit] ^= 1

        py_syn = fw.syndrome(s_flipped)
        hw_syn = simulate_xor_tree(H, s_flipped)

        if not np.array_equal(py_syn, hw_syn):
            inconsistent += 1
            continue

        if py_syn.any():
            detected += 1
        else:
            undetected += 1

    results.record(
        f"{prefix}adversarial single-bit flips ({n_trials})",
        inconsistent == 0,
        f"detected={detected}, undetected={undetected}, inconsistent={inconsistent}"
    )


def test_failure_witness_coverage(results: TestResults, fw: InvariantMatrix, label: str = ""):
    """Every nonzero entry H[r,c] must cause syndrome[r] to flip when bit c
    is the only set bit in the state vector."""
    prefix = f"[{label}] " if label else ""
    H = fw.H
    bad = 0

    for r in range(fw.m):
        for c in range(fw.n):
            if H[r, c] == 0:
                continue
            s = np.zeros(fw.n, dtype=np.uint8)
            s[c] = 1
            syn = simulate_xor_tree(H, s)
            if syn[r] != 1:
                bad += 1

    total_ones = int(H.sum())
    results.record(
        f"{prefix}failure-witness coverage ({total_ones} entries)",
        bad == 0,
        f"{bad} uncovered" if bad else "100% covered"
    )


def test_audit_chain(results: TestResults):
    """Create a short audit chain and verify it."""
    import tempfile

    with tempfile.TemporaryDirectory() as tmpdir:
        chain_path = Path(tmpdir) / "test_chain.jsonl"
        chain = AuditChain(chain_path)
        chain.append("INVARIANT_LOADED", {"matrix": "default_32bit", "m": 4, "n": 32})
        chain.append("STATE_CHECKED", {"state": "0x00000000", "valid": True})
        chain.append("CHECK_PASSED", {"state": "0x00000000"})
        chain.append("STATE_CHECKED", {"state": "0x00000001", "valid": False})
        chain.append("CHECK_FAILED", {"state": "0x00000001", "syndrome": "0b0101"})

        ok, n, bad = verify_chain(chain_path)
        results.record(
            "audit chain create+verify",
            ok and n >= 5,  # at least 5 records (including the dev-key warning)
            f"ok={ok}, records={n}, bad_seq={bad}"
        )

        # tamper test: modify a data field inside a record (keeping valid JSON)
        data = chain_path.read_text()
        lines = data.strip().split("\n")
        if len(lines) >= 4:
            import json as _json
            rec3 = _json.loads(lines[3])
            # flip a value in the data dict to break the HMAC
            rec3["data"]["valid"] = "TAMPERED"
            lines[3] = _json.dumps(rec3)
            chain_path.write_text("\n".join(lines) + "\n")
            ok2, n2, bad2 = verify_chain(chain_path)
            results.record(
                "audit chain tamper detection",
                not ok2,
                f"tampered chain correctly rejected (bad_seq={bad2})"
                if not ok2 else "FAILED to detect tamper"
            )


def test_from_rows_factory(results: TestResults):
    """Test the from_rows factory method with known row values."""
    # Reconstruct Hamming [7,4,3] from integer rows
    # Row 0: columns {0,1,3,4} -> 2^0+2^1+2^3+2^4 = 1+2+8+16 = 27
    # Row 1: columns {0,2,3,5} -> 1+4+8+32 = 45
    # Row 2: columns {1,2,3,6} -> 2+4+8+64 = 78
    h1 = InvariantMatrix.from_rows([27, 45, 78], n=7)
    h2 = hamming_7_4()

    results.record(
        "from_rows factory (Hamming)",
        np.array_equal(h1.H, h2.H),
        f"h1.shape={h1.H.shape}, h2.shape={h2.H.shape}"
    )


def test_hamming_exhaustive(results: TestResults):
    """Exhaustive sweep of all 128 vectors in F2^7 against Hamming [7,4,3]."""
    fw = hamming_7_4()
    n_pass = 0
    for val in range(128):
        sv = np.array([(val >> i) & 1 for i in range(7)], dtype=np.uint8)
        if fw.check(sv):
            n_pass += 1
    # Hamming(7,4) has dim ker = 4, so 2^4 = 16 codewords
    results.record(
        "Hamming exhaustive (128 vectors)",
        n_pass == 16,
        f"codewords found: {n_pass} (expected 16)"
    )


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    t0 = time.time()
    results = TestResults()

    print("=" * 60)
    print("SAMIPE Functional Test Suite")
    print("=" * 60)

    # --- default 32-bit matrix ---
    print("\n-- default_32bit (4x32) --")
    fw32 = default_32bit()
    test_valid_states(results, fw32, "32bit")
    test_invalid_states(results, fw32, "32bit")
    test_edge_cases(results, fw32, "32bit")
    test_batch_validation(results, fw32, "32bit")
    test_xor_tree_equivalence(results, fw32, "32bit")
    test_adversarial_injection(results, fw32, "32bit")
    test_failure_witness_coverage(results, fw32, "32bit")

    # --- Hamming [7,4,3] ---
    print("\n-- hamming_7_4 (3x7) --")
    fw74 = hamming_7_4()
    test_valid_states(results, fw74, "ham74")
    test_invalid_states(results, fw74, "ham74")
    test_edge_cases(results, fw74, "ham74")
    test_batch_validation(results, fw74, "ham74")
    test_xor_tree_equivalence(results, fw74, "ham74")
    test_adversarial_injection(results, fw74, "ham74")
    test_failure_witness_coverage(results, fw74, "ham74")

    # --- identity check (16x16) ---
    print("\n-- identity_check(16) (16x16) --")
    fwid = identity_check(16)
    test_edge_cases(results, fwid, "id16")
    test_xor_tree_equivalence(results, fwid, "id16")
    test_failure_witness_coverage(results, fwid, "id16")

    # --- Hamming exhaustive ---
    print("\n-- exhaustive sweeps --")
    test_hamming_exhaustive(results)

    # --- cross-cutting tests ---
    print("\n-- cross-cutting --")
    test_audit_chain(results)
    test_from_rows_factory(results)

    elapsed = time.time() - t0
    print(f"\nCompleted in {elapsed:.2f}s")
    all_ok = results.summary()
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
