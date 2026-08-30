#!/usr/bin/env -S uv run --quiet --script
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""
bmad_beads.py — the bridge between BMAD Method (v6.11+) planning artifacts and
beads (bd ≥ 1.2, Dolt-backed).

Ownership contract (one owner per field, no reconciliation logic):

  BMAD owns   : planning artifacts (brief/PRD/architecture/epics.md) and the
                story lifecycle status it writes during build
                (in-progress → review → done).
  beads owns  : the dependency graph, claims/assignees, discovered work,
                cross-session memory (bd prime / bd remember).
  sprint-status.yaml is the wire format between them.
    - `ready-for-dev` / `backlog` for a story is DERIVED from `bd ready`.
    - `in-progress` / `review` / `done` written by BMAD flow INTO beads.
    - statuses this script does not know (e.g. bmad-loop's
      `awaiting-operator`) pass through untouched.

Commands
  import   epics.md  → beads (epics as `epic`, stories as child `task`s,
                              deps from `Depends on:` lines). Idempotent.
  sync     sprint-status.yaml ↔ beads, per the contract above. Idempotent.
  status   one table: story key, bead id, yaml status, bead status, ready.
  doctor   preconditions + drift report. Exit 1 on hard failures.

Everything shells out to `bd --json`; no beads internals are touched.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

# ----------------------------------------------------------------------------
# Constants mirrored from BMAD (bmad-sprint-planning/scripts/sprint_plan.py)
# ----------------------------------------------------------------------------
EPIC_RE = re.compile(r"^#{1,3}\s*Epic\s+(\d+)\s*:?\s*(.*?)\s*#*\s*$", re.IGNORECASE)
STORY_RE = re.compile(r"^#{2,4}\s*Story\s+(\d+)\.(\d+[a-z]?)\s*:?\s*(.*?)\s*#*\s*$", re.IGNORECASE)
FENCE_RE = re.compile(r"^\s{0,3}(?:```|~~~)")
# Our own convention (taught to the PM agent via persistent_facts):
#   **Depends on:** 1.3, 2.1        (story-level)
#   **Depends on:** Epic 1          (epic-level)
DEPENDS_RE = re.compile(r"^\**\s*(?:Depends on|Blocked by)\s*:?\**\s*(.+?)\s*$", re.IGNORECASE)
STORY_REF_RE = re.compile(r"\b(\d+)\.(\d+[a-z]?)\b")
EPIC_REF_RE = re.compile(r"\bEpic\s+(\d+)\b", re.IGNORECASE)

# BMAD story vocabulary, ranked. Anything else is "unknown" and passes through.
BMAD_RANK = {"backlog": 0, "ready-for-dev": 1, "in-progress": 2, "review": 3, "done": 4}
# BMAD → beads status. `review` is a custom beads status (bootstrap sets `status.custom review:wip`).
BMAD_TO_BD = {"in-progress": "in_progress", "review": "review", "done": "closed"}
BD_RANK = {"open": 0, "in_progress": 2, "review": 3, "closed": 4}

META_STORY_KEY = "bmad_story_key"
META_EPIC_KEY = "bmad_epic_key"
META_GATE_KEY = "bmad_epic_gate"  # milestone task "Epic N complete" — tasks can only block tasks, not epics
LABEL_STORY = "story"
LABEL_EPIC = "bmad-epic"


def _slug(text: str, maxlen: int = 60) -> str:
    """Byte-for-byte the same rule sprint_plan.py uses, so keys line up."""
    slug = re.sub(r"[^\w]+", "-", str(text).lower(), flags=re.UNICODE).strip("-")
    slug = slug[:maxlen].strip("-")
    if not slug:
        slug = hashlib.sha256(str(text).encode("utf-8")).hexdigest()[:8]
    return slug


# ----------------------------------------------------------------------------
# Project discovery
# ----------------------------------------------------------------------------
def project_root(start: Path | None = None) -> Path:
    p = (start or Path.cwd()).resolve()
    for cand in [p, *p.parents]:
        if (cand / "_bmad").is_dir() or (cand / ".beads").is_dir() or (cand / ".git").exists():
            return cand
    return p


