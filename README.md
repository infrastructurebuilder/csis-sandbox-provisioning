# sandbox-provisioning

Ansible playbooks that turn a bare RHEL 10 instance, with the sandbox's
EFS volume mounted, into a Cloud Sandbox head node, and then turn that
head node into the machine image its compute nodes boot from.

They do what `scripts/setup-instance.sh` does in the Cloud-Sandbox
repository, step for step. The difference is in how: the playbooks can
be applied again to a node that is already built, one step can be
applied on its own, and the first step that fails stops the run.

[DEPLOYMENT.md](DEPLOYMENT.md) says what happens on a new head node and
how to follow it.

| Playbook | What it does |
| --- | --- |
| [site.yml](site.yml) | Builds the software stack: twelve roles, one per function of the script, in the script's order |
| [node-image.yml](node-image.yml) | Snapshots the head node's root volume and registers the compute-node image |
| [push-build-cache.yml](push-build-cache.yml) | Pushes a built head node's Spack environment to the RHEL 10 build cache, signed; run by hand, never by `site.yml` ([docs/BUILD-CACHE.md](docs/BUILD-CACHE.md)) |

## This is a translation, kept beside its original

This directory was made inside the Cloud-Sandbox repository. The
scripts it replaces are in [legacy/](legacy/), unchanged, and every
task carries a comment that names the lines it replaces:

```yaml
# Replaces funcs-setup-instance.sh L229
- name: Create the prefect group
```

The tests hold the two together. They fail if a task names no lines,
if a line of the scripts that does something is neither replaced nor
listed with a reason in [tests/not_carried.yml](tests/not_carried.yml),
or if a version, a package list or a file's text differs from what the
script computes. [../MAP.md](../MAP.md) has the function-to-role
table, the places where the script's behaviour is an accident and what
was done about each, and what has not been proved.

## How it is applied

**At first boot, by the node to itself.**
[init_template.ansible.tpl](../sandbox-terraform/init_template.ansible.tpl),
in the Terraform unit, is the head node's first-boot script. After it has mounted the EFS volume it
runs:

```sh
ansible-pull --url <this repository> --checkout <version> \
    --directory /opt/sandbox-provisioning \
    --inventory inventories/local/hosts.yml site.yml
```

`ansible-pull` clones the playbooks and applies them to the machine it
runs on. `site.yml` needs nothing but the `ansible-core` package that
RHEL 10 ships.

**Later, on the head node.** Logged in to the head node:

```sh
cd /opt/sandbox-provisioning
sudo ansible-playbook site.yml --tags efa_driver
```

**Later, from your local machine.** The second inventory finds the
running head node by its tags:

```sh
ansible-playbook -i inventories/aws/aws_ec2.yml site.yml --tags efa_driver
```

Every role has a tag of its own name. The scripts that were copies of
`setup-instance.sh` with steps removed become one command each:

| Script | Now |
| --- | --- |
| `update-efa.sh` | `--tags efa_driver` |
| `setup-python-deps.sh` | `--tags python_user_env` |
| `rhel10-setup.sh` | `--skip-tags prefect_server,hpc_tuning`, then `node-image.yml` |

`rhel10-setup.sh` also differs in its last lines (it does not stop the
Prefect server for the image and runs `spack clean` without `--all`);
those differences are not carried.

## The roles

| Order | Role | Function in the script | In the container test |
| ---: | --- | --- | --- |
| 1 | `sandbox_paths` | `setup_paths` | yes |
| 2 | `user_shell` | `setup_aliases` | yes |
| 3 | `base_system` | `setup_environment` | yes |
| 4 | `prefect_server` | `setup_prefect-server` | yes |
| 5 | `mpi_ssh` | `setup_ssh_mpi` | yes |
| 6 | `efa_driver` | `install_efa_driver` | no: builds a kernel module |
| 7 | `fsx_lustre_client` | `install_fsx_driver` | no: installs a kernel module |
| 8 | `python_user_env` | `install_python_modules_user` | yes |
| 9 | `spack` | `install_spack` (and, when `spack_site_mirror` is true, `spack-pubkey.sh`) | yes; the site mirror's list is not applied |
| 10 | `intel_oneapi` | `install_intel_oneapi_dnf` | yes |
| 11 | `spack_environment` | `create_spack-environment`, `build_spack-environment` | concretized only: the build takes hours (it runs Spack through `infrastructurebuilder.csis_spack`) |
| 12 | `hpc_tuning` | `configure_optimizations` | no: changes kernel settings |

Two more roles, added in [stage 7](../../SPECS/COMPLETED/STAGE-7.md), replace
operator scripts that are run by hand rather than steps of
`setup-instance.sh`. Each has a playbook of its own:

| Playbook | Role | Replaces | In the container test |
| --- | --- | --- | --- |
| [users.yml](users.yml) | `sandbox_users` | `add-users.py`, `remove-user.sh`, the Lustre `sudoers` rules | yes, except opening SSH in the security group (AWS) |
| [jupyterhub.yml](jupyterhub.yml) | `jupyterhub` | `install_conda_jupyterhub.sh`, with the service, run script, nginx and `sudoers` files | yes, except nginx's TLS (no certificate) |

