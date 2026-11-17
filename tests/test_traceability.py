"""Every task says which lines of the scripts it replaces, and no line is lost."""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml
from support import (
    FUNCS,
    LEGACY,
    OPS_ROLES,
    OPS_SCRIPTS,
    ROLE_FUNCTIONS,
    SETUP,
    UNIT,
    expand,
    functions,
    lines_of,
)

TASK = re.compile(r"^(\s*)- name: (.+)$")
# A step of a list for the csis_spack collection's setup role (stage 11). It
# stands where a task stood, and says what it replaces in the same way.
STEP = re.compile(r"^(\s*)- (kind: .+)$")
REPLACES = re.compile(r"#\s*Replaces (?P<file>[\w./-]+) (?P<lines>L\d+(?:-L\d+)?(?: L\d+(?:-L\d+)?)*)\s*$")
NEW = re.compile(r"#\s*New: \S")

PLAYBOOKS = [UNIT / "site.yml", UNIT / "node-image.yml", UNIT / "users.yml", UNIT / "jupyterhub.yml"]
TASK_FILES = sorted(UNIT.glob("roles/*/tasks/*.yml"))

# Lines of a shell script that do nothing a task would have to do.
STRUCTURE = re.compile(r"(fi|else|then|do|done|\{|\}|EOF|esac|;;|return)")
MESSAGE = re.compile(r"echo\b[^|>]*")
SHELL_STATE = {"home=$PWD", "cd $home", "set +x", "set -x"}
ASSIGNMENT = re.compile(r"(local )?[A-Za-z_]\w*=[^`]*")


def is_action(line: str) -> bool:
    """Say whether a script line does something."""
    text = line.strip()
    if not text or text.startswith("#"):
        return False
    if STRUCTURE.fullmatch(text) or MESSAGE.fullmatch(text) or text in SHELL_STATE:
        return False
    return not (ASSIGNMENT.fullmatch(text) and "$(" not in text)


class Claim:
    """One task's statement about where it comes from."""

    def __init__(self, source: Path, number: int, name: str, comments: list[str]) -> None:
        self.source, self.number, self.name = source, number, name
        self.replaces: dict[str, set[int]] = {}
        self.new = any(NEW.match(comment) for comment in comments)
        for comment in comments:
            match = REPLACES.match(comment)
            if match:
                self.replaces.setdefault(match["file"], set()).update(expand(match["lines"]))

    def __str__(self) -> str:
        return f"{self.source.relative_to(UNIT)}:{self.number} {self.name}"


def claims_in(path: Path) -> list[Claim]:
    found: list[Claim] = []
    lines = path.read_text().splitlines()
    for index, line in enumerate(lines):
        match = TASK.match(line) or STEP.match(line)
        if not match or (path in PLAYBOOKS and not match.group(1)):
            continue
        comments: list[str] = []
        above = index - 1
        while above >= 0 and lines[above].strip().startswith("#"):
            comments.append(lines[above].strip())
            above -= 1
        found.append(Claim(path, index + 1, match.group(2), comments))
    return found


CLAIMS = [claim for path in [*PLAYBOOKS, *TASK_FILES] for claim in claims_in(path)]


def test_there_are_tasks_to_check() -> None:
    assert len({path.parent.parent for path in TASK_FILES}) == len(ROLE_FUNCTIONS) + len(OPS_ROLES)
    assert len(CLAIMS) > 100


def test_the_steps_of_the_setup_lists_are_checked_like_tasks() -> None:
    steps = [claim for claim in CLAIMS if claim.name.startswith("kind: ")]
    by_role: dict[str, int] = {}
    for claim in steps:
        by_role[claim.source.parent.parent.name] = by_role.get(claim.source.parent.parent.name, 0) + 1
    assert by_role == {"spack": 10, "intel_oneapi": 4}
    # Every step replaces lines of a script, but stage 12's removal of what
    # the script left in the wrong scope, which is new.
    assert [claim.name for claim in steps if not claim.replaces] == ["kind: config"]
    assert all(claim.replaces or claim.new for claim in steps)


@pytest.mark.parametrize("claim", CLAIMS, ids=str)
def test_a_task_says_what_it_replaces_or_why_it_is_new(claim: Claim) -> None:
    assert claim.replaces or claim.new, "put '# Replaces <file> L<n>' or '# New: <why>' above the task"