def bmm_paths(root: Path) -> tuple[Path, Path]:
    """planning_artifacts, implementation_artifacts — from _bmad/bmm/config.yaml, else defaults."""
    planning = root / "_bmad-output" / "planning-artifacts"
    impl = root / "_bmad-output" / "implementation-artifacts"
    cfg = root / "_bmad" / "bmm" / "config.yaml"
    if cfg.exists():
        for line in cfg.read_text(encoding="utf-8").splitlines():
            m = re.match(r"^\s*(planning_artifacts|implementation_artifacts)\s*:\s*[\"']?(.+?)[\"']?\s*$", line)
            if m:
                val = m.group(2).replace("{project-root}", str(root))
                if m.group(1) == "planning_artifacts":
                    planning = Path(val)
                else:
                    impl = Path(val)
    return planning, impl


def find_epics_file(planning: Path) -> Path | None:
    cands = [planning / "epics.md", *sorted(planning.glob("epic-*.md")), *sorted((planning / "epics").glob("*.md"))]
    return next((c for c in cands if c.exists()), None)


# ----------------------------------------------------------------------------
# bd wrapper
# ----------------------------------------------------------------------------
class BD:
    def __init__(self, cwd: Path, dry_run: bool = False, verbose: bool = False):
        self.cwd, self.dry_run, self.verbose = cwd, dry_run, verbose
        self.env = {**os.environ, "BD_NON_INTERACTIVE": "1"}

    def run(self, *args: str, json_out: bool = True, mutating: bool = False) -> object:
        cmd = ["bd", *args]
        if json_out:
            cmd.append("--json")
        if self.verbose or (self.dry_run and mutating):
            print(("  [dry-run] " if self.dry_run and mutating else "  $ ") + " ".join(_q(a) for a in cmd))
        if self.dry_run and mutating:
            return None
        res = subprocess.run(cmd, cwd=self.cwd, env=self.env, capture_output=True, text=True)
        if res.returncode != 0:
            raise RuntimeError(f"bd {' '.join(args)} failed: {res.stderr.strip() or res.stdout.strip()}")
        if not json_out:
            return res.stdout
        out = res.stdout.strip()
        if not out:
            return None
        data = json.loads(out)
        # Tolerate the v2 envelope ({"schema_version":1,"data":...}) announced for beads 2.0.
        if isinstance(data, dict) and "data" in data and "schema_version" in data:
            data = data["data"]
        return data

    # --- queries ---
    def list(self, **filters: str) -> list[dict]:
        args = ["list", "-n", "0"]
        for k, v in filters.items():
            args += [f"--{k.replace('_', '-')}", v]
        return self.run(*args) or []

    def ready_ids(self) -> set[str]:
        return {i["id"] for i in (self.run("ready", "--type", "task", "--label", LABEL_STORY) or [])}

    def show(self, issue_id: str) -> dict | None:
        data = self.run("show", issue_id)
        if isinstance(data, list):
            return data[0] if data else None
        return data

    # --- mutations ---
    def create(self, title: str, **kw: str) -> str | None:
        args = ["create", title]
        for k, v in kw.items():
            if v is None or v == "":
                continue
            args += [f"--{k.replace('_', '-')}", v]
        data = self.run(*args, mutating=True)
        if data is None:
            return None
        return data["id"] if isinstance(data, dict) else data[0]["id"]

    def update(self, issue_id: str, **kw: str) -> None:
        args = ["update", issue_id]
        for k, v in kw.items():
            args += [f"--{k.replace('_', '-')}", v]
        self.run(*args, mutating=True)

    def close(self, issue_id: str, reason: str) -> None:
        self.run("close", issue_id, "--reason", reason, mutating=True)

    def dep_add(self, dependent: str, blocker: str) -> None:
        self.run("dep", "add", dependent, blocker, json_out=False, mutating=True)


def _q(s: str) -> str:
    return s if re.fullmatch(r"[\w./:=,+-]+", s) else json.dumps(s)


