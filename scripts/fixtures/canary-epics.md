---
stepsCompleted: [1, 2, 3, 4]
---
# canary - Epic Breakdown

## Epic List

### Epic 1: Foundations
### Epic 2: Serving
**Depends on:** Epic 1

## Epic 1: Foundations

The data has a home.

### Story 1.1: Schema exists

As a dev,
I want a schema,
So that data has a home.

**Acceptance Criteria:**

**Given** nothing **When** migrate runs **Then** tables exist

### Story 1.2: Seed data

**Depends on:** 1.1

As a dev,
I want seeds,
So that tests have data.

**Acceptance Criteria:**

**Given** a schema **When** seed runs **Then** rows exist

## Epic 2: Serving

Analysts can read.

### Story 2.1: Read endpoint

As an analyst,
I want an endpoint,
So that I can read.

**Acceptance Criteria:**

**Given** rows **When** GET **Then** 200
