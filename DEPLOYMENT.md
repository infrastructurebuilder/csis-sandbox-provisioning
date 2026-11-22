# Installing the software on a head node

This is the software part of `DEPLOYMENT.md` in the Cloud-Sandbox
repository (its lines 184–238 and 262–279), written for this project. The
AWS resources come first; they are in `sandbox-terraform`'s
`DEPLOYMENT.md`. The original describes `scripts/setup-instance.sh`; this
describes the playbooks that replace it, and notes where they differ.

## What happens at first boot

When Terraform creates a head node, the node runs its first-boot script
once. That script is `csis-sandbox-terraform`'s `init_template.ansible.tpl`,
which its `main.tf` renders since its spec 006 (2026-11-22); the original
used `init_template.tpl`, which runs `setup-instance.sh`. The script:

1. mounts the EFS volume at `/mnt/efs/fs1` and links `/save` to it;
2. clones cloudflow from its own repository, at the tag Terraform names,
   into `/save/ec2-user/cloudflow`, and links the old checkout's path,
   `/save/ec2-user/Cloud-Sandbox/cloudflow`, to it;
3. installs Ansible and runs `ansible-pull`, which fetches this project at
   the tag Terraform names and applies [site.yml](site.yml) to the node
   itself;
4. installs cloudflow for `ec2-user`, editable and without dependencies:
   `site.yml`'s `python_user_env` role has installed them;
5. if all that succeeded, applies [node-image.yml](node-image.yml), which
   turns the node's root volume into the machine image the compute nodes
   boot from.

Both repositories are public and are cloned with no credential. Any step
that fails stops the script, with a line saying which in `~/setup.log`,
before an image is made.

`site.yml` installs, among other things:

- the GNU and Intel oneAPI compilers for Fortran, C and C++;
- Intel MPI;
- NetCDF, HDF5 and the other libraries the models need, through Spack;
- the Prefect server that cloudflow reports to.

[README.md](README.md) lists the roles in order, and what each replaces.

With the Spack binary mirror the installation takes about an hour.
Without it, everything is compiled, and it takes several hours, depending
on the head node's instance type.

## Following the installation

The installation goes on after Terraform has finished. Wait a minute or
two for the node to boot, log in with the command Terraform printed, and
watch the log:

```sh
ssh -i my-sandbox.pem ec2-user@<the head node's address>
sudo -i
tail -f /root/setup.log
```

The first-boot script runs as root and writes `~/setup.log` in root's
home, as the original's did. What the operating system and the first-boot
script print is also in:

```text
/var/log/cloud-init-output.log
```

A failure in `site.yml` stops the script before it makes an image, and
`setup.log` says so.

## The image for the compute nodes

`node-image.yml` makes the image at the end of the installation, as the
original's `create_image.sh` did. Its id is at the end of `setup.log`, in
the AWS console, or from the AWS CLI. A cluster description needs it as
`image_id`.

To make a new image later, after changing the head node:

```sh
ansible-playbook node-image.yml -e ami_name=<a name not used before>
```

Like the original's `create_image.sh`, it also writes the id to a file in
the login user's home, for example:

```sh
cat ~/image-id-20260619_16-48
```

## One step, on a node already built

Each role has a tag of its own, so one step can be applied again:

```sh
ansible-playbook site.yml --tags efa_driver
```

## After the installation

Two playbooks are applied by hand when a site wants them:

- [users.yml](users.yml) adds and removes the people who use the
  sandbox, with their groups, SSH keys and directories in `/save`, `/com`
  and `/ptmp`. The list of users is the site's, kept with its own
  settings.
- [jupyterhub.yml](jupyterhub.yml) installs JupyterHub behind nginx.
  [docs/JUPYTERHUB.md](docs/JUPYTERHUB.md) is about configuring it.

Run `node-image.yml` again afterwards if the compute nodes should have
these changes too.

## What has not been proved

None of this has been applied to a real head node yet.
[docs/LIVE-PROOF.md](docs/LIVE-PROOF.md) is the procedure for doing so.
