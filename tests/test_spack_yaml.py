"""The environment's spack.yaml, written from the role's template (stage 9).

The template is rendered by Ansible with the role's defaults. What it writes
must be the role's two variables and nothing else, so that what the parity
test holds to the script is what lands on the head node.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest
import yaml
from support import JUPYTERHUB_ORIGINALS, UNIT, rendered


@pytest.fixture(scope="module")
def manifest(tmp_path_factory: pytest.TempPathFactory) -> str:
    out = tmp_path_factory.mktemp("spack-yaml")
    command = [
        str(Path(sys.executable).parent / "ansible-playbook"),
        "tests/render-templates.yml",
        "-e",
        # The hub's templates are rendered too, and need the site's settings.
        json.dumps({"render_out": str(out)} | JUPYTERHUB_ORIGINALS),
    ]
    done = subprocess.run(command, cwd=UNIT, capture_output=True, text=True, check=False)
    assert done.returncode == 0, done.stdout + done.stderr
    return (out / "spack.yaml").read_text()


@pytest.fixture(scope="module")
def values(tmp_path_factory: pytest.TempPathFactory) -> dict:
    return rendered(tmp_path_factory.mktemp("render") / "values.json")


def test_spack_yaml_is_the_specs_and_the_configuration(manifest: str, values: dict) -> None:
    assert yaml.safe_load(manifest) == {"spack": {"specs": values["spack_specs"], **values["spack_config"]}}


def test_spack_yaml_says_it_is_written_by_ansible(manifest: str) -> None:
    assert manifest.startswith("# Ansible managed")
    assert "overwritten" in manifest.splitlines()[2]


def test_the_specs_come_first_and_keep_their_order(manifest: str, values: dict) -> None:
    body = yaml.safe_load(manifest)["spack"]
    assert next(iter(body)) == "specs"
    assert body["specs"] == values["spack_specs"]
