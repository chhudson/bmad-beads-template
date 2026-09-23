#!/usr/bin/env bash
# One-shot project bootstrap for a repo created from bmad-beads-template.
#
#   bash scripts/bootstrap.sh                  # embedded Dolt (default): zero infra, sync via git remote
#   bash scripts/bootstrap.sh --server         # shared `dolt sql-server` for many concurrent writers
#   bash scripts/bootstrap.sh --prefix cdq     # bead id prefix (default: repo directory name)
#   bash scripts/bootstrap.sh --keep-readme    # never replace README.md with the project stub
#   BMAD_VERSION=6.12.0 BD_VERSION=1.3.0 bash scripts/bootstrap.sh   # pin the pair (default: latest)
#
# Idempotent: safe to re-run after pulling template updates or upgrading bmad/bd.
set -euo pipefail

PREFIX=""
MODE_FLAGS=()
KEEP_README=0
# Unpinned by default so a new project never starts on a stale BMAD. `doctor` warns when the
# installed pair differs from the one the bridge was last validated on.
BMAD_VERSION="${BMAD_VERSION:-latest}"
BD_VERSION="${BD_VERSION:-latest}"
USER_NAME="${BMAD_USER_NAME:-$(git config user.name 2>/dev/null || echo "${USER:-}")}"
while [[ $# -gt 0 ]]; do
  case "$1" in
    --prefix) PREFIX="$2"; shift 2 ;;
    --server) MODE_FLAGS+=(--server); shift ;;
    --user-name) USER_NAME="$2"; shift 2 ;;
    --keep-readme) KEEP_README=1; shift ;;
    -h|--help) sed -n 2,10p "$0"; exit 0 ;;
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
NODE_V="$(node -v | sed 's/^v//')"
IFS=. read -r NODE_MAJOR NODE_MINOR _ <<<"$NODE_V"
if (( NODE_MAJOR < 20 || (NODE_MAJOR == 20 && NODE_MINOR < 12) )); then
  echo "Node $NODE_V is too old — BMAD needs 20.12+ (https://nodejs.org)" >&2
  exit 1
fi
need uv    "https://docs.astral.sh/uv/  (curl -LsSf https://astral.sh/uv/install.sh | sh)"
if ! command -v bd >/dev/null 2>&1; then
  echo "bd not found — installing @beads/bd@$BD_VERSION via npm (or: brew install beads)"
  # The package's postinstall downloads the binary, but skips it whenever $CI is set, which
  # leaves a bd that cannot run. Bootstrap needs bd wherever it runs, so clear CI for this call.
  # --foreground-scripts shows the download if it fails.
  CI= npm install -g --foreground-scripts "@beads/bd@$BD_VERSION"
elif [[ "$BD_VERSION" != latest ]] && ! bd version | grep -qF "$BD_VERSION"; then
  echo "warning: BD_VERSION=$BD_VERSION but $(bd version | head -1) is installed — bootstrap does not replace an existing bd" >&2
fi
if ! BD_V="$(bd version 2>&1)"; then
  echo "bd is on PATH but does not run: $BD_V" >&2
  echo "(an npm install whose postinstall could not download the binary looks like this — try: brew install beads)" >&2
  exit 1
fi
echo "bd:   $(head -1 <<<"$BD_V")"
echo "node: $(node -v)   uv: $(uv --version)"
[[ -d .git ]] || git init -q

say "BMAD Method $BMAD_VERSION (npx bmad-method install → _bmad/, .claude/skills/)"
# --yes is non-interactive; re-running performs an update and keeps _bmad/custom/ untouched.
npx -y "bmad-method@$BMAD_VERSION" install --yes --directory "$ROOT" --tools claude-code --modules bmm \
  --user-name "$USER_NAME" --output-folder _bmad-output >/dev/null
mkdir -p _bmad-output/planning-artifacts _bmad-output/implementation-artifacts docs
echo "installed: $(find .claude/skills -mindepth 1 -maxdepth 1 -type d | wc -l | tr -d ' ') skills; team overrides in _bmad/custom/"

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
# Never in the template repo itself (dogfooding bootstrap there would overwrite the template's README).
ORIGIN="$(git remote get-url origin 2>/dev/null || true)"
if (( KEEP_README )) || [[ "$ORIGIN" =~ [:/]chhudson/bmad-beads-template(\.git)?$ ]]; then
  echo "README.md kept (--keep-readme, or this is the template repo itself)"
elif grep -q '^# bmad-beads-template' README.md 2>/dev/null; then
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
  2. Plan:    bd mol pour bmad-planning --var initiative="<name>"
              then open Claude Code and run /bmad-help
  3. Sync beads across machines: bd dolt push  (bd init recorded your git remote as sync.remote)
EOF
