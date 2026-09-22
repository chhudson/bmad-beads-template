#!/usr/bin/env -S uv run --quiet --script
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Unit tests for the bridge (no `bd` required: commands run against an in-memory FakeBD).
Run: uv run scripts/test_bmad_beads.py"""
from __future__ import annotations

import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).parent))
import bmad_beads as bb  # noqa: E402

EPICS = """---
stepsCompleted: [1, 2, 3, 4]
---
# demo - Epic Breakdown

## Epic List

### Epic 1: Foundations
### Epic 2: Serving
**Depends on:** Epic 1

## Epic 1: Foundations

Goal text for epic one.

### Story 1.1: Schema exists

As a dev,
I want a schema,
So that data has a home.

**Acceptance Criteria:**

**Given** nothing
**When** migrate runs
**Then** tables exist

### Story 1.2: Seed data

**Depends on:** 1.1

As a dev,
I want seeds,
So that tests have data.

**Acceptance Criteria:**

**Given** a schema
**When** seed runs
**Then** rows exist

```
### Story 9.9: not a story (fenced)
```

## Epic 2: Serving

### Story 2.1: Read endpoint (v1)

As an analyst,
I want an endpoint,
So that I can read.

**Acceptance Criteria:**

**Given** rows **When** GET **Then** 200

## Summary

Trailing prose that is not a story.
"""

SPRINT = """# comment stays
generated: 08-30-2026 00:00
last_updated: 08-30-2026 00:00
project: demo
tracking_system: file-system
story_location: "x"

development_status:
  epic-1: backlog
  1-1-schema-exists: backlog   # inline comment
  1-2-seed-data: backlog
  epic-1-retrospective: optional
  epic-2: backlog
  2-1-read-endpoint-v1: ready-for-dev
  epic-2-retrospective: optional

action_items:
  - epic: 1
    action: "keep"
    status: open
"""


class ParserTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "epics.md"
        self.path.write_text(EPICS, encoding="utf-8")
        self.epics = bb.parse_epics(self.path)

    def tearDown(self):
        self.tmp.cleanup()

    def test_epics_and_stories(self):
        self.assertEqual([e.num for e in self.epics], [1, 2])
        self.assertEqual([s.ref for s in self.epics[0].stories], ["1.1", "1.2"])
        self.assertEqual([s.ref for s in self.epics[1].stories], ["2.1"])

    def test_keys_match_bmad_slug_rule(self):
        self.assertEqual(self.epics[0].stories[0].key, "1-1-schema-exists")
        self.assertEqual(self.epics[1].stories[0].key, "2-1-read-endpoint-v1")

    def test_dependencies(self):
        self.assertEqual(self.epics[0].stories[1].depends, ["1.1"])
        self.assertEqual(self.epics[1].depends, [1])  # from the Epic List summary

    def test_epic_list_does_not_pollute(self):
        self.assertEqual(self.epics[0].title, "Foundations")
        self.assertEqual(self.epics[0].goal, ["Goal text for epic one."])

    def test_fenced_and_trailing_sections_ignored(self):
        refs = [s.ref for e in self.epics for s in e.stories]
        self.assertNotIn("9.9", refs)

    def test_description_and_acceptance_split(self):
        s = self.epics[0].stories[1]
        self.assertTrue(s.description().startswith("As a dev,"))
        self.assertNotIn("Depends on", s.description())
        self.assertIn("**Given** a schema", s.acceptance())
        self.assertNotIn("As a dev", s.acceptance())

    def test_slug_rule(self):
        self.assertEqual(bb._slug("Two identifiers for one thing can be joined, and unjoined"),
                         "two-identifiers-for-one-thing-can-be-joined-and-unjoined")
        self.assertEqual(len(bb._slug("x" * 100)), 60)


EDGE_EPICS = """## Epic List

### Epic 1: A
### Epic 2: B
**Depends on:** Epic 1

## Epic 1: A

### Story 1.1: One

As a dev.

#### Acceptance Criteria

**Given** x **Then** y

### Story 1.2: Two

Blocked by 1.1 legal review of v1.1 wording

## Epic 2: B

**Depends on:** Epic 1

### Story 2.1: Three

**Depends on**: Epic 1, 1.2, 1.2

## Epic 3: C

**Depends on:** Epic 1

### Story 3.1: Four

