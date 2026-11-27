# Specs

The specs of `csis-sandbox-provisioning`'s own work, made with Spec Kit. Each
spec has a directory of its own: `spec.md` says what and why, `plan.md` how,
and `tasks.md` the steps, ticked as they are done. Work that spans units is
planned in Cloud-Sandbox, as a spec under its `specs/`, not here. Every spec is
held to the [constitution](../.specify/memory/constitution.md).

A spec is done when its tasks are ticked, `just full-test` passes, a
`/speckit-converge` run finds nothing left, it is merged into `develop` on the
operator's word, and the release that carries it is named below.

**Converged** is ✅ when the last `/speckit-converge` run on the spec appended
no tasks, and ❌ when it appended some or has never been run. **Last converge
check** is the date of that run, or `never`.

| # | Spec | Converged | Serves | Ends in | State | Needs first | Branch | Tasks | Released in | Last converge check |
| ---: | --- | --- | --- | --- | --- | --- | --- | ---: | --- | --- |
| 1 | [001 A package install that loses its downloads to another dnf tries again](001-dnf-retries/spec.md) | ❌ | the operator who boots a head node; a site whose account runs its own patch scans | a test in which a package task's downloads are taken away during its first attempt succeeding on a later one, 10 runs out of 10; a missing package failing within 3 minutes; the next head node's first boot ending `failed=0` | drafted, 2026-11-27 ([spec](001-dnf-retries/spec.md)) | nothing | none yet | | | never |

Before Spec Kit, this repository's work was planned in Cloud-Sandbox: its
stages, then its specs 001, 002, 004 and 009, which made the releases 0.0.1 to
0.0.6.
