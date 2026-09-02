#!/usr/bin/env -S uv run --quiet --script
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Unit tests for the pure parts of the bridge (no `bd` required). Run: uv run scripts/test_bmad_beads.py"""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

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


if __name__ == "__main__":
    unittest.main(verbosity=1)
