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
        # Version 2 as written; version 3 where the first run (2026-11-23) changed a box.
        assert {match["v"] for match in parsed if match} <= {"2", "3"}, step


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


def box(step: str, n: int) -> str:
    """Give the body of one box."""
    for label, _, text in steps():
        if label == step:
            return list(BOX.finditer(text))[n - 1]["body"]
    raise KeyError(step)


# What the first run found (Cloud-Sandbox's spec 001, 2026-11-23), held here.


def test_every_box_that_runs_tofu_against_aws_exports_the_sessions_credentials() -> None:
    # OpenTofu's AWS provider cannot read the noaa SSO profile; the CLI can.
    for step, n in (("A4", 1), ("A5", 1), ("B2", 2), ("E2", 1)):
        body = box(step, n)
        assert "aws configure export-credentials --profile noaa --format env" in body, step
        assert "unset AWS_PROFILE" in body, step


def test_jupyterhub_is_given_the_settings_only_a_site_can_give() -> None:
    body = box("B7", 1)
    for name in (
        "jupyterhub_server_name",
        "jupyterhub_oauth_callback_url",
        "jupyterhub_ssl_certificate",
        "jupyterhub_ssl_certificate_key",
        "jupyterhub_admin_users_literal",
        "jupyterhub_username_map_literal",
    ):
        assert name in body, name


def test_a_failed_boot_replaces_the_node_with_its_efs_volume() -> None:
    body = box("B2", 2)
    assert "-replace=aws_efs_file_system.main_efs" in body
    assert "-replace=aws_instance.head_node" in body


def test_the_search_for_leftovers_does_not_trust_the_tagging_index_alone() -> None:
    body = box("E4", 1)
    assert "describe-instances" in body
    assert "describe-volumes" in body


def test_the_networks_comparison_ignores_order_and_free_address_counts() -> None:
    body = box("E5", 1)
    assert "sort_by" in body
    assert "AvailableIpAddressCount" in body


def test_no_text_names_a_box_the_page_does_not_have() -> None:
    named = set(re.findall(r"\bbox(?:es)? ([A-E]\d)\b", PAGE.read_text()))
    assert named <= {step for step, _, _ in steps()}, named - {step for step, _, _ in steps()}
