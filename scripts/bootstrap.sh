#!/usr/bin/env bash
# One-shot project bootstrap for a repo created from bmad-beads-template.
#
#   bash scripts/bootstrap.sh                  # embedded Dolt (default): zero infra, sync via git remote
#   bash scripts/bootstrap.sh --server         # shared `dolt sql-server` for many concurrent writers
#   bash scripts/bootstrap.sh --prefix cdq     # bead id prefix (default: repo directory name)
#
# Idempotent: safe to re-run after pulling template updates or upgrading bmad/bd.
set -euo pipefail

PREFIX=""
MODE_FLAGS=()
USER_NAME="${BMAD_USER_NAME:-$(git config user.name 2>/dev/null || echo "$USER")}"
while [[ $# -gt 0 ]]; do
  case "$1" in
    --prefix) PREFIX="$2"; shift 2 ;;
    --server) MODE_FLAGS+=(--server); shift ;;
    --user-name) USER_NAME="$2"; shift 2 ;;
    -h|--help) sed -n 2,9p "$0"; exit 0 ;;
    *) echo "unknown arg: $1" >&2; exit 2 ;;
  esac
done

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
[[ -z "$PREFIX" ]] && PREFIX="$(basename "$ROOT" | tr '[:upper:]' '[:lower:]' | tr -c 'a-z0-9\n' '-' | sed 's/-*$//')"

say() { printf '\n\033[1m▶ %s\033[0m\n' "$*"; }
need() { command -v "$1" >/dev/null 2>&1 || { echo "missing: $1 — $2" >&2; exit 1; }; }

say "Preflight"
need git   "https://git-scm.com"
need node  "Node 20.12+ (https://nodejs.org)"
need uv    "https://docs.astral.sh/uv/  (curl -LsSf https://astral.sh/uv/install.sh | sh)"
if ! command -v bd >/dev/null 2>&1; then
  echo "bd not found — installing @beads/bd via npm (or: brew install beads)"
  npm install -g @beads/bd
fi
echo "bd:   $(bd version | head -1)"
echo "node: $(node -v)   uv: $(uv --version)"
[[ -d .git ]] || git init -q

say "BMAD Method (npx bmad-method install → _bmad/, .claude/skills/)"
# --yes is non-interactive; re-running performs an update and keeps _bmad/custom/ untouched.
npx -y bmad-method@latest install --yes --directory "$ROOT" --tools claude-code --modules bmm \
  --user-name "$USER_NAME" --output-folder _bmad-output >/dev/null
mkdir -p _bmad-output/planning-artifacts _bmad-output/implementation-artifacts docs
echo "installed: $(ls .claude/skills | wc -l | tr -d ' ') skills; team overrides in _bmad/custom/"

say "beads (bd init --prefix $PREFIX ${MODE_FLAGS[*]:-})"
if [[ -f .beads/config.yaml ]]; then
  echo "already initialised — skipping bd init"
else
  # --skip-agents: we ship our own AGENTS.md; bd's section can be added later with `bd onboard`.
  bd init --prefix "$PREFIX" --skip-agents --non-interactive "${MODE_FLAGS[@]}"
fi
# `review` is BMAD's between-build-and-code-review state; beads needs it as a custom status.
bd config set status.custom "review:wip" >/dev/null
bd config get status.custom >/dev/null && echo "custom status: review (wip)"

say "Claude Code hook (bd prime on SessionStart)"
# .claude/settings.json shipped with the template already carries the hook; `bd setup claude`
# is idempotent and will also refresh it after a bd upgrade.
bd setup claude >/dev/null 2>&1 || true
grep -q 'bd prime' .claude/settings.json && echo "hook present"

say "Seed memory"
bd remember --key bmad-beads-bridge "This repo uses the BMAD×beads bridge: AGENTS.md is the protocol; scripts/bmad_beads.py {import,sync,claim,status,doctor}. Never bd-close a story bead by hand — a story leaves review only via /bmad-code-review, and sync closes the bead. Discovered/deferred beads are top-level (--deps discovered-from), never children of a story." >/dev/null 2>&1 || true
# The conservative agent profile forbids git ops; the bridge needs two of them.
bd remember --key bmad-git-policy "Git policy for agents in this repo: a LOCAL git commit at the end of a BMAD build or code-review, and bd dolt push, are permitted — the workflow on_complete steps ask for them and they override the conservative no-git-ops profile. git push to the code remote stays a human decision." >/dev/null 2>&1 || true
# bd prime's default rules forbid "markdown files for task tracking"; BMAD's sprint-status.yaml must be exempt.
bd remember --key bmad-sprint-status "sprint-status.yaml and _bmad-output/** are BMAD's own artifacts, not task tracking: BMAD skills write them, scripts/bmad_beads.py sync mirrors them into beads. Never block a BMAD skill from writing sprint-status.yaml. Beads is the source of truth for readiness, claims and discovered work; sprint-status.yaml is the wire format." >/dev/null 2>&1 || true

say "Project README"
# A clone of the template still carries the template's own README, which describes
# the template rather than this project. Replace it with a stub once, on first run.
if grep -q '^# bmad-beads-template' README.md 2>/dev/null; then
  cat > README.md <<STUB
# ${PREFIX}

<!-- One paragraph: what this project is and who it is for. -->

Built on [bmad-beads-template](https://github.com/chhudson/bmad-beads-template):
BMAD Method for planning, beads for execution state. \`AGENTS.md\` is the operating
protocol; \`task --list\` shows the entry points; \`docs/BLUEPRINT.md\` explains the bridge.

## Run

<!-- How to run / test this project. -->
STUB
  echo "template README replaced with a project stub — fill it in"
else
  echo "README.md already project-specific — untouched"
fi

say "Doctor"
uv run --quiet scripts/bmad_beads.py doctor || true

cat <<EOF

Next:
  1. Commit:  git add -A && git commit -m "bootstrap BMAD×beads"
  2. Plan:    bd cook bmad-planning && bd mol pour bmad-planning --var initiative="<name>"
              then open Claude Code and run /bmad-help
  3. Sync beads across machines: bd dolt push  (bd init recorded your git remote as sync.remote)
EOF
