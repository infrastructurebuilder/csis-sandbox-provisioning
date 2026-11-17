# Proving the playbooks on a real head node

*Written 2026-11-12. **Not run.** Every box below is a careful reading
of the scripts and of the tools involved, but none has been executed.
Treat the first run as a test of this page as well as of the
playbooks, and stop at any result the page does not predict.*

The container test proves seven roles on AlmaLinux 10. It cannot prove
the two kernel drivers, the Intel compilers, the Spack build, the
tuning profile or the node image, and it does not run on RHEL or on
AWS. This procedure does: it builds a head node with the playbooks in
place of `setup-instance.sh`, applies them a second time, and makes a
node image.

## What it costs

- One head node of the instance type in your settings file, for the
  length of the Spack build. The build compiles everything; allow
  several hours.
- One EFS volume, one snapshot and one machine image, until you remove
  them in stage E.
- Stage D doubles the first item.

Nothing here touches an existing sandbox, provided the gate in step A3
holds.

## Where each box runs

Two places, named in every step: **your local machine**, in a terminal
at the root of the Cloud-Sandbox repository, and **the head node**, in
an `ssh` session as `ec2-user`. Every box sets the variables it uses,
so a box can be pasted on its own.

`$HOME/sandbox-live-proof` is this page's choice of working directory
on your local machine. Any empty place outside the repository will do;
change it in every box if you change it in one.

## Stage A: a head node with nothing installed

### A1. Your AWS session (local machine)

```sh
# A1 -- box 1 of 1 -- v1
aws sts get-caller-identity
```

It must print your account and role. If it prints an error, STOP:
refresh the session before going on. Everything after this needs it,
and stage B runs for hours.

### A2. A working copy of the Terraform (local machine)

The copy is edited; the repository's `terraform/` is not.

```sh
# A2 -- box 1 of 2 -- v1
PROOF="$HOME/sandbox-live-proof"
cp -R terraform "$PROOF"
sed -i.orig '/setup-instance.sh/d' "$PROOF/init_template.tpl"
grep -c 'setup-instance.sh' "$PROOF/init_template.tpl"
```

It must print `0`: the first-boot script no longer runs the old
set-up. If it prints anything else, STOP.

```sh
# A2 -- box 2 of 2 -- v1
PROOF="$HOME/sandbox-live-proof"
rm -rf "$PROOF/.terraform" "$PROOF"/terraform.tfstate*
ls -a "$PROOF" | grep -c -x '.terraform'
```

It must print `0`. A `.terraform` directory copied from the repository
would point this copy at the state of a sandbox you already run.

### A3. A workspace of its own (local machine)

```sh
# A3 -- box 1 of 3 -- v1
PROOF="$HOME/sandbox-live-proof"
cd "$PROOF"
terraform init -backend-config=config.s3.tfbackend
terraform workspace new live-proof
terraform workspace show
```

It must print `live-proof`. If it prints anything else, STOP: a plan
made now would be a plan against another sandbox.

**YOUR DECISION:** the settings. Copy the settings file you deploy
with to `$HOME/sandbox-live-proof/proof.tfvars` and give `nameprefix`
and `name_tag` values that no other sandbox uses, for example
`live_proof` and `Live-Proof`. If you change nothing, the IAM role and
the placement group collide with your existing sandbox's and the apply
fails.

```sh
# A3 -- box 2 of 3 -- v1
PROOF="$HOME/sandbox-live-proof"
grep -E '^(nameprefix|name_tag)' "$PROOF/proof.tfvars"
```

It must show the two values you chose.

```sh
# A3 -- box 3 of 3 -- v1
PROOF="$HOME/sandbox-live-proof"
cd "$PROOF"
terraform plan -var-file=proof.tfvars -out=proof.plan
```

The last lines must read `Plan: N to add, 0 to change, 0 to destroy.`
If either of the last two numbers is not 0, STOP. Do not apply.

### A4. Create it (local machine)

A few minutes; the exact time is not known.

```sh
# A4 -- box 1 of 1 -- v1
PROOF="$HOME/sandbox-live-proof"
cd "$PROOF"
terraform apply proof.plan
```

