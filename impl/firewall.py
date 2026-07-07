# Copyright (c) 2026 Justin Arndt. All rights reserved.
# Licensed under the GNU GPLv3. For commercial licensing and proprietary
# hardware mapping, see the LICENSE file (dual-licensing notice at top).
"""firewall.py -- F2 algebraic firewall simulator for SAMIPE.

Core math: an m x n binary parity-check matrix H validates state vectors
s in F2^n by checking H . s = 0 (mod 2).  The Verilog implementation
realises this as parallel XOR trees (one per syndrome bit); a state passes
iff every syndrome bit is zero.

Classes:
  InvariantMatrix -- holds the m x n binary matrix H (numpy uint8), exposes
      check(), syndrome(), kernel-vector generation, and factory constructors.

Preset matrices:
  hamming_7_4()   -- the classical [7,4,3] Hamming code parity-check matrix.
  default_32bit() -- the 4 x 32 matrix matching the Verilog default localparam.
  identity_check(n) -- n x n identity (rejects everything except zero).
"""

from __future__ import annotations

from typing import List, Optional

import numpy as np


class InvariantMatrix:
    """Binary parity-check matrix H over F2.

    H is stored as an (m, n) numpy uint8 array with entries in {0, 1}.
    A state vector s in F2^n passes the firewall iff H . s = 0 (mod 2).
    """

    def __init__(self, H: np.ndarray):
        H = np.asarray(H, dtype=np.uint8)
        if H.ndim != 2:
            raise ValueError(f"H must be 2-D, got shape {H.shape}")
        if not np.all((H == 0) | (H == 1)):
            raise ValueError("H must contain only 0s and 1s")
        self._H = H

    # -- properties -----------------------------------------------------------

    @property
    def H(self) -> np.ndarray:
        """The m x n parity-check matrix (read-only copy)."""
        return self._H.copy()

    @property
    def m(self) -> int:
        """Number of check rows (syndrome bits)."""
        return self._H.shape[0]

    @property
    def n(self) -> int:
        """Number of state-vector bits."""
        return self._H.shape[1]

    # -- core operations ------------------------------------------------------

    def syndrome(self, state_vec: np.ndarray) -> np.ndarray:
        """Compute the raw syndrome vector H . s mod 2.

        Parameters
        ----------
        state_vec : array_like, shape (n,) or (batch, n)
            State vector(s) with entries in {0, 1}.

        Returns
        -------
        np.ndarray, shape (m,) or (batch, m)
            Syndrome bits, each in {0, 1}.
        """
        s = np.asarray(state_vec, dtype=np.uint8)
        if s.ndim == 1:
            return (self._H @ s) % 2
        # batched: s is (batch, n) -> result is (batch, m)
        return (s @ self._H.T) % 2

    def check(self, state_vec: np.ndarray) -> bool:
        """Return True iff every syndrome bit is zero (state is valid).

        For batched input (2-D), returns True only if ALL vectors pass.
        """
        syn = self.syndrome(state_vec)
        return bool(np.all(syn == 0))

    def check_batch(self, states: np.ndarray) -> np.ndarray:
        """Check a batch of state vectors, return a boolean array.

        Parameters
        ----------
        states : array_like, shape (batch, n)

        Returns
        -------
        np.ndarray of bool, shape (batch,)
            True where the corresponding state passes the firewall.
        """
        states = np.asarray(states, dtype=np.uint8)
        syn = (states @ self._H.T) % 2  # (batch, m)
        return np.all(syn == 0, axis=1)

    # -- kernel vector generation ---------------------------------------------

    def _kernel_basis(self) -> np.ndarray:
        """Compute a basis for ker(H) over F2 via Gaussian elimination.

        Returns an (k, n) uint8 array where k = dim ker(H) = n - rank(H).
        """
        m, n = self._H.shape
        # augmented matrix [H | I_n] transposed for column operations
        # We work with the transpose: find null space of H by row-reducing H^T.
        # ker(H) = {x : Hx=0} is the left null space of H^T ... but it is
        # easier to row-reduce H directly and read off the free columns.

        A = self._H.copy()
        pivot_col = [-1] * m
        row = 0
        for col in range(n):
            # find pivot in column col at or below current row
            found = -1
            for r in range(row, m):
                if A[r, col]:
                    found = r
                    break
            if found == -1:
                continue
            # swap rows
            A[[row, found]] = A[[found, row]]
            pivot_col[row] = col
            # eliminate below and above
            for r in range(m):
                if r != row and A[r, col]:
                    A[r] = A[r] ^ A[row]
            row += 1

        rank = row
        pivot_set = set(pivot_col[:rank])
        free_cols = [c for c in range(n) if c not in pivot_set]

        # build basis vectors: for each free column f, set x[f] = 1 and
        # determine pivot entries to satisfy Hx = 0.
        basis = []
        for f in free_cols:
            x = np.zeros(n, dtype=np.uint8)
            x[f] = 1
            for r in range(rank):
                pc = pivot_col[r]
                if A[r, f]:
                    x[pc] = 1
            basis.append(x)
        if len(basis) == 0:
            return np.zeros((0, n), dtype=np.uint8)
        return np.array(basis, dtype=np.uint8)

    def random_valid_state(self, rng: Optional[np.random.Generator] = None) -> np.ndarray:
        """Generate a random vector in ker(H) (passes the firewall).

        Parameters
        ----------
        rng : numpy Generator, optional
            If None, uses np.random.default_rng().

        Returns
        -------
        np.ndarray, shape (n,), dtype uint8
            A vector s such that H . s = 0 (mod 2).
        """
        if rng is None:
            rng = np.random.default_rng()
        basis = self._kernel_basis()
        k = basis.shape[0]
        if k == 0:
            # Only the zero vector is in the kernel
            return np.zeros(self.n, dtype=np.uint8)
        coeffs = rng.integers(0, 2, size=k, dtype=np.uint8)
        # ensure not all-zero (unless kernel is trivial) for variety
        while k > 0 and not coeffs.any():
            coeffs = rng.integers(0, 2, size=k, dtype=np.uint8)
        return (coeffs @ basis) % 2

    def random_invalid_state(self, rng: Optional[np.random.Generator] = None) -> np.ndarray:
        """Generate a random vector NOT in ker(H) (fails the firewall).

        Parameters
        ----------
        rng : numpy Generator, optional

        Returns
        -------
        np.ndarray, shape (n,), dtype uint8
            A vector s such that H . s != 0 (mod 2).
        """
        if rng is None:
            rng = np.random.default_rng()
        # Strategy: generate a random vector and check; if it accidentally
        # lands in the kernel, flip a bit guided by a non-zero row of H.
        for _ in range(1000):
            s = rng.integers(0, 2, size=self.n, dtype=np.uint8)
            syn = (self._H @ s) % 2
            if syn.any():
                return s
        # Fallback: take a valid state and add a row of H (guaranteed to
        # produce a non-zero syndrome if H has full row rank, which it
        # does for all our preset matrices).
        s = self.random_valid_state(rng)
        # pick a random row of H and XOR it into a unit vector
        row_idx = rng.integers(0, self.m)
        flip_col = int(np.flatnonzero(self._H[row_idx])[0])
        s[flip_col] ^= 1
        return s

    # -- factory methods ------------------------------------------------------

    @classmethod
    def from_rows(cls, row_list: List[int], n: Optional[int] = None) -> "InvariantMatrix":
        """Build from a list of integer row values.

        Each integer encodes one row of H: bit j of the integer corresponds
        to column j of H (LSB = column 0).  This matches the Verilog
        localparam ROW_0, ROW_1, ... convention.

        Parameters
        ----------
        row_list : list of int
            One integer per check row.
        n : int, optional
            Number of columns.  If None, inferred from the largest row value.
        """
        if n is None:
            max_val = max(row_list) if row_list else 0
            n = max(max_val.bit_length(), 1)
        m = len(row_list)
        H = np.zeros((m, n), dtype=np.uint8)
        for i, val in enumerate(row_list):
            for j in range(n):
                H[i, j] = (val >> j) & 1
        return cls(H)

    @classmethod
    def from_numpy(cls, matrix: np.ndarray) -> "InvariantMatrix":
        """Build from a numpy array (entries must be 0 or 1)."""
        return cls(matrix)

    # -- display --------------------------------------------------------------

    def __repr__(self) -> str:
        return f"InvariantMatrix(m={self.m}, n={self.n})"

    def summary(self) -> str:
        """Human-readable summary of the matrix properties."""
        basis = self._kernel_basis()
        lines = [
            f"InvariantMatrix {self.m} x {self.n}",
            f"  rank(H)      = {self.n - len(basis)}",
            f"  dim ker(H)   = {len(basis)} (of {self.n})",
            f"  row weight   = {self._H.sum(axis=1).tolist()}",
            f"  col weight   = {self._H.sum(axis=0).tolist()}",
        ]
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Preset matrices
# ---------------------------------------------------------------------------

