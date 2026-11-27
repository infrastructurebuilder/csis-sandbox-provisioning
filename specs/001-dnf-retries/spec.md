# Feature Specification: A package install that loses its downloads to another dnf tries again

**Feature Branch**: none yet

**Created**: 2026-11-27, on the operator's instruction of that day, after the
first boot of Cloud-Sandbox's spec 004 head node failed: "Replace node, same
0.0.6 and write a spec for adding retries to base_system's dnf tasks in
csis-sandbox-provisioning."

**Status**: Draft

**Input**: User description: "base_system's dnf tasks retry when another dnf on
the node takes their cache away. Found 2026-11-27 on Cloud-Sandbox spec 004's
head node … a race with the account, not a code bug, but it fails a first
boot … retry a bounded number of times with a delay on a failure of this kind,
and a genuine failure (a package that does not exist, a repository that is
down) still fails, within a bounded time; the container test or a unit test
shows a retry happening. Not in scope: changing the account's associations."

## What happened

On 2026-11-27 the first boot of Cloud-Sandbox's spec 004 head node
(`i-0e072db9769af2082`, `csis-sandbox-provisioning` 0.0.6) failed one minute
in, at the `base_system` task "Update every installed package". dnf could not
open a package it had just downloaded:

```text
FileNotFoundError: [Errno 2] No such file or directory:
'/var/cache/dnf/rhel-10-appstream-rhui-rpms-a3d654160ef63c8a/packages/python3-policycoreutils-3.11-1.el10.noarch.rpm'
```

The node's logs show why. As soon as its Session Manager agent registered
(11:39:43 UTC), the noaa account's own State Manager associations ran on it:
`AWS-RunPatchBaselineAssociation` (with `AWS-RedHatDefaultPatchBaseline`) and
`AWS-GatherSoftwareInventory`. The patch scan ran `dnf makecache`, `dnf list
installed`, `dnf repoquery`, `dnf module list` and then `dnf clean all`
(11:40:17), which removed the packages the update was in the middle of
installing. The nodes of spec 001 and spec 002 met the same associations and
were not hit: it is a race with the account, decided by timing, and not a fault
of the playbooks' tasks. The node was replaced on the same 0.0.6, the
operator's choice.

The account's associations are the account's, and not this repository's to
change. What this repository can do is make a package task that loses its
downloads this way try again, instead of failing the boot.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - A first boot survives the account's patch scan (Priority: P1)

