"""The values the playbooks use are the values the scripts compute."""

from __future__ import annotations

import re
import shlex
import subprocess
from pathlib import Path

import pytest
import yaml
from support import ENVIRONMENT, FUNCS, UNIT, VARIABLES, functions, lines_of, rendered, script_values

DEFAULT_NPROC = 8


@pytest.fixture(scope="module")
def values(tmp_path_factory: pytest.TempPathFactory) -> dict:
    return rendered(tmp_path_factory.mktemp("render") / "values.json", nproc=DEFAULT_NPROC)


@pytest.fixture(scope="module")
def script() -> dict[str, str]:
    return script_values(DEFAULT_NPROC)


def body(function: str) -> list[str]:
    """Give the lines of one function, without blank lines and comments."""
    lines = lines_of(FUNCS)
    stripped = [lines[number].strip() for number in functions()[function]]
    return [line for line in stripped if line and not line.startswith("#")]


def substitute(text: str, known: dict[str, str]) -> str:
    """Put the script's values in place of $NAME and ${NAME}."""
    return re.sub(r"\$\{?(\w+)\}?", lambda match: known.get(match.group(1), match.group(0)), text)


def test_every_exported_variable_is_mapped() -> None:
    exported = set(re.findall(r"^\s*export (\w+)=", ENVIRONMENT.read_text(), re.MULTILINE))
    assert exported == set(VARIABLES)


def test_every_mapped_variable_exists() -> None:
    defined = yaml.safe_load((UNIT / "group_vars" / "all.yml").read_text())
    assert set(VARIABLES.values()) <= set(defined)


@pytest.mark.parametrize("name", sorted(set(VARIABLES) - {"ami_name"}))
def test_a_variable_has_the_value_the_script_gives_it(
    name: str, values: dict, script: dict[str, str]
) -> None:
    assert str(values[name]) == script[name]


def test_the_fallback_image_name_has_the_scripts_form(values: dict, script: dict[str, str]) -> None:
    form = re.compile(r"IOOS-Cloud-Sandbox-\d{8}_\d\d-\d\d")
    assert form.fullmatch(script["ami_name"])
    assert form.fullmatch(values["ami_name"])


@pytest.mark.parametrize("nproc", [1, 2, 3, 96])
def test_build_jobs_follow_the_processor_count(nproc: int, tmp_path: Path) -> None:
    ours, theirs = rendered(tmp_path / "v.json", nproc=nproc), script_values(nproc)
    assert ours["JOBS"] == theirs["JOBS"]
    assert ours["SPACKOPTS"] == theirs["SPACKOPTS"]


@pytest.mark.parametrize("cache_only", [1, 0, -1])
def test_the_cache_flag_follows_the_setting(cache_only: int, tmp_path: Path) -> None:
    ours = rendered(tmp_path / "v.json", cache_only=cache_only)
    assert ours["SPACKOPTS"] == script_values(DEFAULT_NPROC, cache_only)["SPACKOPTS"]


def test_the_pip_list_is_the_scripts(values: dict, script: dict[str, str]) -> None:
    theirs = []
    for line in body("install_python_modules_user"):
        match = re.match(r"python3 -m pip install (--upgrade )?(\S+)", line)
        if match:
            spec = substitute(match.group(2).strip('"'), script)
            theirs.append({"spec": spec, "upgrade": bool(match.group(1))})
    assert values["pip"] == theirs
    assert len(theirs) == 14


def dnf_installs(function: str, known: dict[str, str]) -> list[str]:
    found: list[str] = []
    for line in body(function):
        match = re.match(r"sudo dnf -y install (.+)", line)
        if match:
            found.extend(substitute(match.group(1), known).split())
    return found


def test_the_base_packages_are_the_scripts(values: dict, script: dict[str, str]) -> None:
    defaults = yaml.safe_load((UNIT / "roles/base_system/defaults/main.yml").read_text())
    ours = [
        defaults["base_system_epel_release_url"],
        "rh-amazon-rhui-client",
        *values["dnf_base"],
        defaults["base_system_ssm_agent_url"],
        "environment-modules",
    ]
    assert ours == dnf_installs("setup_environment", script)