# ----------------------------------------------------------------------------
# epics.md parsing
# ----------------------------------------------------------------------------
@dataclass
class Story:
    epic: int
    num: str
    title: str
    body: list[str] = field(default_factory=list)
    depends: list[str] = field(default_factory=list)  # "1.3" style refs

    @property
    def key(self) -> str:
        return f"{self.epic}-{self.num}-{_slug(self.title)}"

    @property
    def ref(self) -> str:
        return f"{self.epic}.{self.num}"

    def description(self) -> str:
        """The 'As a / I want / So that' block (everything before Acceptance Criteria)."""
        out = []
        for line in self.body:
            if re.match(r"^\**\s*Acceptance Criteria", line, re.IGNORECASE):
                break
            if DEPENDS_RE.match(line):
                continue
            out.append(line)
        return "\n".join(out).strip()

    def acceptance(self) -> str:
        out, on = [], False
        for line in self.body:
            if re.match(r"^\**\s*Acceptance Criteria", line, re.IGNORECASE):
                on = True
                continue
            if on:
                out.append(line)
        return "\n".join(out).strip()


@dataclass
class Epic:
    num: int
    title: str
    goal: list[str] = field(default_factory=list)
    depends: list[int] = field(default_factory=list)
    stories: list[Story] = field(default_factory=list)

    @property
    def key(self) -> str:
        return f"epic-{self.num}"


def parse_epics(path: Path) -> list[Epic]:
    epics: dict[int, Epic] = {}
    cur_epic: Epic | None = None
    cur_story: Story | None = None
    in_fence = False
    in_list = False  # "## Epic List" summary section — headings there are duplicates
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.rstrip()
        if FENCE_RE.match(line):
            in_fence = not in_fence
        if in_fence:
            if cur_story is not None:
                cur_story.body.append(line)
            continue
        if re.match(r"^##\s+Epic List\s*$", line, re.IGNORECASE):
            in_list = True
            continue
        em = EPIC_RE.match(line)
        if em and line.startswith("#"):
            n, title = int(em.group(1)), em.group(2).strip()
            # "## Epic List" holds "### Epic N:" summaries; the body uses "## Epic N:".
            # Summaries may carry a `Depends on:` line, so track the epic, but never its prose.
            if in_list and line.startswith("###"):
                cur_epic = epics.setdefault(n, Epic(n, title))
                cur_story = None
                continue
            in_list = False
            cur_epic = epics.setdefault(n, Epic(n, title))
            cur_epic.title = title
            cur_story = None
            continue
        sm = STORY_RE.match(line)
        if sm and line.startswith("#") and cur_epic is not None and not in_list:
            cur_story = Story(int(sm.group(1)), sm.group(2), sm.group(3).strip())
            cur_epic.stories.append(cur_story)
            continue
        if line.startswith("## ") and cur_epic is not None and not in_list:
            # A non-epic H2 after the epics (e.g. "## Summary") ends story capture.
            cur_story = None
            continue
        dm = DEPENDS_RE.match(line)
        if dm:
            refs = dm.group(1)
            if cur_story is not None:
                cur_story.depends += [f"{a}.{b}" for a, b in STORY_REF_RE.findall(refs)]
            elif cur_epic is not None:
                cur_epic.depends += [int(x) for x in EPIC_REF_RE.findall(refs)]
        if cur_story is not None:
            cur_story.body.append(line)
        elif cur_epic is not None and line.strip() and not in_list and not dm:
            cur_epic.goal.append(line)
    return [epics[k] for k in sorted(epics)]