## Epic 4: D

### Story 4.1: Five

**Depends on:** Epic 1
"""


class ParserEdgeCaseTests(unittest.TestCase):
    """#22."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        path = Path(self.tmp.name) / "epics.md"
        path.write_text(EDGE_EPICS, encoding="utf-8")
        self.epics = {e.num: e for e in bb.parse_epics(path)}
        self.stories = {s.ref: s for e in self.epics.values() for s in e.stories}

    def test_story_level_epic_dependency_kept(self):
        self.assertEqual(self.stories["2.1"].epic_depends, [1])

    def test_colon_required(self):
        self.assertEqual(self.stories["1.2"].depends, [])
        self.assertIn("Blocked by 1.1 legal review", self.stories["1.2"].description())

    def test_colon_after_bold_accepted_and_deduplicated(self):
        self.assertEqual(self.stories["2.1"].depends, ["1.2"])

    def test_epic_dependency_deduplicated(self):
        self.assertEqual(self.epics[2].depends, [1])  # Epic List summary + epic body

    def test_acceptance_criteria_heading(self):
        s = self.stories["1.1"]
        self.assertEqual(s.acceptance(), "**Given** x **Then** y")
        self.assertEqual(s.description(), "As a dev.")


class SprintStatusTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "sprint-status.yaml"
        self.path.write_text(SPRINT, encoding="utf-8")

    def tearDown(self):
        self.tmp.cleanup()

    def test_entries(self):
        ss = bb.SprintStatus(self.path)
        e = ss.entries()
        self.assertEqual(e["1-1-schema-exists"], "backlog")
        self.assertEqual(e["2-1-read-endpoint-v1"], "ready-for-dev")
        self.assertNotIn("action", e)  # action_items block not parsed as statuses

    def test_set_preserves_everything_else(self):
        ss = bb.SprintStatus(self.path)
        self.assertTrue(ss.set("1-1-schema-exists", "in-progress"))
        self.assertFalse(ss.set("1-1-schema-exists", "in-progress"))  # idempotent
        ss.set_top("tracking_system", "beads")
        ss.save(dry_run=False)
        text = self.path.read_text(encoding="utf-8")
        self.assertIn("# comment stays", text)
        self.assertIn("  1-1-schema-exists: in-progress  # inline comment", text)
        self.assertIn("tracking_system: beads", text)
        self.assertIn('action: "keep"', text)
        self.assertNotIn("last_updated: 08-30-2026 00:00", text)  # refreshed

    def test_unknown_key_is_noop(self):
        ss = bb.SprintStatus(self.path)
        self.assertFalse(ss.set("nope", "done"))
        self.assertFalse(ss.changed)


class BeadsToBmadTests(unittest.TestCase):
    """The beads->BMAD decision (sync's pure core), incl. the review send-back."""

    def test_forward_moves(self):
        self.assertEqual(bb.beads_to_bmad("closed", "review", False), "done")
        self.assertEqual(bb.beads_to_bmad("in_progress", "ready-for-dev", False), "in-progress")
        self.assertEqual(bb.beads_to_bmad("review", "backlog", False), "review")
        self.assertEqual(bb.beads_to_bmad("review", "ready-for-dev", False), "review")

    def test_readiness_derivation(self):
        self.assertEqual(bb.beads_to_bmad("open", "backlog", True), "ready-for-dev")
        self.assertEqual(bb.beads_to_bmad("open", "ready-for-dev", False), "backlog")
        self.assertIsNone(bb.beads_to_bmad("open", "ready-for-dev", True))
        self.assertIsNone(bb.beads_to_bmad("open", "backlog", False))

    def test_review_never_overwrites_in_progress(self):
        # Code-review send-back: yaml in-progress + bead review must NOT be
        # re-promoted to review from the beads side (issue #12).
        self.assertIsNone(bb.beads_to_bmad("review", "in-progress", False))
        self.assertIsNone(bb.beads_to_bmad("review", "review", False))

    def test_never_regresses_done(self):
        self.assertIsNone(bb.beads_to_bmad("in_progress", "done", False))
        self.assertIsNone(bb.beads_to_bmad("open", "done", True))

    def test_unknown_status_passes_through(self):
        self.assertIsNone(bb.beads_to_bmad("closed", "awaiting-operator", False))