def test_the_intel_packages_are_the_scripts(values: dict, script: dict[str, str]) -> None:
    assert values["dnf_intel"] == dnf_installs("install_intel_oneapi_dnf", script)


def test_the_intel_modules_are_the_ones_the_script_loads(values: dict) -> None:
    theirs = [line.split()[2] for line in body("install_intel_oneapi_dnf") if line.startswith("module load ")]
    assert values["intel_modules"] == theirs


def test_spack_is_told_about_the_same_externals_and_providers(values: dict, script: dict[str, str]) -> None:
    """The role's one mapping is what the script's two calls and five commands add up to."""
    text = "\n".join(body("install_intel_oneapi_dnf")).replace("\\\n", " ")
    externals = re.findall(r"add_spack_site_external\s+(\S+)\s+(\S+)\s+(\S+)", text)
    assert len(externals) == 2
    # What add_spack_site_external appends for each (funcs-setup-instance.sh L725-L730).
    expected: dict = {
        package: {"externals": [{"spec": spec, "prefix": prefix}], "buildable": False}
        for package, spec, prefix in externals
    }
    providers = re.findall(r"spack config --scope site add '([^']+)'", text)
    assert len(providers) == 5
    for provider in providers:
        expected = merged(expected, config_add(provider)["packages"])
    assert values["spack_packages"] == expected


# What "spack env create" writes into a new spack.yaml besides an empty list of
# specs (Spack v1.2.0); the script keeps it, and so does the role.
SPACK_ENV_CREATE_DEFAULTS = {"view": True, "concretizer": {"unify": True}}


def config_add(path: str) -> dict:
    """Give the mapping that ``spack config add '<path>'`` adds, as Spack reads the path."""
    *keys, value = path.split(":")
    result: dict = {keys[-1]: yaml.safe_load(value)}
    for key in reversed(keys[:-1]):
        result = {key: result}
    return result


def merged(into: dict, extra: dict) -> dict:
    out = dict(into)
    for key, value in extra.items():
        out[key] = merged(out[key], value) if isinstance(value, dict) and key in out else value
    return out


def test_config_add_reads_a_path_as_spack_does() -> None:
    assert config_add("packages:all:require:[target=x86_64_v3]") == {
        "packages": {"all": {"require": ["target=x86_64_v3"]}}
    }
    assert config_add("concretizer:targets:granularity:generic") == {
        "concretizer": {"targets": {"granularity": "generic"}}
    }


def test_the_spack_environment_gets_the_same_settings_and_specs(values: dict, script: dict[str, str]) -> None:
    lines = "\n".join(body("create_spack-environment"))
    settings = re.findall(r"^\s*spack config add '([^']+)'", lines, re.MULTILINE)
    assert len(settings) == 3
    expected = SPACK_ENV_CREATE_DEFAULTS
    for setting in settings:
        expected = merged(expected, config_add(setting))
    assert values["spack_config"] == expected
    known = {**script, "COMPILER": f"intel-oneapi-compilers@{script['ONEAPI_VER']}"}
    specs = re.findall(r'^spack add "([^"]+)"', "\n".join(body("build_spack-environment")), re.MULTILINE)
    assert values["spack_specs"] == [substitute(spec, known) for spec in specs]


# --- Stage 11: the script's Spack commands, as lists of steps ----------------
#
# The spack and intel_oneapi roles hand lists of steps to the setup role of the
# infrastructurebuilder.csis_spack collection. Each list is held here to the
# Spack commands of the script it replaces, command for step, in order.

SETUP_ROLE = "infrastructurebuilder.csis_spack.setup"


def setup_lists(role: str) -> list[dict]:
    """Give the tasks of a role that apply the collection's setup role."""
    tasks = yaml.safe_load((UNIT / "roles" / role / "tasks" / "main.yml").read_text())
    return [task for task in tasks if task.get("ansible.builtin.include_role", {}).get("name") == SETUP_ROLE]