# ----------------------------------------------------------------------------
# sprint-status.yaml — minimal, comment-preserving line editor
# ----------------------------------------------------------------------------
class SprintStatus:
    """Only touches `development_status:` entries and top-level scalars we own.
    Everything else (comments, action_items, ordering) is preserved verbatim."""

    KV_RE = re.compile(r"^(\s{2,})([\w-]+)\s*:\s*([\w-]+)\s*(#.*)?$")

    def __init__(self, path: Path):
        self.path = path
        self.lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
        self.changed = False

    def exists(self) -> bool:
        return bool(self.lines)

    def entries(self) -> dict[str, str]:
        out, on = {}, False
        for line in self.lines:
            if re.match(r"^development_status\s*:", line):
                on = True
                continue
            if on and line and not line.startswith(" ") and not line.startswith("#"):
                on = False
            if on:
                m = self.KV_RE.match(line)
                if m:
                    out[m.group(2)] = m.group(3)
        return out

    def set(self, key: str, value: str) -> bool:
        on = False
        for i, line in enumerate(self.lines):
            if re.match(r"^development_status\s*:", line):
                on = True
                continue
            if on and line and not line.startswith(" ") and not line.startswith("#"):
                on = False
            if on:
                m = self.KV_RE.match(line)
                if m and m.group(2) == key:
                    if m.group(3) == value:
                        return False
                    tail = f"  {m.group(4)}" if m.group(4) else ""
                    self.lines[i] = f"{m.group(1)}{key}: {value}{tail}"
                    self.changed = True
                    return True
        return False

    def set_top(self, key: str, value: str) -> None:
        for i, line in enumerate(self.lines):
            if re.match(rf"^{re.escape(key)}\s*:", line):
                new = f"{key}: {value}"
                if self.lines[i] != new:
                    self.lines[i] = new
                    self.changed = True
                return
        # insert after `generated:` if present, else at top
        idx = next((i + 1 for i, l in enumerate(self.lines) if l.startswith("generated:")), 0)
        self.lines.insert(idx, f"{key}: {value}")
        self.changed = True

    def save(self, dry_run: bool) -> None:
        if not self.changed:
            return
        self.set_top("last_updated", datetime.now().strftime("%m-%d-%Y %H:%M"))
        if dry_run:
            print(f"  [dry-run] would write {self.path}")
            return
        tmp = self.path.with_suffix(".yaml.tmp")
        tmp.write_text("\n".join(self.lines) + "\n", encoding="utf-8")
        tmp.replace(self.path)


# ----------------------------------------------------------------------------
# beads index
# ----------------------------------------------------------------------------
@dataclass
class Index:
    stories: dict[str, dict]  # bmad_story_key -> issue
    epics: dict[str, dict]  # epic-N -> issue
    gates: dict[str, dict]  # epic-N -> "Epic N complete" milestone task
    statuses: dict[str, str]  # every bead id -> status (for blocker display)


def load_index(bd: BD) -> Index:
    stories, epics, gates, statuses = {}, {}, {}, {}
    seen = set()
    for status in ("open", "in_progress", "blocked", "deferred", "review", "closed"):
        try:
            issues = bd.list(status=status)
        except RuntimeError:
            continue  # e.g. `review` not configured yet
        for issue in issues:
            if issue["id"] in seen:
                continue
            seen.add(issue["id"])
            statuses[issue["id"]] = issue.get("status", status)
            meta = issue.get("metadata") or {}
            if LABEL_STORY in (issue.get("labels") or []) and meta.get(META_STORY_KEY):
                stories[meta[META_STORY_KEY]] = issue
            if issue.get("issue_type") == "epic" and meta.get(META_EPIC_KEY):
                epics[meta[META_EPIC_KEY]] = issue
            if meta.get(META_GATE_KEY):
                gates[meta[META_GATE_KEY]] = issue
    return Index(stories, epics, gates, statuses)


def _dep_type(d: dict) -> str:
    # `bd show` expands deps as {id, dependency_type, status}; `bd list` gives raw {depends_on_id, type}.
    return d.get("dependency_type") or d.get("type") or "blocks"


def _dep_target(d: dict) -> str:
    return d.get("id") or d.get("depends_on_id") or ""


def open_blockers(issue: dict, statuses: dict[str, str] | None = None) -> list[str]:
    out = []
    for d in issue.get("dependencies") or []:
        if _dep_type(d) != "blocks":
            continue
        tid = _dep_target(d)
        st = d.get("status") or (statuses or {}).get(tid, "open")
        if st not in ("closed", "tombstone"):
            out.append(tid)
    return out