class RankTests(unittest.TestCase):
    def test_vocab(self):
        self.assertLess(bb.BMAD_RANK["ready-for-dev"], bb.BMAD_RANK["in-progress"])
        self.assertEqual(bb.BMAD_TO_BD["done"], "closed")
        self.assertIsNone(bb.BMAD_RANK.get("awaiting-operator"))  # unknown → pass-through


# ----------------------------------------------------------------------------
# FakeBD: an in-memory stand-in for the `BD` wrapper, so the commands run without a `bd` binary.
# ----------------------------------------------------------------------------
class FakeBD:
    def __init__(self):
        self.issues: dict[str, dict] = {}
        self.calls: list[tuple] = []  # every mutation that reached the store
        self.fail_list: dict[str, str] = {}  # status -> error text its `list` raises
        self.dry_run = False
        self.actor = "me"
        self._n = 0

    # --- test setup helpers ---
    def add(self, title: str, status: str = "open", type: str = "task", labels=(), metadata=None,
            assignee: str = "", blocked_by=()) -> str:
        self._n += 1
        iid = f"bd-{self._n}"
        self.issues[iid] = {"id": iid, "title": title, "status": status, "issue_type": type,
                            "labels": list(labels), "metadata": metadata or {}, "assignee": assignee,
                            "dependencies": [{"depends_on_id": b, "type": "blocks"} for b in blocked_by]}
        return iid

    def story(self, key: str, epic: int, **kw) -> str:
        ref = ".".join(key.split("-")[:2])
        return self.add(f"Story {ref}: {key}", labels=[bb.LABEL_STORY, f"epic-{epic}"],
                        metadata={bb.META_STORY_KEY: key, "bmad_epic": epic}, **kw)

    def epic(self, num: int, **kw) -> str:
        return self.add(f"Epic {num}: E{num}", type="epic", labels=[bb.LABEL_EPIC, f"epic-{num}"],
                        metadata={bb.META_EPIC_KEY: f"epic-{num}", "bmad_epic": num}, **kw)

    def gate(self, num: int, blocked_by=(), **kw) -> str:
        return self.add(f"Epic {num} complete", labels=["epic-gate", f"epic-{num}"],
                        metadata={bb.META_GATE_KEY: f"epic-{num}", "bmad_epic": num}, blocked_by=blocked_by, **kw)

    def mutations(self, verb: str) -> list[tuple]:
        return [c for c in self.calls if c[0] == verb]

    # --- the BD interface ---
    def list(self, status: str) -> list[dict]:
        if status in self.fail_list:
            raise RuntimeError(f"bd list --status {status} failed: {self.fail_list[status]}")
        return [json.loads(json.dumps(i)) for i in self.issues.values() if i["status"] == status]

    def ready_ids(self) -> set[str]:
        return {i["id"] for i in self.issues.values()
                if i["status"] == "open" and i["issue_type"] == "task" and bb.LABEL_STORY in i["labels"]
                and all(self.issues.get(d["depends_on_id"], {}).get("status") == "closed" for d in i["dependencies"])}

    def show(self, issue_id: str) -> dict | None:
        return self.issues.get(issue_id)

    def run(self, *args, **kw):
        return ""

    def _mutate(self, *call) -> bool:
        self.calls.append(call)
        return not self.dry_run

    def create(self, title: str, **kw) -> str | None:
        if not self._mutate("create", title, kw):
            return None
        iid = self.add(title, type=kw.get("type", "task"), labels=[x for x in kw.get("labels", "").split(",") if x],
                       metadata=json.loads(kw.get("metadata") or "{}"))
        return iid

    def update(self, issue_id: str, **kw) -> None:
        if not self._mutate("update", issue_id, kw):
            return
        i = self.issues[issue_id]
        if "claim" in kw:
            i["assignee"], i["status"] = self.actor, "in_progress"
        for k in ("status", "title", "assignee"):
            if k in kw:
                i[k] = kw[k]

    def close(self, issue_id: str, reason: str) -> None:
        if self._mutate("close", issue_id, reason):
            self.issues[issue_id]["status"] = "closed"

    def reopen(self, issue_id: str, reason: str) -> None:
        if self._mutate("reopen", issue_id, reason):
            self.issues[issue_id]["status"] = "open"

    def dep_add(self, dependent: str, blocker: str) -> None:
        if self._mutate("dep_add", dependent, blocker):
            self.issues[dependent]["dependencies"].append({"depends_on_id": blocker, "type": "blocks"})


