"""docs/LIVE-PROOF.md keeps the form a procedure run box by box needs (Cloud-Sandbox's spec 001).

Every box is numbered and versioned, under a step whose heading says where it
runs; every decision states its default; and every box that creates, changes or
removes something on AWS is announced as such, so that it is run only on the
operator's word.
"""

from __future__ import annotations

import re
from pathlib import Path

PAGE = Path(__file__).resolve().parents[1] / "docs" / "LIVE-PROOF.md"
HEADING = re.compile(r"^### (?P<step>[A-E]\d)\. .*$", re.MULTILINE)
BOX = re.compile(r"```sh\n(?P<body>.*?)```", re.DOTALL)
FIRST = re.compile(r"^# (?P<step>[A-E]\d) -- box (?P<n>\d+) of (?P<m>\d+) -- v(?P<v>\d+)$")
CHANGES_AWS = re.compile(
    r"tofu\"? apply|\" apply |destroy -var-file|node-image\.yml|deregister-image|delete-snapshot"
)


def steps() -> list[tuple[str, str, str]]:
    """Give each step's label, heading line and text."""
    text = PAGE.read_text()
    found = list(HEADING.finditer(text))
    ends = [match.start() for match in found[1:]] + [text.index("## What to bring back")]
    return [
        (match["step"], match.group(0), text[match.start() : end])
        for match, end in zip(found, ends, strict=True)
    ]


def test_every_step_says_where_it_runs() -> None:
    wrong = [
        heading
        for _, heading, _ in steps()
        if "your local machine" not in heading and "the head node" not in heading
    ]
    assert not wrong, wrong


def test_every_box_is_numbered_and_versioned_within_its_step() -> None:
    for step, _, text in steps():
        firsts = [box["body"].splitlines()[0] for box in BOX.finditer(text)]
        assert firsts, f"{step} has no box"
        parsed = [FIRST.match(line) for line in firsts]
        assert all(parsed), (step, firsts)
        assert {match["step"] for match in parsed if match} == {step}
        numbers = [int(match["n"]) for match in parsed if match]
        assert numbers == list(range(1, len(numbers) + 1)), (step, numbers)
        assert {int(match["m"]) for match in parsed if match} == {len(numbers)}, step
        assert {match["v"] for match in parsed if match} == {"2"}, step


def test_every_decision_states_its_default() -> None:
    lines = [line for line in PAGE.read_text().splitlines() if "**YOUR DECISION:**" in line]
    assert lines
    text = PAGE.read_text()
    for line in lines:
        after = text[text.index(line) :][:400]
        assert "**Default:**" in after, line


def test_every_box_that_changes_aws_is_announced() -> None:
    text = PAGE.read_text()
    last = 0
    for box in BOX.finditer(text):
        if CHANGES_AWS.search(box["body"]):
            before = text[last : box.start()]
            assert "**Changes AWS:**" in before, box["body"].splitlines()[0]
        last = box.end()