# ----------------------------------------------------------------------------
# commands
# ----------------------------------------------------------------------------
def cmd_import(args: argparse.Namespace) -> int:
    root = project_root()
    planning, _ = bmm_paths(root)
    epics_path = Path(args.epics) if args.epics else find_epics_file(planning)
    if not epics_path or not epics_path.exists():
        print(f"error: no epics file found under {planning} (pass --epics)", file=sys.stderr)
        return 1
    bd = BD(root, dry_run=args.dry_run, verbose=args.verbose)
    epics = parse_epics(epics_path)
    if not epics:
        print(f"error: no `## Epic N:` headings found in {epics_path}", file=sys.stderr)
        return 1
    idx = load_index(bd)
    created = updated = deps = 0
    story_ids: dict[str, str] = {s.key: i["id"] for s, i in ((s, idx.stories[s.key]) for e in epics for s in e.stories if s.key in idx.stories)}
    epic_ids: dict[int, str] = {int(k.split("-")[1]): v["id"] for k, v in idx.epics.items()}

    print(f"Importing {epics_path.relative_to(root)} → beads ({sum(len(e.stories) for e in epics)} stories in {len(epics)} epics)")
    for e in epics:
        title = f"Epic {e.num}: {e.title}"
        existing = idx.epics.get(e.key)
        if existing:
            if existing["title"] != title:
                bd.update(existing["id"], title=title)
                updated += 1
            eid = existing["id"]
        else:
            eid = bd.create(
                title,
                type="epic",
                priority=str(args.priority),
                description="\n".join(e.goal).strip(),
                labels=f"{LABEL_EPIC},{e.key}",
                metadata=json.dumps({META_EPIC_KEY: e.key, "bmad_epic": e.num, "source": str(epics_path.relative_to(root))}),
            ) or f"<epic-{e.num}>"
            created += 1
            print(f"  + {eid}  {title}")
        epic_ids[e.num] = eid

        for s in e.stories:
            stitle = f"Story {s.ref}: {s.title}"
            existing = idx.stories.get(s.key)
            if existing:
                sid = existing["id"]
                if existing["title"] != stitle:
                    bd.update(sid, title=stitle)
                    updated += 1
            else:
                sid = bd.create(
                    stitle,
                    type="task",
                    priority=str(args.priority),
                    parent=eid,
                    labels=f"{LABEL_STORY},{e.key}",
                    description=s.description(),
                    acceptance=s.acceptance(),
                    metadata=json.dumps({META_STORY_KEY: s.key, "bmad_epic": e.num, "bmad_story": s.num, "bmad_ref": s.ref}),
                ) or f"<{s.key}>"
                created += 1
                print(f"  + {sid}  {stitle}  [{s.key}]")
            story_ids[s.key] = sid

    # Dependencies: explicit `Depends on:` lines, optional sequential fallback.
    by_ref = {s.ref: s for e in epics for s in e.stories}
    wanted: list[tuple[str, str, str]] = []  # (dependent_id, blocker_id, why)
    for e in epics:
        prev: Story | None = None
        for s in e.stories:
            for ref in s.depends:
                if ref in by_ref:
                    wanted.append((story_ids[s.key], story_ids[by_ref[ref].key], f"{s.ref} depends on {ref}"))
                else:
                    print(f"  ! {s.ref} depends on unknown story {ref} — skipped")
            if args.deps == "sequential" and prev is not None and not s.depends:
                wanted.append((story_ids[s.key], story_ids[prev.key], f"{s.ref} follows {prev.ref} (sequential)"))
            prev = s
        for en in e.depends:
            prior = next((x for x in epics if x.num == en), None)
            if prior is None or en not in epic_ids:
                print(f"  ! Epic {e.num} depends on unknown Epic {en} — skipped")
                continue
            # beads rule: tasks can only block tasks. So an epic-level dependency goes through a
            # milestone task "Epic N complete" (blocked by every story of N); `sync` closes it.
            gate_id = _ensure_gate(bd, idx, prior, epic_ids[en], args.priority)
            for s in prior.stories:
                wanted.append((gate_id, story_ids[s.key], f"Epic {en} gate waits on {s.ref}"))
            for s in e.stories:
                wanted.append((story_ids[s.key], gate_id, f"Epic {e.num} depends on Epic {en}"))
    # existing deps (avoid duplicate adds)
    have: set[tuple[str, str]] = set()
    for issue in [*idx.stories.values(), *idx.gates.values()]:
        for d in issue.get("dependencies") or []:
            if _dep_type(d) == "blocks":
                have.add((issue["id"], _dep_target(d)))
    for dep, blocker, why in wanted:
        if (dep, blocker) in have or dep == blocker:
            continue
        try:
            bd.dep_add(dep, blocker)
            deps += 1
            print(f"  ⇢ {dep} blocked by {blocker}  ({why})")
        except RuntimeError as ex:
            print(f"  ! {why}: {ex}")
    print(f"done: {created} created, {updated} retitled, {deps} dependencies added" + ("  (dry run)" if args.dry_run else ""))
    return 0


