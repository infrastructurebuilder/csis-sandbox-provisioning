# Building spack-stack for UFS Coastal

`ufs-stack.yml` builds [spack-stack](https://github.com/JCSDA/spack-stack),
the software stack the UFS models are built against, on a head node that
`site.yml` has built. It sits beside the sandbox's own Spack and never
changes it. It was written for Cloud-Sandbox's spec 004, which proved it on a
head node of its own on 2026-11-27 and 28; this page says what that proof
found a site needs to know.

## When to run it

Run it by hand, once, on a head node that will build UFS Coastal (the
`csis-model-ufscoastal` unit). Nothing else in the sandbox needs it, and
`site.yml` never runs it. Run it from the head node itself, as root, in the
checkout the first boot made:

```sh
cd /opt/sandbox-provisioning
export ANSIBLE_CONFIG=/opt/sandbox-provisioning/ansible.cfg
sudo -E ansible-playbook -i inventories/local/hosts.yml ufs-stack.yml
```

The checkout must be at **0.0.10 or later**. Releases 0.0.6 to 0.0.9 hold
the playbook but do not build the stack on a real head node: each of 0.0.7 to
0.0.10 fixed something the proof found there (the Intel module files Spack
could not read, the system packages the build needs, the module files and
the meta-modules settling, the MPI module's `I_MPI_ROOT`). Move an older
checkout first: `git fetch --tags origin && git checkout 0.0.10`, then install
the collections again (`ansible-galaxy collection install -r requirements.yml`).

The first apply compiles everything, so run it where it can run for hours
without a terminal: in `tmux`, or with `nohup … &` and its output in a file.
The playbook keeps going if your session ends.

## How long it takes

On the `c6i.8xlarge` the proofs use (32 processors):

| Step | Time |
| --- | --- |
| The clone of spack-stack with its submodules | about 10 minutes on the node; 38 minutes in the container test, over a slower link |
| The build of the environment, about 112 packages, with oneAPI | about two hours |
| A second apply, with nothing to do | two to three minutes |

There is no build cache for spack-stack yet, so every node compiles it. A
change to the system's packages can make Spack find more of them as
externals, which changes the concretization and rebuilds much of the
environment (74 packages, once, on the proof's node).

## What it builds

- **spack-stack**: the fork `asascience-open/spack-stack` at commit
  `406b090aa4828fb7be840eea33c83963d88ac84e`, with its submodules, in
  `/save/environments/spack-stack-<that commit>/`. A commit, or a tag, never a
  branch: the playbook checks the variable `ufs_stack_version` before it
  clones and stops on a branch. JCSDA's own releases had no RHEL 10 site and
  none of UFS Coastal's pins; the operator chose the fork on 2026-11-26.
- **Its environment**, `envs/aws-ioossb-rhel10/`, made by `spack stack create
  env` from the fork's `aws-rhel10` site and `ioos-ufscoastal` template, with
  the sandbox's oneAPI (`--compiler oneapi`) and RHEL 10's own GCC 14 (no GCC
  toolset). The template's `ufs-weather-model-env` and the model's other
  dependencies, with `sp@2.5.0` added as the old script added it.
- **Its module files**, Tcl, which the sandbox's Environment Modules reads,
  under `envs/aws-ioossb-rhel10/modules/`, and spack-stack's **meta-modules**
  in `modules/Core`: `stack-intel-oneapi-compilers/2024.2.1`, which offers
  `stack-intel-oneapi-mpi/2021.13`, which offers the rest (`esmf/8.8.0`,
  `fms/2025.03-gfs-constants`, `mapl/2.53.4-esmf-8.8.0`, `netcdf-c/4.9.2` and
  others).
- **System packages** spack-stack's build needs, installed with dnf before the
  clone: the old script's six (`binutils-devel`, `git-lfs`, `bash-completion`,
  `xorg-x11-xauth`, `perl-IPC-Cmd`, `gettext-devel`), Perl whole (RHEL 10's
  `perl-interpreter` lacks `FindBin`, which OpenSSL's build needs) and zlib's
  static library (the system zlib's CMake files name it, and HDF5's CMake
  stops without it).

To use the stack, as UFS Coastal's module file does:

```sh
module use /save/environments/spack-stack-406b090aa4828fb7be840eea33c83963d88ac84e/envs/aws-ioossb-rhel10/modules/Core
module load stack-intel-oneapi-compilers/2024.2.1 stack-intel-oneapi-mpi/2021.13
module avail
```

## Where it writes Spack's configuration

The sandbox's own Spack reads `/etc/spack` (its system scope), so the
playbook never writes there; on a head node that directory does not even
exist, and after the playbook it still does not. spack-stack's `setup.sh`
turns off Spack's user and system scopes for the stack, so the stack does not
read it either. The playbook writes to three scopes, all inside the stack's
directory:

| Scope | What goes there |
| --- | --- |
| The environment's own (`env:<the environment's directory>`, its `spack.yaml`) | the externals and compilers Spack finds on the node; the MPI requirement (`intel-oneapi-mpi@2021.13`); the target (`x86_64_v3`, generic); `I_MPI_ROOT` and `FI_PROVIDER_PATH` for the MPI module |
| The environment's `site/` (named by its real path, since `/save` is a link) | the sandbox's oneAPI as externals with no module to load, in place of the fork's site's entries, which name an MPI the sandbox lacks and load Intel's module files, whose `®` Spack cannot read |
| spack-stack's own Spack's `site` (`spack/etc/spack/site/`) | the install tree's padding, as the old script set it |

## Check mode

```sh
sudo -E ansible-playbook -i inventories/local/hosts.yml ufs-stack.yml --check
```

Before the first apply there is nothing cloned to preview against: the
preview says what the first apply would do and stops. On a built node it
reports changes it would not make (`changed=2` after two applies that changed
nothing): the collection's `spack_env` previews from a copy of the
environment, and spack-stack's install tree is `$env/install`, which in the
copy holds nothing, so the whole environment looks uninstalled. The real
apply is right; only the preview is wrong. The collection's spec 014
(`ansible-collection-csis-spack`, FR-007) is to fix it.

## What it replaces

`csis-sandbox-ops`' `bin/add-ufs-setup.sh` and `bin/ufs-envars.sh`, which
called three functions of `legacy/funcs-setup-instance.sh` that
`setup-instance.sh` never called: `install_spack-stack_prereqs`,
`setup_spack-stack` and `build_spack-stack-environment`. Both scripts stay in
that unit, marked as replaced. Every line of the three functions is either
replaced by a step or task of the playbook, which names it in a `# Replaces`
comment, or listed with its reason in `tests/not_carried.yml` (the build
cache's key and mirror, the GCC toolset, the system scope's redirection, the
switch to Lmod). The versions are the sandbox's own, not `ufs-envars.sh`'s
(the playbook's header says why).