@pytest.mark.parametrize("claim", [claim for claim in CLAIMS if claim.replaces], ids=str)
def test_the_lines_a_task_names_exist_and_belong_to_its_function(claim: Claim) -> None:
    role = claim.source.parent.parent.name if claim.source in TASK_FILES else None
    for file, numbers in claim.replaces.items():
        script = LEGACY / file
        assert script.is_file(), f"no such script: {file}"
        assert max(numbers) < len(lines_of(script)), f"{file} has no line {max(numbers)}"
        if role and script == FUNCS:
            allowed = {n for function in ROLE_FUNCTIONS[role] for n in functions()[function]}
            assert numbers <= allowed, f"lines outside {ROLE_FUNCTIONS[role]}: {sorted(numbers - allowed)}"


def not_carried() -> dict[str, set[int]]:
    entries = yaml.safe_load((UNIT / "tests" / "not_carried.yml").read_text())
    found: dict[str, set[int]] = {}
    for entry in entries:
        assert entry["why"].strip()
        found.setdefault(entry["file"], set()).update(expand(entry["lines"]))
    return found


def accounted_for(file: str) -> set[int]:
    claimed = {n for claim in CLAIMS for n in claim.replaces.get(file, set())}
    return claimed | not_carried().get(file, set())


def unaccounted(script: Path, numbers: range) -> list[str]:
    lines = lines_of(script)
    known = accounted_for(script.name)
    return [f"L{n}: {lines[n].strip()}" for n in numbers if is_action(lines[n]) and n not in known]


CALLED = [function for names in ROLE_FUNCTIONS.values() for function in names]


# Python lines that do nothing a task would have to do: structure, messages,
# imports, and the lines of docstrings.
PYTHON_STRUCTURE = re.compile(
    r"(def \w+\(.*\):|try:|except\b.*:|else:|return\b.*|pass|print\(.*\)|import \w.*|from \S+ import .*"
    r"|[\]\)}]|if __name__ == .__main__.:|main\(\))"
)


def python_actions(script: Path) -> set[int]:
    """Give the lines of a Python script that do something."""
    found: set[int] = set()
    in_docstring = False
    for number, line in enumerate(lines_of(script)):
        text = line.strip()
        quotes = text.count('"""') + text.count("'''")
        if in_docstring or quotes:
            in_docstring = in_docstring != (quotes % 2 == 1)
            continue
        if number and text and not text.startswith("#") and not PYTHON_STRUCTURE.fullmatch(text):
            found.add(number)
    return found


@pytest.mark.parametrize("name", OPS_SCRIPTS)
def test_every_line_of_an_operator_script_is_replaced_or_explained(name: str) -> None:
    script = LEGACY / name
    lines = lines_of(script)
    known = accounted_for(name)
    if script.suffix == ".py":
        acting = python_actions(script)
    else:
        acting = {n for n in range(1, len(lines)) if is_action(lines[n])}
    assert [f"L{n}: {lines[n].strip()}" for n in sorted(acting - known)] == []


@pytest.mark.parametrize("function", CALLED)
def test_every_line_of_a_function_is_replaced_or_explained(function: str) -> None:
    assert unaccounted(FUNCS, functions()[function]) == []


@pytest.mark.parametrize("script", [SETUP, LEGACY / "create_image.sh"], ids=lambda path: path.name)
def test_every_line_of_a_script_is_replaced_or_explained(script: Path) -> None:
    assert unaccounted(script, range(1, len(lines_of(script)))) == []


def test_what_is_not_carried_is_not_also_replaced() -> None:
    for file, numbers in not_carried().items():
        claimed = {n for claim in CLAIMS for n in claim.replaces.get(file, set())}
        assert not (numbers & claimed), (
            f"{file}: both replaced and listed as not carried: {sorted(numbers & claimed)}"
        )


def test_the_roles_come_in_the_scripts_order() -> None:
    lines = lines_of(SETUP)
    called = [line.split()[0] for line in lines if line.split() and line.split()[0] in functions()]
    role_of = {function: role for role, names in ROLE_FUNCTIONS.items() for function in names}
    expected: list[str] = []
    for function in called:
        if not expected or expected[-1] != role_of[function]:
            expected.append(role_of[function])
    play = yaml.safe_load((UNIT / "site.yml").read_text())[0]
    block = next(task["block"] for task in play["tasks"] if "block" in task)
    imported = [
        task["ansible.builtin.import_role"]["name"] for task in block if "ansible.builtin.import_role" in task
    ]
    assert imported == expected
    assert [task["tags"] for task in block if "ansible.builtin.import_role" in task] == [
        [name] for name in expected
    ]