class CommandTestCase(unittest.TestCase):
    """Runs `bb.main([...])` against a FakeBD in a temp project root."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.bd = FakeBD()
        def factory(cwd, dry_run=False, verbose=False):
            self.bd.dry_run = dry_run
            return self.bd
        patches = [mock.patch.object(bb, "BD", factory), mock.patch.object(bb, "project_root", lambda: self.root)]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        self.addCleanup(self.tmp.cleanup)

    def main(self, *argv: str) -> int:
        self.out, self.err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(self.out), contextlib.redirect_stderr(self.err):
            return bb.main(list(argv))


SYNC_YAML = """development_status:
  epic-1: {e1}
  1-1-a: {s11}
  1-2-b: {s12}
  epic-1-retrospective: optional
"""


class SyncCommandTests(CommandTestCase):
    def write(self, e1="backlog", s11="backlog", s12="backlog") -> Path:
        p = self.root / "sprint-status.yaml"
        p.write_text(SYNC_YAML.format(e1=e1, s11=s11, s12=s12), encoding="utf-8")
        return p

    def sync(self, *extra: str) -> int:
        return self.main("sync", "--status-file", str(self.root / "sprint-status.yaml"), *extra)

    def yaml(self) -> dict[str, str]:
        return bb.SprintStatus(self.root / "sprint-status.yaml").entries()

    def test_forward_moves_bmad_to_beads(self):
        a = self.bd.story("1-1-a", 1)
        b = self.bd.story("1-2-b", 1)
        self.write(e1="in-progress", s11="done", s12="in-progress")
        self.assertEqual(self.sync(), 0)
        self.assertEqual(self.bd.issues[a]["status"], "closed")
        self.assertEqual(self.bd.issues[b]["status"], "in_progress")

    def test_forward_moves_beads_to_bmad(self):
        self.bd.story("1-1-a", 1)
        self.bd.story("1-2-b", 1, status="in_progress")
        self.write()
        self.sync()
        self.assertEqual(self.yaml()["1-1-a"], "ready-for-dev")
        self.assertEqual(self.yaml()["1-2-b"], "in-progress")

    def test_review_send_back(self):
        a = self.bd.story("1-1-a", 1, status="review", assignee="me")
        self.bd.story("1-2-b", 1)
        self.write(e1="in-progress", s11="in-progress")
        self.sync()
        self.assertEqual(self.bd.issues[a]["status"], "in_progress")
        self.assertEqual(self.yaml()["1-1-a"], "in-progress")

    def test_epic_milestone_and_epic_bead_close(self):
        e = self.bd.epic(1)
        a = self.bd.story("1-1-a", 1, status="closed")
        b = self.bd.story("1-2-b", 1, status="review")
        g = self.bd.gate(1, blocked_by=(a, b))
        self.write(e1="in-progress", s11="done", s12="done")
        self.sync()
        self.assertEqual(self.bd.issues[b]["status"], "closed")
        self.assertEqual(self.bd.issues[g]["status"], "closed")
        self.assertEqual(self.bd.issues[e]["status"], "closed")
        self.assertEqual(self.yaml()["epic-1"], "done")

    def test_epic_row_lifts_to_in_progress(self):
        self.bd.story("1-1-a", 1, status="in_progress")
        self.bd.story("1-2-b", 1)
        self.write()
        self.sync()
        self.assertEqual(self.yaml()["epic-1"], "in-progress")
        self.assertEqual(self.yaml()["epic-1-retrospective"], "optional")

    def test_blocked_and_deferred_beads_are_left_alone(self):
        # #21: build-auto marks a bead `blocked`; the yaml row still reads in-progress.
        a = self.bd.story("1-1-a", 1, status="blocked", assignee="me")
        b = self.bd.story("1-2-b", 1, status="deferred")
        self.write(e1="in-progress", s11="in-progress", s12="ready-for-dev")
        self.sync()
        self.assertEqual(self.bd.calls, [])
        self.assertEqual((self.bd.issues[a]["status"], self.bd.issues[b]["status"]), ("blocked", "deferred"))
        self.assertEqual(self.yaml()["1-1-a"], "in-progress")

    def test_done_still_closes_a_blocked_bead(self):
        a = self.bd.story("1-1-a", 1, status="blocked")
        self.bd.story("1-2-b", 1)
        self.write(s11="done")
        self.sync()
        self.assertEqual(self.bd.issues[a]["status"], "closed")

    def test_epic_row_reopens_when_a_story_is_added(self):
        # #23: epic-1 was done; correct-course added 1-2-b and sprint-planning gave it a row.
        self.bd.story("1-1-a", 1, status="closed")
        self.bd.story("1-2-b", 1)
        self.write(e1="done", s11="done", s12="backlog")
        self.sync()
        self.assertEqual(self.yaml()["epic-1"], "in-progress")

    def test_dry_run_writes_nothing(self):
        self.bd.story("1-1-a", 1)
        self.bd.story("1-2-b", 1)
        p = self.write(s12="done")
        before = p.read_text(encoding="utf-8")
        self.assertEqual(self.sync("--dry-run"), 0)
        self.assertEqual(p.read_text(encoding="utf-8"), before)
        self.assertTrue(all(i["status"] == "open" for i in self.bd.issues.values()))


IMPORT_EPICS = """## Epic 1: Foundations

