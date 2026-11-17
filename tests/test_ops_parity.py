"""The stage 7 roles write what the operator scripts and files wrote.

The templates are rendered by Ansible with the roles' defaults, and with the
values the original files had, and compared with those files. The lines the
users role adds to the shell files are compared with the lists in
add-users.py, read with Python's own parser.
"""

from __future__ import annotations

import ast
import csv
import json
import subprocess
import sys
from pathlib import Path

import pytest
import yaml
from support import JUPYTERHUB_ORIGINALS, LEGACY, UNIT

ORIGINAL_SPACK = "/save/environments/spack.v0.22.5"
SCRATCH_USER = "@USER@"


def render(out: Path, extra: dict[str, object]) -> Path:
    """Render the stage 7 templates into ``out`` and return it."""
    out.mkdir(parents=True, exist_ok=True)
    command = [
        str(Path(sys.executable).parent / "ansible-playbook"),
        "tests/render-templates.yml",
        "-e",
        json.dumps({"render_out": str(out), **extra}),
    ]
    done = subprocess.run(command, cwd=UNIT, capture_output=True, text=True, check=False)
    assert done.returncode == 0, done.stdout + done.stderr
    return out


@pytest.fixture(scope="module")
def defaults(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return render(tmp_path_factory.mktemp("defaults"), JUPYTERHUB_ORIGINALS)


@pytest.fixture(scope="module")
def as_originals(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return render(
        tmp_path_factory.mktemp("originals"),
        JUPYTERHUB_ORIGINALS
        | {
            "jupyterhub_spawn_users": ["jupyter", "jonmjoyce"],
            "sandbox_users_lustre_mounters": ["patrick"],
            "spack_dir": ORIGINAL_SPACK,
        },
    )


def active(text: str) -> list[str]:
    """Give the lines that are neither blank nor comments, with spaces made even."""
    return [
        " ".join(line.split())
        for line in text.splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]


@pytest.mark.parametrize("name", ["jupyterhub_config.py", "jupyterhub.conf"])
def test_with_its_defaults_and_the_originals_site_values_a_template_writes_the_original(
    defaults: Path, name: str
) -> None:
    assert (defaults / name).read_text() == (LEGACY / "system" / name).read_text()


def test_the_hubs_sudoers_file_is_the_original_given_its_users(as_originals: Path) -> None:
    # The original lacks a final newline; the rendered file has one.
    assert (as_originals / "jupytersudoers").read_text() == (
        LEGACY / "system" / "jupytersudoers"
    ).read_text() + "\n"


def test_by_default_the_hubs_sudoers_file_names_no_person(defaults: Path) -> None:
    assert "Runas_Alias JUPYTER_USERS = jupyter\n" in (defaults / "jupytersudoers").read_text()


def test_the_lustre_sudoers_file_has_the_originals_rules(as_originals: Path) -> None:
    original = active((LEGACY / "system" / "sudoers.d.sandbox-modelers").read_text())
    assert active((as_originals / "sandbox-modelers.sudoers").read_text()) == original


def script_list(function: str, variable: str) -> list[str]:
    """Evaluate one list of strings in add-users.py, with the user as a placeholder."""
    tree = ast.parse((LEGACY / "add-users.py").read_text())
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == function:
            for statement in node.body:
                if (
                    isinstance(statement, ast.Assign)
                    and isinstance(statement.targets[0], ast.Name)
                    and statement.targets[0].id == variable
                ):
                    names = {"username": SCRATCH_USER, "SPACK_VERSION": Path(ORIGINAL_SPACK).name}
                    return eval(compile(ast.Expression(statement.value), "add-users.py", "eval"), {}, names)
    raise AssertionError(f"no {variable} in {function}()")


def task_lines(name: str) -> list[str]:
    """Give the lines a task of the users role writes, as the script would for its user."""
    tasks = yaml.safe_load((UNIT / "roles" / "sandbox_users" / "tasks" / "main.yml").read_text())
    task = next(task for task in tasks if task["name"] == name)
    lines = next(iter(task["vars"].values()))
    return [line.replace("{{ spack_dir }}", ORIGINAL_SPACK) for line in lines]


def test_the_tcsh_lines_are_the_scripts() -> None:
    assert task_lines("Add the aliases for tcsh") == script_list("setup_shell_configs", "tcshrc_lines")


def test_the_bash_lines_are_the_scripts_without_its_blank_line() -> None:
    script = [line for line in script_list("setup_shell_configs", "bashrc_lines") if line]
    assert task_lines("Add the module and Spack set-up and the aliases for bash") == script


def test_the_spack_configuration_is_the_scripts(as_originals: Path) -> None:
    script = "\n".join(script_list("setup_shell_configs", "spackcfg_lines"))
    assert (as_originals / "spack-config.yaml").read_text().rstrip("\n") == script


def test_the_test_users_are_the_sample_list() -> None:
    fields = ["FullName", "email", "username", "uid", "groups", "gids", "public_key", "ip_address"]
    with (LEGACY / "system" / "sample.users.csv").open(newline="") as handle:
        rows = list(csv.DictReader((line for line in handle if not line.startswith("#")), fieldnames=fields))
    users = yaml.safe_load((UNIT / "tests" / "container" / "users.yml").read_text())["sandbox_users_present"]
    assert len(rows) == len(users) == 1
    row, user = rows[0], users[0]
    assert user["full_name"] == row["FullName"]
    assert user["email"] == row["email"]
    assert user["username"] == row["username"]
    assert str(user["uid"]) == row["uid"]
    assert [group["name"] for group in user["groups"]] == row["groups"].split(";")
    assert [str(group["gid"]) for group in user["groups"]] == row["gids"].split(";")


def check_jupyterhub(extra: dict[str, object]) -> subprocess.CompletedProcess[str]:
    command = [
        str(Path(sys.executable).parent / "ansible-playbook"),
        "tests/jupyterhub-check.yml",
        "-e",
        json.dumps(extra),
    ]
    return subprocess.run(command, cwd=UNIT, capture_output=True, text=True, check=False)


def test_the_hub_refuses_to_install_without_the_sites_settings() -> None:
    done = check_jupyterhub({})
    assert done.returncode != 0
    for name in JUPYTERHUB_ORIGINALS:
        assert name in done.stdout


def test_the_hub_names_only_what_is_missing_or_empty() -> None:
    given = JUPYTERHUB_ORIGINALS | {"jupyterhub_ssl_certificate": "  "}
    del given["jupyterhub_server_name"]
    done = check_jupyterhub(given)
    assert done.returncode != 0
    assert "jupyterhub_server_name, jupyterhub_ssl_certificate." in " ".join(done.stdout.split())


def test_the_hub_installs_with_the_sites_settings() -> None:
    done = check_jupyterhub(JUPYTERHUB_ORIGINALS)
    assert done.returncode == 0, done.stdout + done.stderr


def test_no_site_setting_is_left_in_the_hubs_defaults() -> None:
    defaults = yaml.safe_load((UNIT / "roles" / "jupyterhub" / "defaults" / "main.yml").read_text())
    assert not set(JUPYTERHUB_ORIGINALS) & set(defaults)
    assert set(defaults["jupyterhub_required_variables"]) == set(JUPYTERHUB_ORIGINALS)
    text = (UNIT / "roles" / "jupyterhub" / "defaults" / "main.yml").read_text()
    for value in ("rpsgroup", "star_ioos_us", "sandbox-dev.ioos.us"):
        assert all(value not in line or line.lstrip().startswith("#") for line in text.splitlines())
