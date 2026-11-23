"""The base_system role edits only files that exist on the host it runs on.

The script's line that silences subscription-manager's dnf plugin
(funcs-setup-instance.sh L34) names /etc/dnf/pluginconf.d/, a directory RHEL 10
does not have; the script's sed failed there unnoticed. The role names the
file RHEL 10 has, the one the script's next line names in a comment, and
edits it only if it is there. Found by spec 001's live proof, 2026-11-23.
"""

from __future__ import annotations

import yaml
from support import UNIT

ROLE = UNIT / "roles" / "base_system"
TASKS = yaml.safe_load((ROLE / "tasks" / "main.yml").read_text())
DEFAULTS = yaml.safe_load((ROLE / "defaults" / "main.yml").read_text())


def task(name: str) -> dict:
    found = [entry for entry in TASKS if entry.get("name") == name]
    assert len(found) == 1, name
    return found[0]


def test_the_plugin_file_is_the_one_rhel_10_has() -> None:
    wanted = "/etc/dnf/plugins/subscription-manager.conf"
    assert DEFAULTS["base_system_subscription_manager_plugin_conf"] == wanted


def test_the_plugin_is_silenced_only_where_the_file_exists() -> None:
    look = task("Look for subscription-manager's dnf plugin file")
    assert look["ansible.builtin.stat"]["path"] == "{{ base_system_subscription_manager_plugin_conf }}"
    register = look["register"]
    silence = task("Silence the subscription-manager dnf plugin")
    assert silence["ansible.builtin.replace"]["path"] == "{{ base_system_subscription_manager_plugin_conf }}"
    assert silence["when"] == [
        "base_system_subscription_manager | bool",
        f"{register}.stat.exists",
    ]
    assert TASKS.index(look) < TASKS.index(silence)


def test_no_task_names_the_directory_rhel_10_lacks() -> None:
    # The comments name it, to say why; no task or default does.
    assert "pluginconf.d" not in yaml.safe_dump(TASKS) + yaml.safe_dump(DEFAULTS)
