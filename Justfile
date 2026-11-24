# sandbox-provisioning: Ansible playbooks that build the Cloud Sandbox stack.

set shell := ["bash", "-euo", "pipefail", "-c"]

# List the targets.
default:
    @just --justfile {{ justfile() }} --list

# Create the tool environment and fetch the collection that node-image.yml needs.
init:
    uv sync
    uv run ansible-galaxy collection install -r requirements.yml -p .collections

# Nothing to compile: playbooks are applied as they are.
build:
    @echo "sandbox-provisioning: nothing to build"

# Syntax, ansible-lint at its strictest profile, shellcheck, and ruff on the tests.
lint:
    uv run ansible-playbook --syntax-check site.yml node-image.yml users.yml jupyterhub.yml push-build-cache.yml tests/render.yml tests/render-templates.yml tests/user-scope.yml tests/jupyterhub-check.yml tests/container/verify.yml
    uv run ansible-lint
    shellcheck tests/container/converge.sh
    uv run ruff check tests
    uv run ruff format --check tests

# Type-check the tests; any error fails.
typecheck:
    uv run pyright

# Lint, type-check, and the tests that compare the playbooks with the scripts.
test: lint typecheck
    uv run pytest -q

# Everything in test, then apply the roles a container can take, twice (needs Docker; about ten minutes).
full-test: test
    tests/container/converge.sh

# Nothing is published from a copy inside Cloud-Sandbox.
release: full-test
    @echo "sandbox-provisioning: nothing to release from exportit/; see exportit/MAP.md"