def as_steps(commands: list[str]) -> list[dict]:
    """Write a script's Spack commands as the steps that do the same.

    Consecutive ``config add`` commands for one scope are one ``config`` step,
    which is all the difference there is between a command and a step. The
    scope a command names is kept as "scope"; a command that names none
    writes to the user scope, and has none here.
    """
    steps: list[dict] = []
    for command in commands:
        words = shlex.split(command)[1:]
        scope = words[words.index("--scope") + 1] if "--scope" in words else None
        if scope:
            at = words.index("--scope")
            words = words[:at] + words[at + 2 :]
        if words[:2] == ["config", "add"]:
            setting = config_add(words[2])
            last = steps[-1] if steps else {}
            if last.get("kind") == "config" and last.get("scope") == scope:
                last["settings"] = merged(last["settings"], setting)
            else:
                steps.append({"kind": "config", "settings": setting} | ({"scope": scope} if scope else {}))
        elif words[:2] == ["compiler", "find"]:
            steps.append({"kind": "detect", "compilers": True} | ({"scope": scope} if scope else {}))
        elif words[:2] == ["external", "find"]:
            names = [word for word in words[2:] if not word.startswith("--")]
            step = {"kind": "detect", "externals": names or True}
            if "--not-buildable" in words:
                step["not_buildable"] = True
            steps.append(step | ({"scope": scope} if scope else {}))
        elif words[:2] == ["mirror", "add"]:
            steps.append(
                {"kind": "mirror", "name": words[2], "url": words[3]} | ({"scope": scope} if scope else {})
            )
        elif words[:2] == ["buildcache", "keys"]:
            assert words[2:] == ["--install", "--trust"]
            steps.append({"kind": "gpg_key", "from_mirrors": True})
        elif words[:2] == ["gpg", "trust"]:
            steps.append({"kind": "gpg_key", "key": words[2]})
        else:
            raise AssertionError(f"a Spack command the lists have no step for: {command}")
    return steps


def spack_commands(lines: list[str]) -> list[str]:
    return [line.split(" >&")[0] for line in lines if line.startswith("spack ")]


def test_as_steps_reads_commands_as_the_collection_would_carry_them_out() -> None:
    assert as_steps(
        [
            'spack config add "a:b:1"',
            "spack config add 'a:c:[x]'",
            "spack config --scope site add 'a:d:2'",
            "spack external find --not-buildable --scope site tool",
        ]
    ) == [
        {"kind": "config", "settings": {"a": {"b": 1, "c": ["x"]}}},
        {"kind": "config", "settings": {"a": {"d": 2}}, "scope": "site"},
        {"kind": "detect", "externals": ["tool"], "not_buildable": True, "scope": "site"},
    ]


def test_the_spack_roles_first_list_is_the_scripts_commands_in_order() -> None:
    task = setup_lists("spack")[0]
    assert task["vars"]["spack_setup_scope"] == "site"
    ours = task["vars"]["spack_setup"]
    theirs = as_steps(spack_commands(body("install_spack")))
    assert len(theirs) == 6
    # The one difference, decided in stage 11: the script's two settings have
    # no --scope and so are the login user's; the step has none either, and
    # takes the role's, which is the site scope.
    assert "scope" not in theirs[0]
    assert "scope" not in ours[0]
    assert ours[0] == theirs[0]
    # Everything else the script puts in the site scope, and so does the role.
    assert all(step.pop("scope", "site") == "site" for step in theirs[1:])
    assert ours[1:] == theirs[1:]
    assert task["ansible.builtin.include_role"]["apply"] == {
        "become": True,
        "become_user": "{{ sandbox_user }}",
    }


