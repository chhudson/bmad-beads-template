# Upgrading

How to take a newer template release into a project made from this template:

```bash
uv run scripts/update_from_template.py            # or /update-template in Claude Code
```

Projects made before v0.3.0 don't have the script yet. Run it straight from the template:

```bash
uv run https://raw.githubusercontent.com/chhudson/bmad-beads-template/main/scripts/update_from_template.py
```

It merges each file with the project's own changes, leaves conflicts untouched for review, and prints
the steps below for every release it crosses. See the README section "Updating from the template".

## v0.3.0

- **bd 1.3 or newer is required** (`claim` uses `bd update --if-assignee`). `brew upgrade beads` or
  `npm i -g @beads/bd@latest`. `doctor` now warns on anything older and prints the installed
  BMAD / bd pair against the validated one.
- **Planning molecules poured before v0.3.0 have no step labels**, and the planning skills now find
  their step only by label (`bmad-step:<id>`), so they skip an old molecule without a word. Re-pour it
  (`bd mol pour bmad-planning --var initiative="<name>"`), or close its remaining steps by hand.
- **PRD sign-off is two closes**: the human gate bead (`bd gate list`), then the "PRD sign-off" step it
  unblocks. Architecture waits on the second.
- **The `upstream canary` workflow is new** (`.github/workflows/upstream-canary.yml`). It runs weekly,
  and when it fails it opens an issue in *this* repo. If you don't want that, delete the file
  (updates won't bring it back).
- Nothing to do for the rest (bridge fixes, stricter `Depends on:` parsing, the permission allowlist).
  After updating, run `uv run scripts/bmad_beads.py sync` once.
