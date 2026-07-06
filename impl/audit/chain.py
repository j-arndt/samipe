# Copyright (c) 2026 Justin Arndt. All rights reserved.
# Licensed under the GNU GPLv3. For commercial licensing and proprietary
# hardware mapping, see the LICENSE file (dual-licensing notice at top).
"""audit/chain.py -- HMAC-SHA256 hash-chained audit log (JSONL) for SAMIPE.

Schema matches the SAMIPE audit log format:
    {"seq", "timestamp", "event", "data", "prev_hash", "hmac"}

Chain rule: record r_i carries prev_hash = hmac(r_{i-1}) (genesis: 64 zeros),
and hmac = HMAC-SHA256(key, canonical(r_i without the hmac field)) where
canonical is json.dumps(..., sort_keys=True, separators=(",", ":")).  Any
mutation of any field of any record breaks every subsequent hmac -- tamper-
evidence, given key secrecy.

What the chain establishes: integrity of the execution transcript.  The
algebraic invariant is enforced by the F2 parity-check matrix in hardware;
the chain records which matrices were loaded, which states were checked,
and whether each check passed or failed.

Event types (SAMIPE-specific):
    STATE_CHECKED     -- a state vector was submitted to the firewall
    INVARIANT_LOADED  -- a parity-check matrix was loaded into the checker
    CHECK_PASSED      -- the firewall accepted a state (syndrome = 0)
    CHECK_FAILED      -- the firewall rejected a state (syndrome != 0)
    CHAIN_NOTE        -- freeform annotation (warnings, status messages)
"""

from __future__ import annotations

import hashlib
import hmac as hmac_mod
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Tuple

GENESIS = "0" * 64
DEV_KEY = b"samipe-dev-key-NOT-FOR-PRODUCTION"

PROOF_FILES = [
    "rtl/samipe_checker.v",
    "rtl/netlist.json",
    "impl/firewall.py",
    "impl/rtl_equiv.py",
]


def _canonical(obj) -> bytes:
    """Deterministic JSON serialisation for HMAC input."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":")).encode("utf-8")


def sha256_file(path: str | Path) -> str:
    """Compute the SHA-256 hex digest of a file."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def proof_hashes(repo_root: str | Path) -> dict:
    """Return SHA-256 hashes for all SAMIPE proof/source files that exist."""
    root = Path(repo_root)
    return {rel: sha256_file(root / rel) for rel in PROOF_FILES if (root / rel).exists()}


class AuditChain:
    """Append-only HMAC-SHA256 chained JSONL log."""

    def __init__(self, path: str | Path, key: Optional[bytes] = None):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        env_key = os.environ.get("SAMIPE_HMAC_KEY")
        self.key = key or (env_key.encode() if env_key else DEV_KEY)
        self._dev_key = self.key == DEV_KEY
        self.seq = 0
        self.prev_hash = GENESIS
        if self.path.exists() and self.path.stat().st_size > 0:
            with open(self.path) as f:
                for line in f:
                    rec = json.loads(line)
            self.seq = rec["seq"] + 1
            self.prev_hash = rec["hmac"]
        elif self._dev_key:
            self._append_raw("CHAIN_NOTE", {
                "warning": "chain keyed with the public dev key -- tamper-evidence "
                           "requires SAMIPE_HMAC_KEY to be set to a secret value"
            })

    def _append_raw(self, event: str, data: dict) -> dict:
        rec = {
            "seq": self.seq,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "event": event,
            "data": data,
            "prev_hash": self.prev_hash,
        }
        mac = hmac_mod.new(self.key, _canonical(rec), hashlib.sha256).hexdigest()
        rec["hmac"] = mac
        with open(self.path, "a") as f:
            f.write(json.dumps(rec) + "\n")
        self.seq += 1
        self.prev_hash = mac
        return rec

    def append(self, event: str, data: dict) -> dict:
        """Append an event to the chain.  Returns the full record (with hmac)."""
        return self._append_raw(event, data)


def verify_chain(path: str | Path, key: Optional[bytes] = None) -> Tuple[bool, int, Optional[int]]:
    """Re-verify a chain file end to end.

    Returns
    -------
    (ok, n_records, first_bad_seq_or_None)
        ok is True iff every HMAC and prev_hash link checks out.
        n_records is the total number of records examined.
        first_bad_seq is the seq number of the first broken record, or None.
    """
    env_key = os.environ.get("SAMIPE_HMAC_KEY")
    key = key or (env_key.encode() if env_key else DEV_KEY)
    prev = GENESIS
    n = 0
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            rec = json.loads(line)
            claimed = rec.pop("hmac")
            if rec.get("prev_hash") != prev:
                return False, n, rec.get("seq")
            mac = hmac_mod.new(key, _canonical(rec), hashlib.sha256).hexdigest()
            if not hmac_mod.compare_digest(mac, claimed):
                return False, n, rec.get("seq")
            prev = claimed
            n += 1
    return True, n, None