The operator boots a head node (Cloud-Sandbox's live-proof procedure, or any
site's). While `site.yml` installs or updates packages, another dnf on the node
(the account's patch scan, an automatic metadata refresh, an administrator)
removes the cache the task is using. The task tries again after a pause, the
second or third attempt finds the packages, and the boot goes on to the end.

**Why this priority**: a failed first boot costs a node replacement (about ten
minutes, and the EFS volume with it) and a person watching for it; this one
failed after a minute and the node then sat idle until someone looked.

**Independent Test**: on a test machine, make a package task's first attempt
fail the way the node's did (its downloads taken away under it), and see the
task try again and succeed, reporting the attempts.

**Acceptance Scenarios**:

1. **Given** a package task whose first attempt fails because its downloaded
   packages vanished from dnf's cache, **When** the play runs, **Then** the
   task tries again after a pause, succeeds, and the play goes on; the output
   shows that it took more than one attempt.
2. **Given** a package task whose first attempt fails because dnf's lock is
   held by another dnf, **When** the play runs, **Then** the task waits and
   tries again in the same way.
3. **Given** a run in which nothing interferes, **When** the play runs twice,
   **Then** each task succeeds on its first attempt, and the second run
   changes nothing, as now (constitution, principle II).

---

### User Story 2 - A real failure still fails, and soon (Priority: P1)

A package that does not exist, a repository that is down or refuses the node,
a signature that does not verify: trying again does not help these. The
operator needs them to stop the boot, with dnf's own message, and not to be
retried at length or hidden behind a retry.

**Why this priority**: a retry that swallows real failures, or makes a boot
wait many minutes before failing, is worse than no retry.

**Independent Test**: give a package task a package name that does not exist;
the task fails with dnf's message, after no more than the bounded number of
attempts and the bounded wait.

**Acceptance Scenarios**:

1. **Given** a package task asked for a package that no repository has,
   **When** the play runs, **Then** it fails with dnf's message naming the
   package, and the time from its first attempt to the failure is within the
   bound of SC-003.
2. **Given** a failure of a kind that is not a lost download or a held lock,
   **When** the play runs, **Then** the task is not retried at all, or is
   retried no more than the bound, and fails with the first attempt's message.

---

### User Story 3 - Every package task of the first boot is covered (Priority: P2)

The update that failed is one of several package tasks a first boot runs
before the account's associations are done (they finish within minutes of the
agent registering). Each of them can meet the same race. The operator wants
all of them covered, not only the one that happened to fail this time.

**Why this priority**: the race is decided by timing; fixing one task moves it
to the next.

**Independent Test**: a test lists every package-installing task of the
playbooks and fails on any that does not retry in the agreed way.

**Acceptance Scenarios**:

1. **Given** the playbooks, **When** the tests run, **Then** every task that
   installs, updates or removes packages through dnf retries as specified, and
   a new such task without it fails the tests.

---

### Edge Cases

- **The other dnf runs for longer than the retries wait.** The task fails after
  its last attempt with dnf's message from that attempt; the bound is chosen so
  that a patch scan of the kind seen (about 40 seconds from `makecache` to
  `clean all`) is outlasted.
- **dnf's lock is held, not the cache cleaned.** dnf may wait for the lock on
  its own or fail at once; either way the task ends as in User Story 1.
- **A partial transaction.** An attempt that installed some packages before it
  failed leaves them installed; the next attempt installs the rest. The final
  state is the same as an uninterrupted run.
- **Check mode.** A preview does not download or install anything, so it is
  not retried differently; it reports what it would change, as now.
- **Package steps that are not tasks of these playbooks.** The first-boot
  script of `csis-sandbox-terraform` installs `git` and `ansible-core` with
  dnf before the playbooks run. It can meet the same race, but it is that
  unit's: the plan records it as a finding for that unit, and this spec does
  not change it.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: Every task of this repository's playbooks and roles that installs,
  updates or removes packages through dnf MUST retry when an attempt fails,
  up to a bounded number of attempts with a pause between them, and MUST
  succeed as soon as an attempt does.
- **FR-002**: A failure MUST be retried only when it is of a kind another dnf
  can cause: the downloaded packages missing from the cache, or the dnf lock
  held. Any other failure MUST stop the play on its first attempt, with dnf's
  message, unless the plan shows that telling the kinds apart is not
  dependable, in which case every failure is retried within the same bounds
  and the last attempt's message is the one shown.
- **FR-003**: The number of attempts and the pause MUST be the same for every
  such task, set in one place, and MUST be variables a site may change
  (constitution, principle III), with defaults that outlast a patch scan like
  the one seen on 2026-11-27.
- **FR-004**: A run with no interference MUST behave as today: every task
  succeeds on its first attempt, a second apply changes nothing, and check mode
  after it changes nothing (constitution, principle II).
- **FR-005**: The tests MUST hold FR-001 for every dnf task of the playbooks, so
  that a dnf task added later without the retry fails `just test`.
- **FR-006**: A test MUST show a retry happening: a package task whose first
  attempt fails as the node's did, which then succeeds, with the attempts
  visible in the output; and a test MUST show a package that does not exist
  failing within the bound.
- **FR-007**: Each changed task MUST keep its `# Replaces` or `# New:` comment
  (`tests/test_traceability.py`); the retry is a deliberate difference from the
  script (constitution, principle I) and is recorded as one where it is made.
- **FR-008**: The account's State Manager associations MUST NOT be changed, and
  nothing in this repository may stop, delay or disable them on a node.

### Key Entities

- **A package task**: a task of a role that installs, updates or removes
  packages through dnf (today: `base_system` seven, `intel_oneapi` two,
  `jupyterhub` one, `efa_driver` two, `fsx_lustre_client` one; the plan
  confirms the list).
- **The retry settings**: the number of attempts and the pause between them,
  shared by every package task.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: In the test that takes a package task's downloads away during its
  first attempt, the task succeeds on a later attempt in 10 runs out of 10.
- **SC-002**: The next head node booted with this change (Cloud-Sandbox's next
  live proof) ends its first boot with `failed=0`; if the account's patch scan
  overlapped a package task, its log shows the retry.
- **SC-003**: A package that does not exist fails its task within 3 minutes of
  the task's first attempt, with dnf's message naming the package.
- **SC-004**: `just test` fails when any dnf task of the playbooks lacks the
  retry; `just full-test`'s second apply and check mode still change nothing.

## Assumptions

- The race is with another dnf on the same node; network failures between the
  node and a repository are not this spec's subject, though a retry may help
  some of them.
- The account's associations run once, within minutes of the agent
  registering; the defaults are chosen against the scan seen on 2026-11-27
  (about 40 seconds), with margin.
- `csis-sandbox-provisioning` owns its copied files (Cloud-Sandbox's
  `exportit/sandbox-provisioning.map` says `owned`), so the roles change here.
- A release with the change (0.0.7 or later) is cut on the operator's word;
  Cloud-Sandbox's spec 004 continues on 0.0.6 and does not wait for it.
