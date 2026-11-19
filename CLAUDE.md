# csis-sandbox-provisioning

This repository uses [Spec Kit](https://github.com/github/spec-kit), and
nothing else, to plan and track its own work. This file points at the rules;
it adds none of its own.

- **Read the constitution first:**
  [.specify/memory/constitution.md](.specify/memory/constitution.md). It is
  above every other practice here.
- **Work is planned in specs**, under `specs/`, with `/speckit-specify`,
  `/speckit-plan`, `/speckit-tasks` and `/speckit-implement`. A rule that says
  plans go in `PLAN.md` is met here by a spec. There is no `PLAN.md` in this
  repository; do not create one. Work that spans units is planned in
  Cloud-Sandbox, as a spec under its `specs/`.
- **A copied file is not edited here while Cloud-Sandbox holds its
  original**, that is, while Cloud-Sandbox's `exportit/sandbox-provisioning.map` does not
  say `owned`: it changes there, by the original or by a patch, and
  Cloud-Sandbox's `just export sandbox-provisioning` writes it here. Once the map says
  `owned`, the originals are gone and the copied files are this repository's;
  later changes from the original arrive by Cloud-Sandbox's `just export-sync`.
- **Verify with the `Justfile`:** `just test` after every change,
  `just full-test` before a spec is called done or a release is cut.
- **Commit locally.** Merge, push and release only on the operator's word.
  Nothing goes toward `ioos`.
