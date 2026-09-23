#!/usr/bin/env -S uv run --quiet --script
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Upstream canary: drive the bridge through one story lifecycle against the BMAD and bd that
are actually installed, with BMAD's own sprint_plan.py writing sprint-status.yaml.

Run from a project that `scripts/bootstrap.sh` has set up (CI does this weekly against
@latest; see .github/workflows/upstream-canary.yml). Exits non-zero on the first broken
expectation. It writes beads and planning artifacts: never run it in a real project.

  uv run scripts/canary.py
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from datetime import date
from pathlib import Path

ROOT = Path.cwd()
BRIDGE = ["uv", "run", "--quiet", str(ROOT / "scripts" / "bmad_beads.py")]
PLANNING = ROOT / "_bmad-output" / "planning-artifacts"
IMPL = ROOT / "_bmad-output" / "implementation-artifacts"
STATUS = IMPL / "sprint-status.yaml"
S11, S12, S21 = "1-1-schema-exists", "1-2-seed-data", "2-1-read-endpoint"


def run(*cmd: str, expect: int = 0) -> str:
    res = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True)
    print(f"$ {' '.join(cmd)}  → {res.returncode}")
    if res.returncode != expect:
        sys.exit(f"canary: expected exit {expect}\n--- stdout\n{res.stdout}\n--- stderr\n{res.stderr}")
    return res.stdout


def sprint_plan(*args: str) -> dict:
    script = next(ROOT.glob(".claude/skills/bmad-sprint-planning/scripts/sprint_plan.py"), None)
    if script is None:
        sys.exit("canary: BMAD's sprint_plan.py not found — did BMAD move or rename it?")
    out = json.loads(run("uv", "run", "--quiet", str(script), *args, "--status-file", str(STATUS)))  # PEP 723 deps
    if out.get("ok") is False:
        sys.exit(f"canary: sprint_plan.py {args[0]} reported failure: {out}")
    return out


def status() -> dict[str, dict]:
    return {r["story_key"]: r for r in json.loads(run(*BRIDGE, "status", "--json"))}


def check(what: str, got, want) -> None:
    print(f"  {'✓' if got == want else '✗'} {what}: {got!r}" + ("" if got == want else f" (want {want!r})"))
    if got != want:
        sys.exit(f"canary: {what}")


def set_yaml(key: str, value: str) -> None:
    text = STATUS.read_text(encoding="utf-8")
    text, n = re.subn(rf"^(\s+{re.escape(key)}:\s*)[\w-]+", rf"\g<1>{value}", text, flags=re.M)
    if n != 1:
        sys.exit(f"canary: no `{key}:` row in {STATUS}")
    STATUS.write_text(text, encoding="utf-8")


def main() -> int:
    PLANNING.mkdir(parents=True, exist_ok=True)
    IMPL.mkdir(parents=True, exist_ok=True)
    epics = PLANNING / "epics.md"
    epics.write_text((Path(__file__).parent / "fixtures" / "canary-epics.md").read_text(encoding="utf-8"), encoding="utf-8")

    print("== BMAD sprint planning writes sprint-status.yaml; the bridge imports and syncs")
    sprint_plan("generate", "--epic-file", str(epics), "--stories-dir", str(IMPL),
                "--project", "canary", "--date", date.today().isoformat())
    run(*BRIDGE, "import")
    run(*BRIDGE, "sync")
    st = status()
    check("story keys (bridge == BMAD slug rule)", sorted(st), [S11, S12, S21])
    check("1.1 ready", (st[S11]["yaml"], st[S11]["ready"]), ("ready-for-dev", "READY"))
    check("1.2 waits on 1.1", st[S12]["yaml"], "backlog")
    check("2.1 waits on Epic 1", st[S21]["yaml"], "backlog")

    print("== claim guard")
    run(*BRIDGE, "claim", S12, "--actor", "canary", expect=1)
    run(*BRIDGE, "claim", S11, "--actor", "canary")
    run(*BRIDGE, "sync")
    st = status()
    check("1.1 claimed", (st[S11]["yaml"], st[S11]["beads"], st[S11]["assignee"]), ("in-progress", "in_progress", "canary"))

    print("== build → review → done, and the cascade")
    set_yaml(S11, "review")
    run(*BRIDGE, "sync")
    check("1.1 in review", status()[S11]["beads"], "review")
    set_yaml(S11, "done")
    run(*BRIDGE, "sync")
    st = status()
    check("1.1 closed", st[S11]["beads"], "closed")
    check("1.2 unblocked", st[S12]["yaml"], "ready-for-dev")
    check("2.1 still waits on Epic 1", st[S21]["yaml"], "backlog")
    run(*BRIDGE, "claim", S12, "--actor", "canary")
    set_yaml(S12, "done")
    run(*BRIDGE, "sync")
    st = status()
    check("2.1 unblocked by the Epic 1 milestone", st[S21]["yaml"], "ready-for-dev")

    print("== BMAD accepts what the bridge wrote")
    sprint_plan("validate")
    rows = sprint_plan("status")
    print(f"  sprint_plan.py status: {json.dumps(rows)[:200]}")
    run(*BRIDGE, "doctor")
    print("canary: OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