def test_the_intel_list_is_the_scripts_commands_in_order(values: dict, script: dict[str, str]) -> None:
    (task,) = setup_lists("intel_oneapi")
    ours = task["vars"]["spack_setup"]
    lines = body("install_intel_oneapi_dnf")
    # In the script: the modules are loaded, then "compiler find", then the two
    # externals, then five "config add", then "mirror add" (not carried, see
    # tests/not_carried.yml), then "buildcache keys".
    theirs = as_steps(spack_commands(lines))
    assert [step["kind"] for step in theirs] == ["detect", "config", "mirror", "gpg_key"]
    assert [step["kind"] for step in ours] == ["environment", "detect", "config", "gpg_key"]

    environment, detect, config, keys = ours
    loads = [line for line in lines if line.startswith(("module ", ". /usr/share/Modules"))]
    assert len(loads) == 7
    assert environment["shell"].split() == [
        "{{", "sandbox_modules_init", "}}", "set", "-eo", "pipefail", "{{", "sandbox_load_intel_modules", "}}"
    ]  # fmt: skip
    assert detect == {
        "kind": "detect",
        "compilers": True,
        "environment": environment["name"],
        "require": ["intel-oneapi-compilers@{{ oneapi_version }}"],
    }
    assert theirs[0] == {"kind": "detect", "compilers": True, "scope": "site"}
    # The step's settings are one variable, held to the script above.
    assert config == {"kind": "config", "settings": {"packages": "{{ intel_oneapi_spack_packages }}"}}
    assert theirs[1]["settings"]["packages"]["all"] == values["spack_packages"]["all"]
    assert theirs[1]["scope"] == "site"
    assert keys == theirs[3]
    assert script["ONEAPI_VER"] in values["intel_modules"][0]


def test_the_site_mirror_list_is_spack_pubkeys_commands_and_is_off_by_default(values: dict) -> None:
    (task,) = [task for task in setup_lists("spack") if "spack_site_mirror | bool" in task.get("when", [])]
    assert values["spack_site_mirror"] is False
    pubkey = [line.strip() for line in (UNIT / "legacy" / "spack-pubkey.sh").read_text().splitlines()]
    theirs = as_steps(spack_commands([line for line in pubkey if line != "spack gpg list"]))
    assert theirs == [
        {"kind": "gpg_key", "key": "$SPACK_KEY"},
        {"kind": "mirror", "name": "s3-mirror", "url": "$SPACK_MIRROR"},
        {"kind": "gpg_key", "from_mirrors": True},
    ]
    # The script downloads $SPACK_KEY_URL to $SPACK_KEY and trusts that file;
    # the step fetches the same URL, and trusts it only with the fingerprint.
    assert "wget $SPACK_KEY_URL -O $SPACK_KEY" in pubkey
    assert task["vars"]["spack_setup"] == [
        {"kind": "gpg_key", "key": "{{ spack_key_url }}", "fingerprint": "{{ spack_key_fingerprint }}"},
        {"kind": "mirror", "name": "s3-mirror", "url": "{{ spack_mirror }}"},
        {"kind": "gpg_key", "from_mirrors": True},
    ]
    # The script sets the two addresses itself; they are the ones in group_vars.
    for name in ("SPACK_MIRROR", "SPACK_KEY_URL"):
        (theirs_value,) = re.findall(rf"^{name}='([^']+)'$", "\n".join(pubkey), re.MULTILINE)
        assert values[name] == theirs_value
    assert re.fullmatch(r"[0-9A-F]{40}", values["spack_key_fingerprint"])


def test_no_task_of_the_two_roles_runs_spack_through_a_shell() -> None:
    for role in ("spack", "intel_oneapi"):
        text = (UNIT / "roles" / role / "tasks" / "main.yml").read_text()
        shells = [
            task
            for task in yaml.safe_load(text)
            if "ansible.builtin.shell" in task or "ansible.builtin.command" in task
        ]
        for task in shells:
            command = str(task.get("ansible.builtin.shell") or task.get("ansible.builtin.command"))
            assert "spack" not in command, task["name"]
    variables = (UNIT / "group_vars" / "all.yml").read_text()
    assert "spack_fingerprint" not in variables
    assert "spack_config_json" not in variables


@pytest.mark.parametrize(
    ("role_file", "first", "last"),
    [
        ("roles/mpi_ssh/files/sandbox-local-net.conf", 1355, 1437),
        ("roles/intel_oneapi/files/oneAPI.repo", 892, 898),
        ("roles/hpc_tuning/files/tuned.conf", 196, 208),
    ],
)
def test_a_file_written_out_of_the_script_has_the_scripts_text(role_file: str, first: int, last: int) -> None:
    theirs = "\n".join(lines_of(FUNCS)[first : last + 1]) + "\n"
    assert (UNIT / role_file).read_text() == theirs


