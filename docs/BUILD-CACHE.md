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
  build-only ones included, is not installed ("package not installed"), so a
  half-built environment pushes nothing.
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

Packages are signed with the key made for this cache on 2026-11-24,
fingerprint `8D58116F59406FF3B70812BA065FBB8F66F38D66` (`spack_key_fingerprint` in `group_vars/all.yml`). The
old site key, whose fingerprint ends `F525C05B06DCA266`, signed the RHEL 8
cache; its private half could not be obtained, so it signs nothing here.

- **The public half** is in this repository,
  `roles/spack/files/build-cache-signing-key.pub.asc`. The `spack` role puts
  it in Spack's keyring on every head node that uses the site mirror,
  trusted only if it has that fingerprint. Nothing is downloaded.
- **The private half** is kept in the team's Keybase folder,
  `/Volumes/Keybase/team/csimagesystem`, beside a `README.md` that says what
  it is and how to manage it. It is never put in a repository, a variable, a
  setting, a log or an AWS secret. It has no passphrase, because the push
  runs unattended; its protection is where it is kept.

Only a node that pushes needs the private half, and only while it pushes:

1. **Copy it to the node as a file**, from your local machine, through a
   Session Manager tunnel, into the login user's home. Do not paste it into a
   session: Session Manager may log what is typed.

   ```sh
   export AWS_PROFILE=noaa AWS_REGION=us-east-2
   scp -i <the node's key pair> \
     -o "ProxyCommand=aws ssm start-session --target %h --document-name AWS-StartSSHSession --parameters portNumber=%p" \
     /Volumes/Keybase/team/csimagesystem/csis-sandbox-rhel10-build-cache.signing-key.8D58116F59406FF3B70812BA065FBB8F66F38D66.private.asc \
     ec2-user@<instance id>:signing.key
   ```

2. **Import it, as the login user**: `spack gpg trust ~/signing.key`, then
   `rm ~/signing.key`. Spack asks "Trust key? [y/N]"; where there is no
   terminal to answer (a command run over `ssh` without one), give
   `--yes-to-all`, or the import fails and the file is left behind. `spack gpg list --signing` must show the fingerprint
   under "Signing keys" (the trusted keys are listed above that heading; a
   key there alone cannot sign).
3. **Push** (below).
4. **Remove it from the node when the push is done**:
   `spack gpg untrust --signing 8D58116F59406FF3B70812BA065FBB8F66F38D66`. A node made into an image while the
   key is on it would give the key to every compute node.

Without the key in Spack's keyring, the play stops before pushing anything,
and names the key it wanted.

## The push

On the head node, from the playbooks' checkout, as root:

```sh
cd /opt/sandbox-provisioning && export ANSIBLE_CONFIG=/opt/sandbox-provisioning/ansible.cfg
ansible-playbook -i inventories/local/hosts.yml push-build-cache.yml --check
ansible-playbook -i inventories/local/hosts.yml push-build-cache.yml
```

- **The cache is `spack_mirror`**, whose default is the RHEL 10 cache since
  0.0.4. The play refuses `ioos-cloud-sandbox`, which is never written to;
  give `-e spack_mirror=...` only to push somewhere else.
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
