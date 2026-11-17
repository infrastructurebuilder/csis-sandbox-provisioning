#!/usr/bin/env python3
"""Compare what Spack has been told with what the shell roles used to leave.

Until stage 11 the spack and intel_oneapi roles set Spack up with shell
tasks. tests/container/expected-spack-config.json is what those tasks left in
Spack's site and user scopes in this container, dumped with --dump just
before they were replaced, and kept as it was dumped. The roles now hand
lists of steps to the infrastructurebuilder.csis_spack collection; this
script holds what they leave to that file.

One difference is expected, because it was decided (stage 11, decision 3):
the script's two settings without --scope, the install-tree padding and the
Tcl modules, were in the login user's scope and are now in the site scope.

What detection finds depends on the versions the container's image happens to
have, so each external is compared by its package's name, not its version or
paths. The versions that the roles state themselves (MKL, MPI, the Intel
compilers) are checked in verify.yml against the roles' variables.

  compare-spack-config.py --spack <spack> --dump                 print what Spack holds now
  compare-spack-config.py --spack <spack> --expected <file>      compare; exit 1 on a difference
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

SCOPES = ("site", "user")
SECTIONS = ("config", "modules", "mirrors", "packages")
# Sections whose content moved from the user scope to the site scope.
MOVED = ("config", "modules")


def section(spack: str, scope: str, name: str) -> dict[str, Any]:
    done = subprocess.run(
        [spack, "config", "--scope", scope, "get", "--json", name],
        capture_output=True,
        text=True,
        check=False,
    )
    if done.returncode != 0:
        # A scope whose directory has not been made holds nothing.
        if "must refer to an existing scope" in done.stderr:
            return {}
        sys.exit(f"cannot read {scope}:{name}: {done.stderr.strip()}")
    return json.loads(done.stdout).get(name) or {}


def dump(spack: str) -> dict[str, Any]:
    return {f"{scope}:{name}": section(spack, scope, name) for scope in SCOPES for name in SECTIONS}


def merged(low: dict[str, Any], high: dict[str, Any]) -> dict[str, Any]:
    out = dict(low)
    for key, value in high.items():
        out[key] = (
            merged(out[key], value) if isinstance(value, dict) and isinstance(out.get(key), dict) else value
        )
    return out


def as_decided(shell: dict[str, Any]) -> dict[str, Any]:
    """Give what the shell left, with the one difference that was decided."""
    expected = dict(shell)
    for name in MOVED:
        expected[f"site:{name}"] = merged(shell[f"site:{name}"], shell[f"user:{name}"])
        expected[f"user:{name}"] = {}
    return expected


def comparable(found: dict[str, Any]) -> dict[str, Any]:
    """Reduce each external to its package's name; leave everything else as it is."""
    out = dict(found)
    for key in [key for key in found if key.endswith(":packages")]:
        packages = {}
        for name, entry in found[key].items():
            reduced = dict(entry)
            if "externals" in entry:
                reduced["externals"] = sorted(
                    {external["spec"].split("@")[0].split()[0] for external in entry["externals"]}
                )
            packages[name] = reduced
        out[key] = packages
    return out


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Compare what Spack has been told with what the shell roles left."
    )
    parser.add_argument("--spack", required=True)
    parser.add_argument("--dump", action="store_true")
    parser.add_argument("--expected")
    args = parser.parse_args()
    now = dump(args.spack)
    if args.dump:
        print(json.dumps(now, indent=1, sort_keys=True))
        return 0
    shell = json.loads(Path(args.expected).read_text())
    # The decided difference must be a difference: the shell had the two
    # settings in the user scope and not in the site scope.
    for name in MOVED:
        if not shell[f"user:{name}"] or shell[f"site:{name}"]:
            sys.exit(f"the expected file does not hold the shell's {name} in the user scope alone")
    ours, theirs = comparable(now), comparable(as_decided(shell))
    problems = []
    for key in sorted(theirs):
        if ours[key] == theirs[key]:
            continue
        if not key.endswith(":packages"):
            now_text, shell_text = (json.dumps(side[key], sort_keys=True) for side in (ours, theirs))
            problems.append(f"{key}: now {now_text}, the shell left {shell_text}")
            continue
        for name in sorted(set(ours[key]) | set(theirs[key])):
            if ours[key].get(name) != theirs[key].get(name):
                problems.append(
                    f"{key}:{name}: now {json.dumps(ours[key].get(name), sort_keys=True)}, "
                    f"the shell left {json.dumps(theirs[key].get(name), sort_keys=True)}"
                )
    for problem in problems:
        print(f"DIFFERS {problem}", file=sys.stderr)
    if problems:
        return 1
    externals = sum(1 for entry in now["site:packages"].values() if entry.get("externals"))
    print(
        f"as the shell roles left it: {externals} packages with externals, the providers and the mirror "
        f"in the site scope; {' and '.join(MOVED)} now in the site scope, not the user's"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