@pytest.mark.parametrize(
    ("kernel", "edits"),
    [
        ("6.12.0-211.5.1.el10_2.x86_64", ["s#gpgcheck=1#gpgcheck=0#"]),
        ("6.12.0-124.8.1.el10_1.x86_64", ["s#gpgcheck=1#gpgcheck=0#", "s#10#10.1#"]),
        ("6.12.0-55.9.1.el10_0.x86_64", ["s#gpgcheck=1#gpgcheck=0#"]),
    ],
)
def test_the_lustre_repository_gets_the_edits_sed_would_make(
    kernel: str, edits: list[str], tmp_path: Path
) -> None:
    ours = rendered(tmp_path / "v.json", kernel=kernel)["fsx_repo_text"]
    theirs = (UNIT / "tests" / "fsx-lustre-client.repo.sample").read_text()
    for edit in edits:
        theirs = subprocess.run(
            ["sed", edit], input=theirs, capture_output=True, text=True, check=True
        ).stdout
    assert ours == theirs
    assert "gpgcheck=1" not in ours
    assert ("/el/10.1/" in ours) == (len(edits) == 2)


def test_stage_12_removes_only_the_two_paths_the_script_left_in_the_user_scope() -> None:
    """The removal names the script's two settings, the only ones the shell left there."""
    (task,) = [task for task in setup_lists("spack") if task["name"].startswith("Remove the leftovers")]
    (step,) = task["vars"]["spack_setup"]
    assert step == {
        "kind": "config",
        "scope": "user",
        "state": "absent",
        "settings": "{{ spack_user_scope.leftover }}",
    }
    found = (UNIT / "roles" / "spack" / "tasks" / "user_scope.yml").read_text()
    for keys in (["config", "install_tree", "padded_length"], ["modules", "default", "enable"]):
        section, middle, leaf = keys
        assert f"{{'{section}': {{'{middle}': {{'{leaf}': none}}}}}}" in found
    first = setup_lists("spack")[0]["vars"]["spack_setup"][0]["settings"]
    assert first == {
        "config": {"install_tree": {"padded_length": 73}},
        "modules": {"default": {"enable": ["tcl"]}},
    }


# Spec 002: push-build-cache.yml replaces csis-sandbox-ops' bin/spack-update-mirror.sh,
# which is not in legacy/ (it is that unit's). Its L31 names the key it signs with.
SCRIPT_KEY = "F525C05B06DCA266"
PUSH = "infrastructurebuilder.csis_spack.spack_buildcache_push"


def push_task() -> dict:
    plays = yaml.safe_load((UNIT / "push-build-cache.yml").read_text())
    found = [task[PUSH] for play in plays for task in play["tasks"] if PUSH in task]
    assert len(found) == 1
    return found[0]


def test_the_push_goes_where_the_script_pushed_signed_with_its_key(values: dict) -> None:
    args = push_task()
    # The script pushes to $SPACK_MIRROR, which the playbooks call spack_mirror.
    assert VARIABLES["SPACK_MIRROR"] == "spack_mirror"
    assert args["mirror"] == "{{ spack_mirror }}"
    # KEY=F525C05B06DCA266 is the short form of the fingerprint the nodes trust.
    assert "spack_key_fingerprint" in args["key"]
    assert values["spack_key_fingerprint"].endswith(SCRIPT_KEY)
    # The script pushes the packages of the environment the node built.
    assert args["env"] == "{{ spack_environment_dir }}"
    # It rebuilds the index (L34), and pushes again only what is missing.
    assert args["update_index"] is True
    assert args["force"] is False


def test_the_push_is_not_part_of_the_build() -> None:
    assert "push-build-cache" not in (UNIT / "site.yml").read_text()


def test_the_key_check_reads_only_the_signing_keys() -> None:
    # spack gpg list always lists the trusted (public) keys first; --signing
    # adds a "Signing keys" section. A head node trusts the site's public key,
    # so the fingerprint must be looked for after that heading only (found on
    # a head node, spec 002).
    plays = yaml.safe_load((UNIT / "push-build-cache.yml").read_text())
    (check,) = [task for play in plays for task in play["tasks"] if "ansible.builtin.assert" in task]
    that = check["ansible.builtin.assert"]["that"]
    assert "'Signing keys'" in str(that)
    assert "split('Signing keys')" in str(that)