def _ensure_gate(bd: BD, idx: Index, epic: Epic, epic_id: str, priority: int) -> str:
    g = idx.gates.get(epic.key)
    if g:
        return g["id"]
    gid = bd.create(
        f"Epic {epic.num} complete",
        type="task",
        priority=str(priority),
        parent=epic_id,
        labels=f"epic-gate,{epic.key}",
        description=f"Milestone: closes automatically (bmad_beads sync) when every story of Epic {epic.num} is closed. Other epics depend on this.",
        metadata=json.dumps({META_GATE_KEY: epic.key, "bmad_epic": epic.num}),
    ) or f"<gate-{epic.key}>"
    idx.gates[epic.key] = {"id": gid, "dependencies": []}
    print(f"  + {gid}  Epic {epic.num} complete  [milestone]")
    return gid


def cmd_sync(args: argparse.Namespace) -> int:
    root = project_root()
    _, impl = bmm_paths(root)
    status_path = Path(args.status_file) if args.status_file else impl / "sprint-status.yaml"
    bd = BD(root, dry_run=args.dry_run, verbose=args.verbose)
    ss = SprintStatus(status_path)
    if not ss.exists():
        print(f"no sprint-status.yaml at {status_path} — run /bmad-sprint-planning first; nothing to sync.")
        return 0
    idx = load_index(bd)
    entries = ss.entries()
    changes: list[str] = []

    # ---- BMAD → beads first, so milestone/epic closure and readiness see the latest state ----
    for key, yaml_status in entries.items():
        issue = idx.stories.get(key)
        if issue is None or key.startswith("epic-"):
            continue
        target = BMAD_TO_BD.get(yaml_status)
        bstat = issue.get("status", "open")
        if target and BD_RANK.get(bstat, 0) < BD_RANK[target]:
            if target == "closed":
                bd.close(issue["id"], f"BMAD sprint-status: {key} done")
            else:
                bd.update(issue["id"], status=target)
            changes.append(f"{key}: beads {bstat} → {target}")
            issue["status"] = target
            idx.statuses[issue["id"]] = target

    # Epic milestones + epic beads: close when every child story is closed (BMAD keeps its own epic-N row).
    for ekey, eissue in idx.epics.items():
        enum = (eissue.get("metadata") or {}).get("bmad_epic")
        kids = [s for s in idx.stories.values() if (s.get("metadata") or {}).get("bmad_epic") == enum]
        if not kids or not all(k.get("status") == "closed" for k in kids):
            continue
        gate = idx.gates.get(ekey)
        if gate and gate.get("status") != "closed":
            bd.close(gate["id"], "all stories of the epic closed")
            changes.append(f"{ekey}: milestone closed (all stories done)")
        if eissue.get("status") != "closed":
            bd.close(eissue["id"], "all stories closed")
            changes.append(f"{ekey}: beads epic closed (all stories done)")

    ready = bd.ready_ids()

    for key, yaml_status in entries.items():
        if key.startswith("epic-"):
            continue  # epic + retrospective rows are BMAD's
        issue = idx.stories.get(key)
        if issue is None:
            continue  # story not imported (or removed) — leave BMAD alone; doctor reports it
        bid, bstat = issue["id"], issue.get("status", "open")
        y_rank = BMAD_RANK.get(yaml_status)
        if y_rank is None:
            continue  # unknown BMAD status (e.g. awaiting-operator) — pass through

        # ---- beads → BMAD ----
        if bstat == "closed" and y_rank < BMAD_RANK["done"]:
            ss.set(key, "done") and changes.append(f"{key}: yaml {yaml_status} → done (closed in beads)")
        elif bstat == "in_progress" and y_rank < BMAD_RANK["in-progress"]:
            ss.set(key, "in-progress") and changes.append(f"{key}: yaml {yaml_status} → in-progress (claimed in beads)")
        elif bstat == "review" and y_rank < BMAD_RANK["review"]:
            ss.set(key, "review") and changes.append(f"{key}: yaml {yaml_status} → review (beads)")
        elif bstat == "open":
            is_ready = bid in ready
            if is_ready and yaml_status == "backlog":
                ss.set(key, "ready-for-dev") and changes.append(f"{key}: yaml backlog → ready-for-dev (bd ready)")
            elif not is_ready and yaml_status == "ready-for-dev":
                blockers = open_blockers(issue, idx.statuses)
                ss.set(key, "backlog") and changes.append(f"{key}: yaml ready-for-dev → backlog (blocked by {', '.join(blockers) or 'deps'})")

    # Epic rows: derived from story rows using BMAD's own rules (build lifts backlog→in-progress;
    # STATUS DEFINITIONS: done = all stories completed). Retrospective rows are never touched.
    entries = ss.entries()
    for ekey in [k for k in entries if re.fullmatch(r"epic-\d+", k)]:
        rows = [v for k, v in entries.items() if k.startswith(ekey[len("epic-"):] + "-") and re.match(r"^\d+-\d+", k)]
        if not rows:
            continue
        if all(v == "done" for v in rows) and entries[ekey] != "done":
            ss.set(ekey, "done") and changes.append(f"{ekey}: yaml → done (all stories done)")
        elif entries[ekey] == "backlog" and any(BMAD_RANK.get(v, 0) >= BMAD_RANK["in-progress"] for v in rows):
            ss.set(ekey, "in-progress") and changes.append(f"{ekey}: yaml backlog → in-progress (first story started)")

    ss.set_top("tracking_system", "beads")
    ss.save(args.dry_run)
    if changes:
        print("\n".join(f"  • {c}" for c in changes))
    print(f"sync complete: {len(changes)} change(s)" + ("  (dry run)" if args.dry_run else ""))
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    root = project_root()
    _, impl = bmm_paths(root)
    bd = BD(root)
    idx = load_index(bd)
    ready = bd.ready_ids()
    ss = SprintStatus(Path(args.status_file) if args.status_file else impl / "sprint-status.yaml")
    entries = ss.entries() if ss.exists() else {}
    rows = []
    keys = sorted(set(entries) | set(idx.stories), key=_key_sort)
    for k in keys:
        if k.startswith("epic-"):
            continue
        issue = idx.stories.get(k)
        rows.append((
            k,
            issue["id"] if issue else "—",
            entries.get(k, "—"),
            issue.get("status", "—") if issue else "—",
            ("READY" if issue and issue["id"] in ready else ("blocked:" + ",".join(open_blockers(issue, idx.statuses)) if issue and issue.get("status") == "open" else "")),
            (issue.get("assignee") or "") if issue else "",
        ))
    if args.json:
        print(json.dumps([dict(zip(("story_key", "bead", "yaml", "beads", "ready", "assignee"), r)) for r in rows], indent=2))
        return 0
    w = [max(len(str(r[i])) for r in rows + [("story_key", "bead", "yaml", "beads", "ready", "assignee")]) for i in range(6)]
    hdr = ("story_key", "bead", "yaml", "beads", "ready", "assignee")
    print("  ".join(h.ljust(w[i]) for i, h in enumerate(hdr)))
    for r in rows:
        print("  ".join(str(c).ljust(w[i]) for i, c in enumerate(r)))
    return 0