### Story 1.1: Schema exists

As a dev.

### Story 1.2: Seed data

**Depends on:** 1.1

As a dev.

## Epic 2: Serving

**Depends on:** Epic 1

### Story 2.1: Read endpoint

As an analyst.
"""


class ImportCase(CommandTestCase):
    def setUp(self):
        super().setUp()
        self.epics = self.root / "epics.md"
        self.epics.write_text(IMPORT_EPICS, encoding="utf-8")

    def imp(self) -> int:
        return self.main("import", "--epics", str(self.epics))

    def by_title(self, title: str) -> dict:
        return next(i for i in self.bd.issues.values() if i["title"] == title)

    def blockers(self, title: str) -> set[str]:
        return {self.bd.issues[d["depends_on_id"]]["title"] for d in self.by_title(title)["dependencies"]}


class ImportCommandTests(ImportCase):
    def test_first_import(self):
        self.assertEqual(self.imp(), 0)
        self.assertEqual(len(self.bd.mutations("create")), 6)  # 2 epics, 3 stories, 1 milestone
        self.assertEqual(self.blockers("Story 1.2: Seed data"), {"Story 1.1: Schema exists"})

    def test_rerun_is_idempotent(self):
        self.imp()
        self.bd.calls.clear()
        self.assertEqual(self.imp(), 0)
        self.assertEqual(self.bd.calls, [])

    def test_retitle_updates_title_only(self):
        self.imp()
        self.bd.calls.clear()
        # Same slug (so same story key), different title text.
        self.epics.write_text(IMPORT_EPICS.replace("Schema exists", "Schema Exists!"), encoding="utf-8")
        self.imp()
        self.assertEqual(self.bd.calls, [("update", self.by_title("Story 1.1: Schema Exists!")["id"],
                                          {"title": "Story 1.1: Schema Exists!"})])

    def test_failed_list_aborts_before_creating(self):
        # #20: a failing `bd list --status open` used to be swallowed, so every open story
        # looked new and was created again.
        self.imp()
        self.bd.calls.clear()
        self.bd.fail_list["open"] = "Error: database is locked"
        self.assertEqual(self.imp(), 1)
        self.assertIn("database is locked", self.err.getvalue())
        self.assertEqual(self.bd.calls, [])

    def test_unconfigured_review_status_tolerated(self):
        self.bd.fail_list["review"] = 'Error: invalid status "review" (valid: open, in_progress, blocked, deferred, closed)'
        self.assertEqual(self.imp(), 0)

    def test_epic_dependency_goes_through_milestone(self):
        self.imp()
        self.assertEqual(self.blockers("Epic 1 complete"), {"Story 1.1: Schema exists", "Story 1.2: Seed data"})
        self.assertEqual(self.blockers("Story 2.1: Read endpoint"), {"Epic 1 complete"})


class ImportReopenTests(ImportCase):
    """#23: a story added to a finished epic re-blocks the epics that depend on it."""

    def test_new_story_reopens_milestone_and_epic(self):
        self.imp()
        for t in ("Story 1.1: Schema exists", "Story 1.2: Seed data", "Epic 1 complete", "Epic 1: Foundations"):
            self.bd.issues[self.by_title(t)["id"]]["status"] = "closed"
        self.assertIn(self.by_title("Story 2.1: Read endpoint")["id"], self.bd.ready_ids())
        self.bd.calls.clear()
        self.epics.write_text(IMPORT_EPICS.replace("## Epic 2", "### Story 1.3: Late addition\n\nAs a dev.\n\n## Epic 2"),
                              encoding="utf-8")
        self.assertEqual(self.imp(), 0)
        self.assertEqual({c[1] for c in self.bd.mutations("reopen")},
                         {self.by_title("Epic 1 complete")["id"], self.by_title("Epic 1: Foundations")["id"]})
        self.assertIn("Story 1.3: Late addition", self.blockers("Epic 1 complete"))
        self.assertNotIn(self.by_title("Story 2.1: Read endpoint")["id"], self.bd.ready_ids())
        self.assertIn("Epic 1 reopened", self.out.getvalue())

    def test_no_reopen_without_a_new_story(self):
        self.imp()
        self.bd.issues[self.by_title("Epic 1 complete")["id"]]["status"] = "closed"
        self.bd.calls.clear()
        self.imp()
        self.assertEqual(self.bd.mutations("reopen"), [])


