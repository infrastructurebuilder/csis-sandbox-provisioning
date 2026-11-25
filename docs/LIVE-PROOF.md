# Proving the playbooks on a real head node

*Version 3, 2026-11-23. Version 2 was written for Cloud-Sandbox's spec 001 and
run once that day; version 3 carries what the run found into the boxes it
changed (those marked `v3`). The run's findings are in spec 001's outcome.
Stop at any result the page does not predict.*

The container test proves the playbooks on AlmaLinux 10. It cannot prove the
two kernel drivers, the Intel compilers, the Spack build, the tuning profile,
the node image or the first-boot script, and it does not run on RHEL or on
AWS. This procedure does: it builds a head node with `csis-sandbox-terraform`
in the `noaa` account's existing IOOS VPC, lets the node's first boot (spec
006) apply the playbooks, applies them again and in check mode by hand,
makes the node image, and removes everything it made.

## What it costs, and what it may touch

- One head node of 32 processors (`c6i.8xlarge`, about $1.36 an hour) from
  box A5 to box E2. On the first run the first boot took 34 minutes and stage
  B about ten more; the node is idle, and paid for, while it waits for an
  answer. One EFS volume, one machine image and its snapshot, until stage E
  removes them.
- **Nothing that exists is changed.** Every resource the proof makes is new and
  carries the prefix `CSIS-Live-Proof` (`csis_live_proof` where a name allows
  no capitals). The plan in box A4 must show only additions; the VPC and its
  subnets are described before and after, and must be the same (box E5).
- **Every box that creates, changes or removes something on AWS** says so with
  **Changes AWS:** above it, and is run only on the operator's word.

## Where each box runs

Two places, named in every step's heading: **your local machine**, in a
terminal anywhere, with the AWS CLI, the Session Manager plugin and `jq`; and
**the head node**, in a Session Manager session (box A5). Every box sets the
variables it uses, so a box can be pasted on its own.

**OpenTofu and the `noaa` session.** The AWS CLI reads the `noaa` profile's
single sign-on session, but OpenTofu's AWS provider cannot ("profile "noaa"
is configured to use SSO but is missing required configuration: sso_region,
sso_start_url"). So every box that runs OpenTofu against AWS first puts the
session's temporary credentials into that box's environment, with
`aws configure export-credentials`, and unsets `AWS_PROFILE`. Nothing is
printed, and nothing is written to a file; the credentials last as long as
the session.

`$HOME/csis-live-proof` is this page's working directory on your local
machine. The settings file there names the account's network: it is never
committed anywhere.

## Stage A: the head node

### A1. Your AWS session and the plugin (your local machine)

```sh
# A1 -- box 1 of 1 -- v2
export AWS_PROFILE=noaa AWS_REGION=us-east-2
aws sts get-caller-identity --query Arn --output text >/dev/null && echo "session: valid"
session-manager-plugin --version
```

It must print `session: valid` and a version. If the session is not valid,
**stop** and refresh it; the proof does not start without one.

### A2. A working copy, and the proof's key pair (your local machine)

The working copy is `csis-sandbox-terraform` as merged, with `proof/`'s files
beside its `main.tf`. Set `CSIS` to your Cloud-Sandbox checkout.

```sh
# A2 -- box 1 of 2 -- v2
CSIS=$HOME/Cloud-Sandbox
PROOF=$HOME/csis-live-proof
mkdir "$PROOF" && cd "$PROOF"
git -C "$CSIS/exportit/sandbox-terraform" archive develop | tar -x
cp proof/backend_override.tf proof/proof_override.tf proof/proof.tf proof/ssm-agent.sh .
cp proof/proof.tfvars.example proof.tfvars
ls proof_override.tf proof.tf backend_override.tf proof.tfvars
```

It must list the four files. A key pair of the proof's own, kept on your local
machine (the module requires an RSA key):

```sh
# A2 -- box 2 of 2 -- v2
ssh-keygen -t rsa -b 4096 -N '' -C csis-live-proof -f "$HOME/.ssh/csis-live-proof"
cat "$HOME/.ssh/csis-live-proof.pub"
```

Put the printed line in `proof.tfvars` as `public_key`.

### A3. The network, and the settings (your local machine)

