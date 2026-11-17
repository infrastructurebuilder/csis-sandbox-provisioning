"""Stage 12: which of the script's two settings in the login user's scope are leftovers.

The spack role's tasks/user_scope.yml is applied alone against scope files
written here, as they are on a head node built before stage 11 (stage 11's
dump of what the shell roles left), and as someone may have changed them.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
import yaml
from support import UNIT

EXPECTED = UNIT / "tests" / "container" / "expected-spack-config.json"
SITE_CONFIG = {"config": {"install_tree": {"padded_length": 73}}}
SITE_MODULES = {"modules": {"default": {"enable": ["tcl"]}}}
REMOVE_BOTH = {"config": {"install_tree": {"padded_length": None}}, "modules": {"default": {"enable": None}}}


def decide(tmp_path: Path, user: dict[str, Any], site: dict[str, Any]) -> dict[str, Any]:
    home, spack = tmp_path / "home", tmp_path / "spack"
    for directory, files in ((home / ".spack", user), (spack / "etc" / "spack" / "site", site)):
        directory.mkdir(parents=True, exist_ok=True)
        for name, data in files.items():
            (directory / name).write_text(yaml.safe_dump(data))
    out = tmp_path / "decided.json"
    variables = {"sandbox_user_home": str(home), "spack_dir": str(spack), "user_scope_out": str(out)}
    command = [
        str(Path(sys.executable).parent / "ansible-playbook"),
        "-i",
        "localhost,",
        "-e",
        json.dumps(variables | {"ansible_python_interpreter": sys.executable}),
        "tests/user-scope.yml",
    ]
    done = subprocess.run(command, cwd=UNIT, capture_output=True, text=True, check=False)
    assert done.returncode == 0, done.stdout + done.stderr
    return json.loads(out.read_text())


def site() -> dict[str, Any]:
    return {"config.yaml": SITE_CONFIG, "modules.yaml": SITE_MODULES}


def test_the_two_paths_are_exactly_what_the_shell_left_in_the_user_scope() -> None:
    dump = json.loads(EXPECTED.read_text())
    assert dump["user:config"] == SITE_CONFIG["config"]
    assert dump["user:modules"] == SITE_MODULES["modules"]
    assert dump["user:packages"] == {} and dump["user:mirrors"] == {}


def test_a_node_built_before_stage_11_has_two_leftovers(tmp_path: Path) -> None:
    decided = decide(tmp_path, site(), site())
    assert decided == {"leftover": REMOVE_BOTH, "chosen": []}


def test_a_node_built_since_has_none(tmp_path: Path) -> None:
    assert decide(tmp_path, {}, site()) == {"leftover": {}, "chosen": []}


def test_a_value_that_differs_from_the_sites_was_chosen_and_is_kept(tmp_path: Path) -> None:
    user = {"config.yaml": SITE_CONFIG, "modules.yaml": {"modules": {"default": {"enable": ["lmod"]}}}}
    decided = decide(tmp_path, user, site())
    assert decided["leftover"] == {"config": {"install_tree": {"padded_length": None}}}
    assert decided["chosen"] == [{"path": "modules:default:enable", "user": ["lmod"], "site": ["tcl"]}]


def test_other_settings_in_the_user_scope_are_not_looked_at(tmp_path: Path) -> None:
    user = {"config.yaml": {"config": {"install_tree": {"root": "/save/me"}, "build_jobs": 4}}}
    assert decide(tmp_path, user, site()) == {"leftover": {}, "chosen": []}


@pytest.mark.parametrize("missing", ["config.yaml", "modules.yaml"])
def test_a_scope_file_that_is_not_there_holds_nothing(tmp_path: Path, missing: str) -> None:
    user = {name: data for name, data in site().items() if name != missing}
    decided = decide(tmp_path, user, site())
    assert len(decided["leftover"]) == 1


def test_an_empty_scope_file_holds_nothing(tmp_path: Path) -> None:
    (tmp_path / "home" / ".spack").mkdir(parents=True)
    (tmp_path / "home" / ".spack" / "config.yaml").write_text("")
    assert decide(tmp_path, {"modules.yaml": SITE_MODULES}, site())["leftover"] == {
        "modules": {"default": {"enable": None}}
    }