class ImportEdgeCaseTests(CommandTestCase):
    def setUp(self):
        super().setUp()
        self.epics = self.root / "epics.md"
        self.epics.write_text(EDGE_EPICS, encoding="utf-8")
        self.assertEqual(self.main("import", "--epics", str(self.epics)), 0)
        self.ids = {i["title"]: i["id"] for i in self.bd.issues.values()}

    def test_no_edge_added_twice(self):
        edges = self.bd.mutations("dep_add")
        self.assertEqual(len(edges), len(set(edges)))

    def test_story_level_epic_dependency_goes_through_milestone(self):
        gate = self.ids["Epic 1 complete"]
        self.assertIn(("dep_add", self.ids["Story 2.1: Three"], gate), self.bd.calls)
        self.assertIn(("dep_add", self.ids["Story 3.1: Four"], gate), self.bd.calls)
        self.assertIn(("dep_add", self.ids["Story 4.1: Five"], gate), self.bd.calls)  # story-level only
        self.assertIn(("dep_add", gate, self.ids["Story 1.1: One"]), self.bd.calls)


class ClaimCommandTests(CommandTestCase):
    def claim(self, key: str = "1-1-a", *extra: str) -> int:
        return self.main("claim", key, "--actor", "me", *extra)

    def test_unknown_key_refused(self):
        self.assertEqual(self.claim("9-9-nope"), 1)

    def test_closed_refused(self):
        self.bd.story("1-1-a", 1, status="closed")
        self.assertEqual(self.claim(), 1)
        self.assertIn("already closed", self.err.getvalue())

    def test_held_by_another_refused(self):
        self.bd.story("1-1-a", 1, status="in_progress", assignee="them")
        self.assertEqual(self.claim(), 1)
        self.assertIn("'them'", self.err.getvalue())

    def test_review_refused(self):
        self.bd.story("1-1-a", 1, status="review")
        self.assertEqual(self.claim(), 1)
        self.assertIn("in review", self.err.getvalue())

    def test_blocked_refused(self):
        self.bd.story("1-1-a", 1, status="blocked")
        self.assertEqual(self.claim(), 1)
        self.assertIn("marked blocked", self.err.getvalue())

    def test_not_ready_refused(self):
        blocker = self.bd.story("1-0-z", 1)
        self.bd.story("1-1-a", 1, blocked_by=(blocker,))
        self.assertEqual(self.claim(), 1)
        self.assertIn("NOT ready", self.err.getvalue())
        self.assertEqual(self.bd.calls, [])

    def test_ready_and_unclaimed_is_claimed(self):
        a = self.bd.story("1-1-a", 1)
        self.assertEqual(self.claim(), 0)
        self.assertEqual(self.bd.mutations("update"), [("update", a, {"claim": ""})])
        self.assertEqual(self.bd.issues[a]["assignee"], "me")

    def test_resume_own_claim(self):
        self.bd.story("1-1-a", 1, status="in_progress", assignee="me")
        self.assertEqual(self.claim(), 0)
        self.assertIn("resuming", self.out.getvalue())


if __name__ == "__main__":
    unittest.main(verbosity=1)
