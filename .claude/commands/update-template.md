---
description: Update this project to a newer bmad-beads-template release, resolving any merge conflicts
argument-hint: "[--ref vX.Y.Z] [--dry-run] [--skip GLOB]"
---

Update this project from its bmad-beads-template release. Work through the four steps in order
and report at each one. Every run of the updater leaves a folder `.template-update/<timestamp>/`
holding `REPORT.md` (what it did), `undo.sh`, `backup/`, and, when there are conflicts,
`CONFLICTS.md` plus `conflicts/`. "The run" below means the newest such folder.

1. **Start or resume.**
   - **Resume** if the newest run (folder names are timestamps, so the last one alphabetically)
     has uncommitted work: a `CONFLICTS.md` with an unticked box (`- [ ]`) → step 2; every box
     ticked, or no `CONFLICTS.md`, but its files still uncommitted → step 3. The updater only
     runs on a clean tree, so those uncommitted changes are that run's own work: don't run the
     updater again, and don't commit or stash them.
   - **Otherwise run it** from the project root: `uv run scripts/update_from_template.py $ARGUMENTS`.
     Projects made before v0.3.0 don't have the script; use
     `uv run https://raw.githubusercontent.com/chhudson/bmad-beads-template/main/scripts/update_from_template.py $ARGUMENTS`.
     Exit 0: done, no conflicts. Exit 2: conflicts and/or failing tests. Exit 1: it did not run. If
     it refused because of uncommitted changes, show `git status --short` and ask the user whether
     to commit or stash; never do either on your own.

2. **Resolve each unticked conflict** in the run's `CONFLICTS.md`. For each `path`, the project
   file is exactly as it was before the update. `conflicts/<path>.base`, `.local` and `.template`
   hold the three versions.
   - Diff `.base` → `.local`: the project's changes. Keep every one.
   - Diff `.base` → `.template`: the template's changes. Apply every one.
   - When both changed the same lines, write the template's text first, unchanged, and the
     project's additions after it, wrapped to the width of the template's lines around them.
     If the two genuinely contradict (the project removed something the template changed), keep
     the project's version and tell the user what the template wanted.
   - Write the result to `path`. Then run `uv run scripts/update_from_template.py --check <path>`,
     which covers `.json` (duplicate keys too), `.toml`, `.py`, `.sh` and leftover conflict markers.
     For `Taskfile.yml`, also run `task --list`. For `.github/workflows/*.yml`, run `actionlint` if
     it is installed; otherwise re-read the file for indentation. `.md` needs no check.
   - Tick the box: `- [x]`.
   Don't edit any project file that isn't listed there.

3. **Check**: run `uv run scripts/test_bmad_beads.py`, then `uv run scripts/bmad_beads.py doctor`.
   If something the update broke fails, fix it. If a failure has nothing to do with the update,
   note it and carry on to step 4 anyway; don't try to fix it.

4. **Report**, using the run's `REPORT.md`, not your memory of the updater's output:
   - the version jump. If REPORT.md says the base was **guessed**, say so plainly: a wrong base
     changes which edits count as the project's. `--base vX.Y.Z` re-runs it with the right one.
   - the files REPORT.md lists as changed, with `git diff --stat`
   - one line per conflict: how you resolved it
   - files the report marks `ignored (changed upstream)`, `removed upstream, kept` or `deleted locally, not restored`
   - the "Do these by hand" steps. For the ones that are safe to automate
     (e.g. `uv run scripts/bmad_beads.py sync`), ask whether to run them, and run nothing until
     the user says yes. Leave the judgement calls (e.g. deleting a workflow) to the user.
   - how to undo the whole update, including your conflict resolutions:
     `bash .template-update/<timestamp>/undo.sh`

   Don't commit unless the user asks. Once they have committed, the run's folder is no longer
   needed. It is gitignored, so offer to delete it rather than leaving it to pile up.