def _key_sort(k: str):
    m = re.match(r"^(\d+)-(\d+)([a-z]?)", k)
    return (int(m.group(1)), int(m.group(2)), m.group(3)) if m else (10**6, 0, k)


def cmd_doctor(args: argparse.Namespace) -> int:
    root = project_root()
    planning, impl = bmm_paths(root)
    hard = 0

    def ok(msg):
        print(f"  ✓ {msg}")

    def warn(msg):
        print(f"  ! {msg}")

    def fail(msg):
        nonlocal hard
        hard += 1
        print(f"  ✗ {msg}")

    def check(cond, good, bad, on_bad):
        ok(good) if cond else on_bad(bad)

    print(f"project: {root}")
    if shutil.which("bd"):
        ok(f"bd on PATH ({subprocess.run(['bd','version'],capture_output=True,text=True).stdout.strip()})")
    else:
        fail("bd not on PATH — brew install beads | npm i -g @beads/bd")
        return 1
    check((root / ".beads" / "config.yaml").exists(), ".beads/ initialised", ".beads/ missing — run scripts/bootstrap.sh or `bd init`", fail)
    check((root / "_bmad" / "bmm" / "config.yaml").exists(), "_bmad/ installed", "_bmad/ missing — npx bmad-method install", fail)
    bd = BD(root)
    try:
        custom = bd.run("config", "get", "status.custom", json_out=False)
        check("review" in (custom or ""), "beads custom status `review` configured", "beads lacks custom status `review` — bd config set status.custom review:wip", fail)
    except RuntimeError as ex:
        warn(f"could not read beads config: {ex}")
    settings = root / ".claude" / "settings.json"
    if settings.exists() and "bd prime" in settings.read_text(encoding="utf-8"):
        ok("Claude Code SessionStart hook → bd prime")
    else:
        warn("no `bd prime` SessionStart hook in .claude/settings.json — bd setup claude")
    for name in ("bmad-create-epics-and-stories", "bmad-sprint-planning", "bmad-build", "bmad-code-review"):
        p = root / "_bmad" / "custom" / f"{name}.toml"
        check(p.exists(), f"_bmad/custom/{name}.toml present", f"_bmad/custom/{name}.toml missing — BMAD will not call the bridge on completion", warn)
    ep = find_epics_file(planning)
    check(bool(ep), f"epics file: {ep.relative_to(root) if ep else ''}", "no epics file yet (run /bmad-create-epics-and-stories)", warn)
    ss = SprintStatus(impl / "sprint-status.yaml")
    if ss.exists():
        idx = load_index(bd)
        entries = {k: v for k, v in ss.entries().items() if not k.startswith("epic-")}
        missing = [k for k in entries if k not in idx.stories]
        orphans = [k for k in idx.stories if k not in entries]
        check(not missing, "every sprint-status story has a bead", f"{len(missing)} sprint-status stories have no bead (run import): {', '.join(missing[:5])}{'…' if len(missing)>5 else ''}", warn)
        if orphans:
            warn(f"{len(orphans)} beads not in sprint-status (renamed/removed stories?): {', '.join(orphans[:5])}")
        if ep:
            keys = {s.key for e in parse_epics(ep) for s in e.stories}
            drift = [k for k in entries if k not in keys]
            check(not drift, "sprint-status keys match epics.md", f"{len(drift)} sprint-status keys not in epics.md (retitled story? re-run sprint-planning then import): {', '.join(drift[:5])}", warn)
    else:
        warn("no sprint-status.yaml yet (run /bmad-sprint-planning)")
    print("doctor: " + ("OK" if not hard else f"{hard} hard failure(s)"))
    return 1 if hard else 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="bmad_beads", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("import", help="epics.md → beads (idempotent)")
    a.add_argument("--epics", help="path to epics.md (default: BMAD planning_artifacts)")
    a.add_argument("--deps", choices=["explicit", "sequential"], default="explicit", help="explicit: only `Depends on:` lines; sequential: also chain stories within an epic when no line is given")
    a.add_argument("--priority", type=int, default=2)
    a.add_argument("--dry-run", action="store_true")
    a.add_argument("-v", "--verbose", action="store_true")
    a.set_defaults(fn=cmd_import)
    s = sub.add_parser("sync", help="sprint-status.yaml ↔ beads (idempotent)")
    s.add_argument("--status-file")
    s.add_argument("--dry-run", action="store_true")
    s.add_argument("-v", "--verbose", action="store_true")
    s.set_defaults(fn=cmd_sync)
    t = sub.add_parser("status", help="stories × (yaml, beads, ready)")
    t.add_argument("--status-file")
    t.add_argument("--json", action="store_true")
    t.set_defaults(fn=cmd_status)
    d = sub.add_parser("doctor", help="preconditions + drift")
    d.set_defaults(fn=cmd_doctor)
    args = p.parse_args(argv)
    try:
        return args.fn(args)
    except RuntimeError as ex:
        print(f"error: {ex}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
