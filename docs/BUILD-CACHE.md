# Pushing a head node's build to the RHEL 10 build cache

A head node builds its Spack environment (ESMF, PETSc and what they need)
from source. Once one node has built it, `push-build-cache.yml` puts the
packages in the sandbox's build cache, so that the next node installs them
from there instead of compiling them. This page says when to push, how the
signing key reaches the node, and how to run the push. It was written for
Cloud-Sandbox's spec 002.

## When to push

- **After a build that changed what the environment holds**: a new ESMF or
  PETSc version, a new compiler, a new Spack. A node built from the cache
  with nothing new has nothing to push.
- **On a head node that finished its first boot cleanly** (`site.yml` ended
  `failed=0`). Spack refuses to push an environment any of whose packages,
  build-only ones included, is not installed: it pushes what is installed and
  then fails ("package not installed"), so a half-built environment leaves a
  half-filled cache and a failed play.
- **Not from `site.yml`, ever.** The push is a separate, deliberate step:
  what goes in the cache is what every later node installs.

## Where the cache is

The cache is a private S3 bucket of the sandbox's own, made once by
`csis-sandbox-terraform`'s `build-cache/` (its `DEPLOYMENT.md`, step 9). Its
`mirror_url` output is the value of `spack_mirror`. The head node writes to it
through its own role, when the deployment set `build_cache_bucket`; no AWS
credential is put on the node.

The older bucket, `ioos-cloud-sandbox`, holds a RHEL 8 cache and is never
written to.

## The signing key

Packages are signed with the site's key, whose fingerprint is
`spack_key_fingerprint` in `group_vars/all.yml`. Every head node already
trusts that key's public half (the `spack` role fetches it). Only a node that
pushes needs the private half, and it needs it only while it pushes:

1. **Copy the private half to the node by hand**, over the Session Manager
   session, into the login user's home. It is never put in a repository, a
   variable, a setting or a log.
2. **Import it, as the login user**: `spack gpg trust <file>`, then remove the
   file. `spack gpg list --signing` must show the fingerprint.
3. **Push** (below).
4. **Remove the key from the node when the push is done**:
   `spack gpg untrust <fingerprint>`. A node made into an image while the key
   is on it would give the key to every compute node.

Without the key in Spack's keyring, the play stops before pushing anything,
and names the key it wanted.

## The push

On the head node, from the playbooks' checkout, as root:

```sh
cd /opt/sandbox-provisioning && export ANSIBLE_CONFIG=/opt/sandbox-provisioning/ansible.cfg
ansible-playbook -i inventories/local/hosts.yml push-build-cache.yml --check
ansible-playbook -i inventories/local/hosts.yml push-build-cache.yml
```

- **Check mode first.** It asks the cache which of the environment's
  packages it lacks, and pushes nothing. `changed` means some are missing.
- **Then for real.** It pushes only what the cache lacks, signed, and rebuilds
  the cache's index. `changed` means something was pushed.
- **Running it again** pushes nothing and reports no change. A push that was
  interrupted is finished by running it again: only what is still missing is
  pushed.

## What it replaces

`csis-sandbox-ops`' `bin/spack-update-mirror.sh` pushed a list of packages
one by one to the RHEL 8 cache. It stays in that unit, marked as replaced by
this play.