It must end with `Apply complete!` and print a `login_command`. Keep
that line: the address in it is the head node.

### A5. Confirm that the node is bare (head node)

Log in with the `login_command`. Then:

```sh
# A5 -- box 1 of 1 -- v1
cloud-init status --wait
sudo tail -2 /root/setup.log
ls /save /mnt/efs/fs1
ls /save/environments
```

`cloud-init` must report `status: done`. The log ends with
`Installation completed!` and a date (the message is the old
script's; nothing was installed). `/save` and `/mnt/efs/fs1` list a
directory for `ec2-user`. The last line must say
`No such file or directory`: if `/save/environments` exists, the old
set-up ran, and this node proves nothing. STOP.

## Stage B: apply the playbooks

### B1. Copy the playbooks to the node (local machine)

**YOUR DECISION:** `NODE` and `KEY` are the address and the key file
from your `login_command`. There is no default.

```sh
# B1 -- box 1 of 1 -- v1
NODE=ec2-user@PUT-THE-ADDRESS-HERE
KEY=PUT-THE-PATH-TO-YOUR-KEY-HERE
tar -C exportit/sandbox-provisioning --format ustar \
    --exclude .venv --exclude .collections --exclude .pytest_cache --exclude .ruff_cache \
    -cf - . | ssh -i "$KEY" "$NODE" 'mkdir -p sandbox-provisioning && tar -C sandbox-provisioning -xf -'
ssh -i "$KEY" "$NODE" 'ls sandbox-provisioning/site.yml sandbox-provisioning/roles | head -3'
```

It must list `sandbox-provisioning/site.yml` and role names.

### B2. Start the build (head node)

```sh
# B2 -- box 1 of 2 -- v1
sudo dnf -y install ansible-core
sudo cp -R ~/sandbox-provisioning /opt/sandbox-provisioning
cd /opt/sandbox-provisioning
ansible-playbook --syntax-check site.yml
```

It must print `playbook: site.yml` and no error.

Several hours: the Spack step compiles ESMF, PETSc and everything they
need. The box returns at once; the build goes on if you log out.

```sh
# B2 -- box 2 of 2 -- v1
cd /opt/sandbox-provisioning
sudo nohup ansible-playbook site.yml > ~/site-first.log 2>&1 &
sleep 20
tail -5 ~/site-first.log
```

It must show task names going by. If it shows an error, STOP.

To watch: `tail -f ~/site-first.log`. Ctrl-C stops the watching, not
the build. During the long step, the build's own output is in
`/save/environments/rhel10-x86_64_v3/log.install`.

### B3. Read the result (head node)

When the log has stopped growing:

```sh
# B3 -- box 1 of 2 -- v1
grep -E '^localhost +: ' ~/site-first.log
```

It must print one line with `unreachable=0 failed=0`. If there is no
such line the build is still running. If `failed` is not 0, STOP: the
task that failed is the last `fatal:` line in the log, and the node is
worth keeping as it is for a look.

Also look for the kernel warning, which is not an error:

```sh
# B3 -- box 2 of 2 -- v1
grep -A3 'WARNING: the running kernel' ~/site-first.log
```

If it prints, the EFA and Lustre drivers were built for a kernel that
is not the one running, exactly as the script would have built them.

### B4. Apply it again (head node)

Time unknown; minutes are expected, since nothing should need
building.

```sh
# B4 -- box 1 of 1 -- v1
cd /opt/sandbox-provisioning
sudo ansible-playbook site.yml > ~/site-second.log 2>&1
grep -E '^localhost +: ' ~/site-second.log
```

It must show `failed=0`. The aim is `changed=0`. Any task that changed
something on the second run is a finding and not a failure; list them
with `grep -B3 '^changed:' ~/site-second.log` and keep the output.

## Stage C: the node image

### C1. Make it (head node)

```sh
# C1 -- box 1 of 2 -- v1
cd /opt/sandbox-provisioning
sudo ansible-galaxy collection install -r requirements.yml
sudo ansible-galaxy collection list amazon.aws
```

It must list `amazon.aws` with a version that begins with 9.

Tens of minutes: the play waits for the snapshot, for up to fifty
minutes.

```sh
# C1 -- box 2 of 2 -- v1
cd /opt/sandbox-provisioning
sudo ansible-playbook node-image.yml -e ami_name=live-proof-$(date -u +%Y%m%d-%H%M) > ~/node-image.log 2>&1
grep -E 'AMI Image ID is|^localhost +: ' ~/node-image.log
```

It must print an image id that begins with `ami-`, and `failed=0`.

### C2. See it from outside (local machine)

```sh
# C2 -- box 1 of 1 -- v1
aws ec2 describe-images --owners self --filters 'Name=name,Values=live-proof-*' \
    --query 'Images[].[ImageId,Name,State]' --output text
```

It must print one line that ends in `available`. Add `--region` if
your default region is not the node's.

Not covered: starting a compute node from this image and running a
model on it. That is the image's real test, and it needs a cluster
description and cloudflow.

## Stage D, optional: compare with a node the script builds

**YOUR DECISION:** skip this (the default), or build a second head
node the old way and compare the two. It is the only direct evidence
that the playbooks leave what the script leaves, and it costs a second
build of several hours.

To do it, repeat stage A in a third workspace with a third
`nameprefix`, leaving out the `sed` line of A2 so that the old set-up
runs. Then, on each node:

```sh
# D -- box 1 of 2 -- v1
rpm -qa | sort > ~/facts-rpm.txt
python3 -m pip list --format=freeze | sort > ~/facts-pip.txt
/save/environments/spack.v1.2.0/bin/spack -e /save/environments/rhel10-x86_64_v3 find > ~/facts-spack.txt
find /save/environments/modulefiles -type f | sort > ~/facts-modules.txt
tuned-adm active > ~/facts-tuned.txt
wc -l ~/facts-*.txt
```

Fetch the five files from both nodes into two directories on your
local machine and compare:

```sh
# D -- box 2 of 2 -- v1
diff -r facts-ansible facts-script
```

Expected differences: none in the Spack and module lists; the
`ansible-core` package and what it requires in the package list.
Anything else is a finding.

## Stage E: remove everything

**YOUR DECISION:** remove now (the default), or keep the node for a
look. While it stands, the node, the EFS volume, the snapshot and the
image are all billed.

```sh
# E -- box 1 of 5 -- v1
PROOF="$HOME/sandbox-live-proof"
cd "$PROOF"
terraform workspace show
```

It must print `live-proof`. If it prints anything else, STOP: the next
box would destroy another sandbox.

```sh
# E -- box 2 of 5 -- v1
PROOF="$HOME/sandbox-live-proof"
cd "$PROOF"
terraform destroy -var-file=proof.tfvars
```

Terraform lists what it will destroy and asks. Read the list before
you answer. It must end with `Destroy complete!`.

The image and its snapshot were not made by Terraform and are still
there.

```sh
# E -- box 3 of 5 -- v1
aws ec2 describe-images --owners self --filters 'Name=name,Values=live-proof-*' \
    --query 'Images[].[ImageId,BlockDeviceMappings[0].Ebs.SnapshotId]' --output text
```

It prints the image id and the snapshot id. Put them in the next two
boxes.

```sh
# E -- box 4 of 5 -- v1
aws ec2 deregister-image --image-id PUT-THE-IMAGE-ID-HERE
```

```sh
# E -- box 5 of 5 -- v1
aws ec2 delete-snapshot --snapshot-id PUT-THE-SNAPSHOT-ID-HERE
aws ec2 describe-snapshots --owner-ids self --filters 'Name=tag:Name,Values=live-proof-*' \
    --query 'Snapshots[].SnapshotId' --output text
```

The last command must print nothing.

## What to bring back

`~/site-first.log`, `~/site-second.log` and `~/node-image.log` from the
head node, and the output of stage D if you ran it. With those, the
rows marked "not proved" in [../../MAP.md](../../MAP.md) can be
settled one way or the other.