```sh
# A3 -- box 1 of 3 -- v2
export AWS_PROFILE=noaa AWS_REGION=us-east-2
VPC=$(aws ec2 describe-vpcs --filters 'Name=tag:Name,Values=IOOS Cloud Sandbox VPC' --query 'Vpcs[0].VpcId' --output text)
echo "VPC: $VPC"
aws ec2 describe-route-tables --filters "Name=vpc-id,Values=$VPC" \
  --query 'RouteTables[].{subnets:Associations[].SubnetId,nat:Routes[?NatGatewayId].NatGatewayId}' --output json
aws ec2 describe-subnets --filters "Name=vpc-id,Values=$VPC" \
  --query 'Subnets[].[SubnetId,AvailabilityZone,Tags[?Key==`Name`]|[0].Value]' --output table
```

The private subnets are those whose route table has a NAT gateway.

**YOUR DECISION:** which private subnet. **Default:** the private subnet in
`us-east-2b`, or the first private subnet if none is there.

Fill in `proof.tfvars`: `vpc_id`, `subnet_id`, `availability_zone` (the
subnet's), `public_key` (box A2), `provisioning_version` (the tag of
`csis-sandbox-provisioning` merged for spec 001) and `cloudflow_version`
(cloudflow's newest tag). Leave `compare_with_script = false` unless stage D
is wanted.

Save the network as it is now, for box E5:

```sh
# A3 -- box 2 of 3 -- v2
export AWS_PROFILE=noaa AWS_REGION=us-east-2
PROOF=$HOME/csis-live-proof
VPC=$(grep '^vpc_id' "$PROOF/proof.tfvars" | cut -d'"' -f2)
aws ec2 describe-vpcs --vpc-ids "$VPC" --output json > "$PROOF/vpc-before.json"
aws ec2 describe-subnets --filters "Name=vpc-id,Values=$VPC" --output json > "$PROOF/subnets-before.json"
aws ec2 describe-route-tables --filters "Name=vpc-id,Values=$VPC" --output json > "$PROOF/routes-before.json"
ls -l "$PROOF"/*-before.json
```

It must list three files, none empty.

```sh
# A3 -- box 3 of 3 -- v2
grep -n 'FILL IN' "$HOME/csis-live-proof/proof.tfvars" || echo "settings: complete"
```

It must print `settings: complete`.

### A4. A workspace of its own, and the plan (your local machine)

About two minutes: OpenTofu fetches its providers.

```sh
# A4 -- box 1 of 1 -- v3
export AWS_REGION=us-east-2
eval "$(aws configure export-credentials --profile noaa --format env)"; unset AWS_PROFILE
cd "$HOME/csis-live-proof"
"$HOME/Cloud-Sandbox/exportit/sandbox-terraform/.tofu/1.13.9/tofu" init -input=false
TOFU="$HOME/Cloud-Sandbox/exportit/sandbox-terraform/.tofu/1.13.9/tofu"
"$TOFU" workspace new live-proof
"$TOFU" plan -var-file=proof.tfvars -out=proof.plan | tail -3
```

It must end with `Plan: N to add, 0 to change, 0 to destroy.` Read the list:
every resource is new and named with the prefix. **If anything is to change or
be destroyed, stop**: nothing is applied.

### A5. Create it (your local machine)

**Changes AWS:** this creates the head node, its EFS volume, groups, role and
key pair. About five minutes; the first boot then runs for hours on its own.

```sh
# A5 -- box 1 of 2 -- v3
export AWS_REGION=us-east-2
eval "$(aws configure export-credentials --profile noaa --format env)"; unset AWS_PROFILE
cd "$HOME/csis-live-proof"
TOFU="$HOME/Cloud-Sandbox/exportit/sandbox-terraform/.tofu/1.13.9/tofu"
test "$("$TOFU" workspace show)" = live-proof && "$TOFU" apply proof.plan
"$TOFU" output -raw instance_id
```

It must end with `Apply complete!` and print the node's id. Within a few
minutes the node answers Session Manager:

```sh
# A5 -- box 2 of 2 -- v2
export AWS_PROFILE=noaa AWS_REGION=us-east-2
ID=$("$HOME/Cloud-Sandbox/exportit/sandbox-terraform/.tofu/1.13.9/tofu" -chdir="$HOME/csis-live-proof" output -raw instance_id)
aws ssm describe-instance-information --filters "Key=InstanceIds,Values=$ID" --query 'InstanceInformationList[0].PingStatus' --output text
```

It must print `Online` (repeat after a minute if it prints `None`). Every box
on **the head node** below runs in `aws ssm start-session --target $ID`.

## Stage B: the build

### B1. Follow the first boot (the head node)

The first boot runs as root in cloud-init, writing `/root/setup.log`. This
box can be run as often as wanted, from any session; closing it stops nothing.

```sh
# B1 -- box 1 of 1 -- v2
sudo tail -n 5 /root/setup.log
sudo cloud-init status
```

Wait until `cloud-init status` says `done` (or `error`). On the first run,
with `c6i.8xlarge`, 34 minutes, Spack compiling the environment's 24 packages
(ESMF, PETSc, HDF5, netCDF and the rest; Python, GCC and Intel's compilers
and MPI are the system's). Since `csis-sandbox-provisioning` 0.0.4 the
environment installs from the RHEL 10 build cache (Cloud-Sandbox's spec 002),
and the whole first boot took 24 minutes. Check early as well as late: a boot that fails stops within
seconds, and the node then waits, idle, for as long as no one looks.

### B2. The first boot's result (the head node)

```sh
# B2 -- box 1 of 2 -- v3
sudo grep -A3 'PLAY RECAP' /root/setup.log | tail -4
sudo grep -E 'FAILED|left for LIVE-PROOF' /root/setup.log
```

The recap must show `failed=0`, and the last line must be the one saying the
node image is left for stage C. A `FAILED` line names the step that stopped.

**If it stopped**, the fix is made, merged and tagged in the unit it concerns,
`provisioning_version` (or `cloudflow_version`) in `proof.tfvars` set to the
new tag, and the node booted again. The EFS volume is replaced with it: the
first boot makes the `/save` link only on a new volume, so a node replaced on
the old one cannot clone cloudflow (a finding of the first run, to be fixed in
`csis-sandbox-terraform`). Then box B1 again.

**Changes AWS:** this replaces the head node and its EFS volume, with
everything on the volume. About ten minutes. Read the plan's list first: the
instance, the volume, its mount target and two local files, and nothing else.

```sh
# B2 -- box 2 of 2 -- v3
export AWS_REGION=us-east-2
eval "$(aws configure export-credentials --profile noaa --format env)"; unset AWS_PROFILE
cd "$HOME/csis-live-proof"
TOFU="$HOME/Cloud-Sandbox/exportit/sandbox-terraform/.tofu/1.13.9/tofu"
test "$("$TOFU" workspace show)" = live-proof && "$TOFU" plan -var-file=proof.tfvars \
  -replace=aws_efs_file_system.main_efs -replace=aws_instance.head_node -out=again.plan | tail -3
"$TOFU" apply again.plan
"$TOFU" output -raw instance_id
```

It must print `Plan: 5 to add, 0 to change, 5 to destroy.`, then
`Apply complete!` and the new node's id; box A5's second box then shows it
`Online`.

### B3. Apply it again (the head node)

About ten minutes (six on the first run); it runs on even if the session
closes.

```sh
# B3 -- box 1 of 1 -- v2
cd /opt/sandbox-provisioning && export ANSIBLE_CONFIG=/opt/sandbox-provisioning/ansible.cfg
sudo touch /root/second-apply.started
sudo -E nohup ansible-playbook -i inventories/local/hosts.yml site.yml \
  --extra-vars "spack_site_mirror=true sandbox_user=ec2-user project_tag=CSIS-Live-Proof" > /tmp/site-second.log 2>&1 &
sleep 5; tail -n 2 /tmp/site-second.log
```

When it is done (`grep -A3 'PLAY RECAP' /tmp/site-second.log`), every
`changed:` line in `/tmp/site-second.log` is a finding. A change caused by an
upstream release since the first apply is repeated once before it is called
one.

### B4. Check mode (the head node)

```sh
# B4 -- box 1 of 1 -- v2
cd /opt/sandbox-provisioning && export ANSIBLE_CONFIG=/opt/sandbox-provisioning/ansible.cfg
sudo -E ansible-playbook -i inventories/local/hosts.yml site.yml --check \
  --extra-vars "spack_site_mirror=true sandbox_user=ec2-user project_tag=CSIS-Live-Proof" > /tmp/site-check.log 2>&1
grep -A3 'PLAY RECAP' /tmp/site-check.log | tail -2
```

Every task that would change is a finding.

### B5. Spack's configuration (the head node)

```sh
# B5 -- box 1 of 1 -- v2
cd /opt/sandbox-provisioning
sudo -u ec2-user python3 tests/container/compare-spack-config.py \
  --spack /save/environments/spack.v1.2.0/bin/spack --expected tests/container/expected-spack-config.json
```

Each difference it lists is a finding, not a failure.

### B6. Module files (the head node)

```sh
# B6 -- box 1 of 1 -- v2
sudo find /save/environments -path '*modules*' -type f -newer /root/second-apply.started | head
```

It must print nothing: the second apply rewrote no module file
(`refresh_modules: when_needed`).

### B7. JupyterHub (the head node)

The `jupyterhub` role needs six settings only a site can give, and refuses to
run without them (`README.md`, "JupyterHub, if a site wants it"). The proof
gives it the container test's values (`tests/container/vars.yml`): a name that
cannot resolve and no certificate, so nginx is enabled and not started, and
the hub answers on its own port. A real site gives its own.

```sh
# B7 -- box 1 of 1 -- v3
cd /opt/sandbox-provisioning && export ANSIBLE_CONFIG=/opt/sandbox-provisioning/ansible.cfg
sudo tee /root/jupyterhub-proof.yml >/dev/null <<'EOF'
jupyterhub_server_name: hub.example.invalid
jupyterhub_oauth_callback_url: https://hub.example.invalid/hub/oauth_callback
jupyterhub_ssl_certificate: /etc/ssl/hub.example.invalid.crt
jupyterhub_ssl_certificate_key: /etc/ssl/hub.example.invalid.key
jupyterhub_admin_users_literal: "{'jupyter'}"
jupyterhub_username_map_literal: "{}"
EOF
sudo -E ansible-playbook -i inventories/local/hosts.yml jupyterhub.yml \
  --extra-vars @/root/jupyterhub-proof.yml > /tmp/jupyterhub.log 2>&1
curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:8000/hub/login
```

It must print `200`.

## Stage C: the node image

### C1. Make it (your local machine, then the head node)

The image's name is the one the module chose for this deployment:

```sh
# C1 -- box 1 of 2 -- v2
"$HOME/Cloud-Sandbox/exportit/sandbox-terraform/.tofu/1.13.9/tofu" -chdir="$HOME/csis-live-proof" output -raw ami_name
```

Put the printed name in the next box, on **the head node**.

**Changes AWS:** this makes a machine image and its snapshot. About fifteen
minutes.

```sh
# C1 -- box 2 of 2 -- v2
cd /opt/sandbox-provisioning && export ANSIBLE_CONFIG=/opt/sandbox-provisioning/ansible.cfg
sudo -E ansible-playbook -i inventories/local/hosts.yml node-image.yml \
  --extra-vars "sandbox_user=ec2-user project_tag=CSIS-Live-Proof ami_name=PUT-THE-NAME-HERE" > /tmp/node-image.log 2>&1
grep -A3 'PLAY RECAP' /tmp/node-image.log | tail -2
```

The recap must show `failed=0`.

### C2. See it from outside (your local machine)

```sh
# C2 -- box 1 of 1 -- v2
export AWS_PROFILE=noaa AWS_REGION=us-east-2
aws ec2 describe-images --owners self --filters 'Name=name,Values=CSIS-Live-Proof-*' \
  --query 'Images[].[Name,State,BlockDeviceMappings[0].Ebs.SnapshotId]' --output table
```

The image must be `available`, with its snapshot.

## Stage D: compare with a node built the original way (only with the flag)

**Skipped unless `compare_with_script = true`** in `proof.tfvars`, which is
off by default. With it, box A5 also made a second node, `CSIS-Live-Proof-script`,
booted by the original's first boot at the units' baseline (`ca0604a`), which
also makes its own image. Compare the two nodes' installed packages
(`rpm -qa | sort`), users (`getent passwd`), services
(`systemctl list-unit-files --state=enabled`), Spack's configuration (box B5
on each) and module files; each difference is a finding. With the flag off,
record the comparison as deferred.

## Stage E: remove everything

### E1. The workspace (your local machine)

```sh
# E1 -- box 1 of 1 -- v2
cd "$HOME/csis-live-proof" && "$HOME/Cloud-Sandbox/exportit/sandbox-terraform/.tofu/1.13.9/tofu" workspace show
```

It must print `live-proof`. If it prints anything else, **stop**: the next box
would destroy another sandbox.

### E2. Destroy what OpenTofu made (your local machine)

**Changes AWS:** this removes the node (and the `-script` node), the EFS
volume, the groups, the role and the key pair. Read the list before you
answer. About five minutes.

```sh
# E2 -- box 1 of 1 -- v3
export AWS_REGION=us-east-2
eval "$(aws configure export-credentials --profile noaa --format env)"; unset AWS_PROFILE
cd "$HOME/csis-live-proof"
"$HOME/Cloud-Sandbox/exportit/sandbox-terraform/.tofu/1.13.9/tofu" destroy -var-file=proof.tfvars
```

It must end with `Destroy complete!`

### E3. The images and snapshots (your local machine)

```sh
# E3 -- box 1 of 2 -- v2
export AWS_PROFILE=noaa AWS_REGION=us-east-2
aws ec2 describe-images --owners self --filters 'Name=name,Values=CSIS-Live-Proof-*' \
  --query 'Images[].[ImageId,BlockDeviceMappings[0].Ebs.SnapshotId]' --output text
```

It prints each image's id and its snapshot's. For each line:

**Changes AWS:** this removes one image and its snapshot.

```sh
# E3 -- box 2 of 2 -- v2
export AWS_PROFILE=noaa AWS_REGION=us-east-2
aws ec2 deregister-image --image-id PUT-THE-IMAGE-ID-HERE
aws ec2 delete-snapshot --snapshot-id PUT-THE-SNAPSHOT-ID-HERE
```

### E4. Nothing left with the prefix (your local machine)

Each kind of resource is asked for by its own call. The tagging API's index
lags deletion: on the first run it still listed two instances, the snapshot
and a volume with the proof's tag minutes after they were gone, so its answer
is shown last, and a line there is checked by the resource's own call.

```sh
# E4 -- box 1 of 1 -- v3
export AWS_PROFILE=noaa AWS_REGION=us-east-2
TAG='Name=tag:Project,Values=CSIS-Live-Proof'
echo "instances: $(aws ec2 describe-instances --filters "$TAG" 'Name=instance-state-name,Values=pending,running,stopping,stopped' --query 'Reservations[].Instances[].InstanceId' --output text)"
echo "volumes: $(aws ec2 describe-volumes --filters "$TAG" --query 'Volumes[].VolumeId' --output text)"
echo "images: $(aws ec2 describe-images --owners self --filters 'Name=name,Values=CSIS-Live-Proof-*' --query 'Images[].ImageId' --output text)"
echo "snapshots: $(aws ec2 describe-snapshots --owner-ids self --filters "$TAG" --query 'Snapshots[].SnapshotId' --output text)"
echo "file systems: $(aws efs describe-file-systems --query "FileSystems[?Tags[?Key=='Project' && Value=='CSIS-Live-Proof']].FileSystemId" --output text)"
echo "tagging index (may lag):"
aws resourcegroupstaggingapi get-resources --tag-filters Key=Project,Values=CSIS-Live-Proof --query 'ResourceTagMappingList[].ResourceARN' --output text
```

The first five lines must name nothing after their colons. The index may still
list some of the proof's resources for a while; each one listed must be
terminated or not found by its own call.

### E5. The network as it was (your local machine)

The comparison sorts what AWS lists in no fixed order (a route table's
associations; on the first run two came back swapped) and leaves out the
subnets' free-address counts, which other users of the VPC change. The
counts are printed after, to be read.

```sh
# E5 -- box 1 of 1 -- v3
export AWS_PROFILE=noaa AWS_REGION=us-east-2
PROOF=$HOME/csis-live-proof
VPC=$(grep '^vpc_id' "$PROOF/proof.tfvars" | cut -d'"' -f2)
ROUTES='[.RouteTables[] | .Associations |= sort_by(.RouteTableAssociationId)] | sort_by(.RouteTableId)'
SUBNETS='[.Subnets[] | del(.AvailableIpAddressCount)] | sort_by(.SubnetId)'
COUNTS='.Subnets | sort_by(.SubnetId)[] | [.SubnetId, .AvailableIpAddressCount] | @tsv'
aws ec2 describe-vpcs --vpc-ids "$VPC" --output json | jq -S . | diff - <(jq -S . "$PROOF/vpc-before.json") && echo "VPC: as it was"
aws ec2 describe-subnets --filters "Name=vpc-id,Values=$VPC" --output json | jq -S "$SUBNETS" | diff - <(jq -S "$SUBNETS" "$PROOF/subnets-before.json") && echo "subnets: as they were"
aws ec2 describe-route-tables --filters "Name=vpc-id,Values=$VPC" --output json | jq -S "$ROUTES" | diff - <(jq -S "$ROUTES" "$PROOF/routes-before.json") && echo "routes: as they were"
aws ec2 describe-subnets --filters "Name=vpc-id,Values=$VPC" --output json | jq -r "$COUNTS" | paste - <(jq -r "$COUNTS" "$PROOF/subnets-before.json" | cut -f2)
```

It must print all three `as it was` / `as they were` lines, then each subnet
with its free addresses now and before. A difference that is not the proof's
(another sandbox's subnet counts changing, say) is noted, not a failure; one
that is the proof's is.

## What to bring back

The logs stay on your local machine and the node: they hold the node's
addresses and the account's identifiers. Copy what is wanted off the node
before box E2 removes it. Their summary, every finding, and each row of the
"Not proved" table (Cloud-Sandbox's `exportit/MAP.md`), proved or not, go
into spec 001's outcome.
