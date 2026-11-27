"""ufs-stack.yml: spack-stack for UFS Coastal (Cloud-Sandbox's spec 004).

What the playbook must never do, what it carries from the scripts, and that
the version it builds is a tag or a commit, never a branch.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
import yaml
from support import FUNCS, UNIT, functions, lines_of
from test_traceability import CLAIMS, UFS_STACK_FUNCTIONS

PLAYBOOK = UNIT / "ufs-stack.yml"
COMMIT = re.compile(r"[0-9a-f]{40}")


def play() -> dict[str, Any]:
    plays = yaml.safe_load(PLAYBOOK.read_text())
    assert isinstance(plays, list) and len(plays) == 1
    return plays[0]


def walk(node: Any):
    """Give every mapping and every string in a loaded YAML document."""
    if isinstance(node, dict):
        yield node
        for value in node.values():
            yield from walk(value)
    elif isinstance(node, list):
        for item in node:
            yield from walk(item)
    elif isinstance(node, str):
        yield node


def code_lines() -> list[str]:
    """The playbook's lines but its comments."""
    return [line for line in PLAYBOOK.read_text().splitlines() if not line.strip().startswith("#")]


def test_the_playbook_is_beside_site_yml_and_not_imported_by_it() -> None:
    assert PLAYBOOK.is_file()
    assert "ufs-stack" not in (UNIT / "site.yml").read_text()
    assert play()["hosts"] == "sandbox_head"


def test_no_step_names_the_system_scope() -> None:
    # FR-004: /etc/spack is the sandbox's Spack's too. The script wrote there
    # (--scope system, L393-L405), with the system scope pointed at the
    # environment's own site/ directory.
    for node in walk(play()):
        if isinstance(node, dict):
            assert node.get("scope") != "system", node
        else:
            assert not re.search(r"--scope[ =]system|/etc/spack", node), node


def test_no_step_or_task_names_a_gcc_toolset() -> None:
    # FR-002: RHEL 10's own GCC; the script's gcc-toolset lines (L380, L437)
    # are not carried.
    assert [line for line in code_lines() if "gcc-toolset" in line or "/opt/rh/" in line] == []


def test_the_lines_the_playbook_names_belong_to_the_two_functions() -> None:
    allowed = {n for function in UFS_STACK_FUNCTIONS for n in functions()[function]}
    claims = [claim for claim in CLAIMS if claim.source == PLAYBOOK]
    assert claims, "ufs-stack.yml is not in test_traceability's PLAYBOOKS"
    for claim in claims:
        assert set(claim.replaces) <= {FUNCS.name}, f"{claim}: {sorted(claim.replaces)}"
        outside = claim.replaces.get(FUNCS.name, set()) - allowed
        assert not outside, f"{claim}: lines outside {UFS_STACK_FUNCTIONS}: {sorted(outside)}"


def test_the_two_functions_are_the_ones_named() -> None:
    lines = lines_of(FUNCS)
    for function in UFS_STACK_FUNCTIONS:
        start = functions()[function].start - 1
        assert lines[start].startswith(f"{function} ()"), (function, lines[start])


def test_the_version_is_a_commit_or_a_tag_and_the_directory_names_it() -> None:
    defaults = play()["vars"]
    version = defaults["ufs_stack_version"]
    assert COMMIT.fullmatch(version) or not re.fullmatch(r"[0-9a-f]{7,39}", version), (
        "an abbreviated commit cannot be told from a branch by its name; give all 40 characters"
    )
    assert "{{ ufs_stack_version }}" in defaults["ufs_stack_dir"]


def ref_check(*extra: str) -> subprocess.CompletedProcess[str]:
    """Run only the playbook's check of the version, on this machine."""
    command = [
        str(Path(sys.executable).parent / "ansible-playbook"),
        "-i",
        "inventories/local/hosts.yml",
        "--tags",
        "ufs_stack_ref",
        "ufs-stack.yml",
        *extra,
    ]
    return subprocess.run(command, cwd=UNIT, capture_output=True, text=True, check=False)


@pytest.mark.slow
def test_the_version_is_not_a_branch_of_the_repository() -> None:
    defaults = play()["vars"]
    done = subprocess.run(
        ["git", "ls-remote", "--heads", "--tags", defaults["ufs_stack_repo"]],
        capture_output=True,
        text=True,
        check=True,
    )
    refs = {line.split("\t")[1] for line in done.stdout.splitlines()}
    assert f"refs/heads/{defaults['ufs_stack_version']}" not in refs
    passed = ref_check()
    assert passed.returncode == 0, passed.stdout + passed.stderr


@pytest.mark.slow
def test_the_playbook_stops_before_cloning_when_given_a_branch(tmp_path: Path) -> None:
    # aws-ioossb is the branch the script cloned (L347).
    clone = tmp_path / "spack-stack"
    done = ref_check("-e", "ufs_stack_version=aws-ioossb", "-e", f"ufs_stack_dir={clone}")
    assert done.returncode != 0
    assert "ufs_stack_version" in done.stdout
    assert not clone.exists()
