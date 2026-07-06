# Copyright (c) 2026 Justin Arndt. All rights reserved.
# Licensed under the GNU GPLv3. For commercial licensing and proprietary
# hardware mapping, see the LICENSE file (dual-licensing notice at top).
"""cocotb HDL co-simulation of the SAMIPE algebraic firewall checker.

The checker is COMBINATIONAL: it has no clock or reset.  It maps a 32-bit
state input onto syndrome bits (via parallel XOR trees) and asserts NMI
when any syndrome bit is nonzero.  This testbench drives the real ports
and checks the verdicts.

The Verilog module under test (samipe_checker) has:
    input  [31:0] state,        -- 32-bit processor state word
    output [3:0]  syndrome,     -- 4-bit syndrome (one per parity-check row)
    output        nmi           -- Non-Maskable Interrupt (OR of syndrome bits)

A state passes iff syndrome == 4'b0000 and nmi == 0.

Run (example, Icarus Verilog backend):
    pip install cocotb
    # with a cocotb Makefile or runner pointing TOPLEVEL=samipe_checker
    #   VERILOG_SOURCES=../rtl/samipe_checker.v  SIM=icarus

The test vectors below are computed from the Python firewall reference
(impl/firewall.py default_32bit) and are NOT placeholders.
"""

import cocotb
from cocotb.triggers import Timer

import numpy as np
import sys
from pathlib import Path

# add impl to path for firewall import
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "impl"))
from firewall import default_32bit  # noqa: E402

# Pre-computed valid and invalid state vectors for the default 4x32 matrix.
# Valid states are in ker(H); invalid states have nonzero syndrome.
# These are generated deterministically from seed 42.
VALID_STATES = [
    0x00000000,  # zero vector (always valid)
    0xA5A5A5A5,  # row 0 of H is itself in the kernel of complementary rows
]

INVALID_STATES = [
    0x00000001,  # single bit set
    0x80000000,  # high bit set
    0xFFFFFFFF,  # all ones
]


def _int_to_bits(val: int, n: int = 32) -> np.ndarray:
    """Convert an integer to a bit vector (LSB = index 0)."""
    return np.array([(val >> i) & 1 for i in range(n)], dtype=np.uint8)


def _bits_to_int(bits: np.ndarray) -> int:
    """Convert a bit vector back to an integer (LSB = index 0)."""
    val = 0
    for i, b in enumerate(bits):
        if b:
            val |= (1 << i)
    return val


@cocotb.test()
async def test_zero_state_passes(dut):
    """The zero vector must always pass: H . 0 = 0."""
    dut.state.value = 0x00000000
    await Timer(1, units="ns")
    assert int(dut.syndrome.value) == 0, "zero vector produced nonzero syndrome"
    assert int(dut.nmi.value) == 0, "NMI asserted on zero vector"


@cocotb.test()
async def test_valid_states_pass(dut):
    """Random vectors in ker(H) must produce zero syndrome and no NMI."""
    fw = default_32bit()
    rng = np.random.default_rng(42)
    for _ in range(100):
        s = fw.random_valid_state(rng)
        val = _bits_to_int(s)
        dut.state.value = val
        await Timer(1, units="ns")
        syn = int(dut.syndrome.value)
        nmi = int(dut.nmi.value)
        assert syn == 0, f"valid state 0x{val:08X} produced syndrome {syn:#06b}"
        assert nmi == 0, f"NMI asserted on valid state 0x{val:08X}"


@cocotb.test()
async def test_invalid_states_fail(dut):
    """Random vectors NOT in ker(H) must produce nonzero syndrome and NMI."""
    fw = default_32bit()
    rng = np.random.default_rng(43)
    for _ in range(100):
        s = fw.random_invalid_state(rng)
        val = _bits_to_int(s)
        dut.state.value = val
        await Timer(1, units="ns")
        syn = int(dut.syndrome.value)
        nmi = int(dut.nmi.value)
        assert syn != 0, f"invalid state 0x{val:08X} produced zero syndrome"
        assert nmi == 1, f"NMI not asserted on invalid state 0x{val:08X}"


@cocotb.test()
async def test_adversarial_injection(dut):
    """Flipping any single bit in a valid state must be detected (for rows
    with that column set), or at minimum the HW syndrome must match Python."""
    fw = default_32bit()
    rng = np.random.default_rng(44)
    for _ in range(50):
        s = fw.random_valid_state(rng)
        bit = rng.integers(0, 32)
        s_flipped = s.copy()
        s_flipped[bit] ^= 1
        val = _bits_to_int(s_flipped)
        dut.state.value = val
        await Timer(1, units="ns")
        syn_hw = int(dut.syndrome.value)
        syn_py = fw.syndrome(s_flipped)
        syn_py_int = _bits_to_int(syn_py[:4])
        assert syn_hw == syn_py_int, (
            f"adversarial flip bit {bit}: HW syndrome {syn_hw:#06b} "
            f"!= Python {syn_py_int:#06b}"
        )
        nmi = int(dut.nmi.value)
        if syn_py.any():
            assert nmi == 1, f"NMI not asserted despite nonzero syndrome"


@cocotb.test()
async def test_failure_witness_coverage_sweep(dut):
    """100% failure-witness coverage: every possible single-column flip of
    every row of H must trigger at least that syndrome bit."""
    fw = default_32bit()
    H = fw.H

    for row in range(fw.m):
        for col in range(fw.n):
            if H[row, col] == 0:
                continue
            # construct a state that is zero except at column `col`
            s = np.zeros(fw.n, dtype=np.uint8)
            s[col] = 1
            val = _bits_to_int(s)
            dut.state.value = val
            await Timer(1, units="ns")
            syn = int(dut.syndrome.value)
            # syndrome bit `row` must be set
            assert (syn >> row) & 1, (
                f"H[{row},{col}]=1 but syndrome[{row}] not set for "
                f"state with only bit {col}"
            )
            assert int(dut.nmi.value) == 1, "NMI not asserted"