The user list holds people's names, addresses and keys, so it is a
variable the site keeps with its own settings
([roles/sandbox_users/defaults/main.yml](roles/sandbox_users/defaults/main.yml)
shows its shape); add-users.py read it from a file that was never in the
repository. The hub's Google OAuth client id and secret are variables too,
empty by default, as they are in the original configuration.
[docs/JUPYTERHUB.md](docs/JUPYTERHUB.md) is the original `jupyterhub/README.md`.

### JupyterHub, if a site wants it

JupyterHub is an option, not part of every build (stage 13, the
operator's decision): `site.yml` does not install it, and `jupyterhub.yml`
does, for a site that asks. Nothing installed it before stage 7, and its
settings in the original files are one site's, so the role has no
defaults for what only a site can say, and refuses to install anything
until it is given:

| Variable | What it is |
| --- | --- |
| `jupyterhub_server_name` | The name nginx answers to, the hub's public host name |
| `jupyterhub_ssl_certificate`, `jupyterhub_ssl_certificate_key` | Paths on the head node of the site's TLS certificate and key. The role does not put them there; nginx is enabled either way and started once both exist |
| `jupyterhub_oauth_callback_url` | The callback registered with the site's Google OAuth application, `https://<server name>/hub/oauth_callback` |
| `jupyterhub_oauth_client_id`, `jupyterhub_oauth_client_secret` | That application's id and secret; empty by default, and to be kept with the site's secrets, never in a repository |
| `jupyterhub_admin_users_literal` | The hub's administrators, as a Python set literal: `"{'jupyter', 'someone'}"` |
| `jupyterhub_username_map_literal` | Google addresses to local user names, as a Python dict literal |
| `jupyterhub_spawn_users` | Who the hub may start servers for; `[jupyter]` by default. The users themselves come from `users.yml` |

The head node's security group, which `sandbox-terraform` makes, opens
only SSH and the EFS volume's NFS. To reach the hub, the site opens 443 to
the addresses that should, itself; this repository does not.

```sh
ansible-playbook jupyterhub.yml --extra-vars @my-site-jupyterhub.yml
```

What the two roles correct, on purpose, is in the comments above each
task: among them, the hub's configuration and run script now go where the
service reads them, conda is given to its owner (the script's
`chown ec2-user/ec2-user` changes nothing), conda comes from Miniforge rather than the
script's Miniconda 23.1, whose solver did not finish the install in 25
minutes (the operator's choice), nginx is started only when the
certificates are there, and the Spack configuration each user gets is
theirs, not root's.

The versions are in [group_vars/all.yml](group_vars/all.yml), which is
`environment-vars.sh` as data. Settings that belong to one role are in
that role's `defaults/main.yml`.

## Working on it

You need `just`, `uv` and `shellcheck`; `full-test` also needs Docker.

```sh
just init        # tool environment, and the collections: infrastructurebuilder.csis_spack (from Ansible Galaxy, >=0.0.3,<0.1.0) and amazon.aws
just test        # syntax, ansible-lint, shellcheck, and the comparisons with the scripts
just full-test   # also applies eight roles, users.yml and jupyterhub.yml to an AlmaLinux 10 container, twice
```

`full-test` builds a container that stands in for a freshly booted
node, runs the same `ansible-pull` command as the first-boot script,
runs it again, and fails unless the second run changes nothing and the
result is what the roles should leave
([tests/container/](tests/container/)).

## What has been proved on AWS, and what has not

Cloud-Sandbox's spec 001 ran [docs/LIVE-PROOF.md](docs/LIVE-PROOF.md) on
2026-11-23: a head node on RHEL 10.2 in the `noaa` account, built by
`csis-sandbox-terraform`'s first boot with this repository's 0.0.3. There,
`site.yml` ended `failed=0`, a second apply changed two tasks (both
explained), and check mode found nothing to change; the four roles marked
"no" above installed what they install, Spack built ESMF and PETSc, and
`node-image.yml` made an image AWS reported `available`. The run's findings
are in spec 001's outcome (`specs/001-live-proof-on-aws/spec.md` in
Cloud-Sandbox).

Still not proved: that the EFA and Lustre drivers load on the kernel the
image boots (the first boot's update installs a newer kernel after they are
built for the running one), and that the playbooks leave the same node the
scripts did (the procedure's stage D, off by default). Each run of the
procedure costs money.

## One deliberate correction: the Prefect server

On 2026-11-12, the Prefect server that the script's command installs
does not start: pip picks FastAPI 0.162, and Prefect 3.7.8's server
fails at import with any FastAPI from 0.155 on, then restarts every
five seconds. The `prefect_server` role therefore installs Prefect
with `fastapi<0.155` (`prefect_server_extra_requirements` in
[roles/prefect_server/defaults/main.yml](roles/prefect_server/defaults/main.yml)).
It is the one place where the playbook does not do what the script
does; set the variable to `[]` to install exactly what the script
installs.

## Licence

BSD 3-Clause; see [LICENSE](LICENSE).