def hamming_7_4() -> InvariantMatrix:
    """The [7,4,3] Hamming code parity-check matrix.

    H is 3 x 7.  The kernel has dimension 4; minimum distance is 3.
    Standard form: columns are the nonzero binary 3-tuples in counting order.
    """
    H = np.array([
        [1, 1, 0, 1, 1, 0, 0],
        [1, 0, 1, 1, 0, 1, 0],
        [0, 1, 1, 1, 0, 0, 1],
    ], dtype=np.uint8)
    return InvariantMatrix(H)


def default_32bit() -> InvariantMatrix:
    """The 4 x 32 parity-check matrix matching the Verilog default.

    This is the matrix used by samipe_cde_firewall.v: a Hamming(7,4) SEC-DED
    parity-check matrix tiled across four 7-bit blocks in a 32-bit word, with
    a fourth overall-parity row covering all 32 bits.

    Verilog localparam encoding (LSB = column 0):
      ROW_0 = tiled h0 (bit-index has bit 0 set) = 0x0AB56AD5
      ROW_1 = tiled h1 (bit-index has bit 1 set) = 0x0CD9B366
      ROW_2 = tiled h2 (bit-index has bit 2 set) = 0x0F1E3C78
      ROW_3 = overall parity (all 32 bits)        = 0xFFFFFFFF
    """
    return InvariantMatrix.from_rows([
        0x0AB56AD5,
        0x0CD9B366,
        0x0F1E3C78,
        0xFFFFFFFF,
    ], n=32)


def identity_check(n: int) -> InvariantMatrix:
    """n x n identity matrix.  Rejects everything except the zero vector.

    ker(I_n) = {0}, so the only valid state is all-zeros.  Useful as a
    maximally restrictive firewall for testing.
    """
    return InvariantMatrix(np.eye(n, dtype=np.uint8))
