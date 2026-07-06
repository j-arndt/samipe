# Copyright (c) 2026 Justin Arndt. All rights reserved.
# Licensed under the GNU GPLv3. For commercial licensing and proprietary
# hardware mapping, see the LICENSE file (dual-licensing notice at top).
"""audit/verify_chain.py -- standalone SAMIPE chain verification CLI.

Usage:  python3 verify_chain.py [--recheck-sources REPO_ROOT] <chain.jsonl> [...]

Key:    SAMIPE_HMAC_KEY env var (falls back to the public dev key -- in that
        case HMAC verification demonstrates integrity of the FORMAT only; see
        the CHAIN_NOTE the chain itself records.  Tamper-evidence requires a
        secret key.)

Modes:
  default                verify the HMAC chain end to end.
  --recheck-sources R    additionally re-hash every source file referenced by
                         an INVARIANT_LOADED record (file_hashes) relative to R
                         and compare -- so the chain's binding to the source
                         ARTIFACTS is independently re-checkable.

Exit: 0 iff every requested check passes.
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

from chain import verify_chain


def recheck_sources(chain_path: str, repo_root: Path) -> int:
    """Re-hash source files referenced by INVARIANT_LOADED events."""
    bad = 0
    n = 0
    with open(chain_path) as f:
        for line in f:
            rec = json.loads(line)
            if rec.get("event") != "INVARIANT_LOADED":
                continue
            data = rec.get("data", {})
            file_hashes = data.get("file_hashes", {})
            for rel, want in file_hashes.items():
                n += 1
                p = repo_root / rel
                if not p.exists():
                    print(f"  SOURCE MISSING  seq={rec['seq']}: {rel}")
                    bad += 1
                    continue
                got = hashlib.sha256(p.read_bytes()).hexdigest()
                status = "ok" if got == want else "HASH MISMATCH"
                if got != want:
                    bad += 1
                print(f"  source seq={rec['seq']:3d} {status:13s} {rel}")
    print(f"  sources rechecked: {n}, mismatches/missing: {bad}")
    return bad


def main(argv) -> int:
    args = list(argv[1:])
    repo_root = None
    if "--recheck-sources" in args:
        i = args.index("--recheck-sources")
        repo_root = Path(args[i + 1])
        del args[i:i + 2]
    if not args:
        print(__doc__)
        return 2
    rc = 0
    for path in args:
        ok, n, bad = verify_chain(path)
        if ok:
            print(f"OK    {path}: {n} records, chain intact")
        else:
            print(f"FAIL  {path}: broken at seq={bad} (verified {n} records before break)")
            rc = 1
        if repo_root is not None:
            rc |= 1 if recheck_sources(path, repo_root) else 0
    return rc


if __name__ == "__main__":
    sys.exit(main(sys.argv))
