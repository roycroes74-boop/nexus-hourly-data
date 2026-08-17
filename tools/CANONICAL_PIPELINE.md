# CANONICAL PIPELINE v1.0.0 — reference document

**Status: FROZEN.** Config hash `2961beb4`, built on frozen core EVENING-REPORT-LITE v1.1.0 (`9624bb9e`).
Reproducibility gate: `python3 tools/canonical_check.py` from repo root — must print `RESEARCH ENVIRONMENT = REPRODUCIBLE`. If any number moves: STOP.

## Components and frozen definitions

**Core (evening_lite v1.1.0 — untouched):**
- Zigzag turning points: 2.5pt reversal on nexus_state mid.
- Brick locations: wall ≥ max(50, 4× trailing-hour median level size), qualified by ≥3 sampled snapshots within 5 min; zone half-width 0.25.
- Episodes (frozen definition): start at tolerance entry (0.50pt from location center), brief exits = same test, end only ≥1.50pt from center; outcome HOLD/BREAK by departure side vs wall side.

**Canonical additions (this module):**
- Chain engine: NEXUS market_state_id series bucketed per 10s; a chain FIRES when ≥3 distinct active states (ids 2–7) were seen within the trailing 10-minute window AND the current state is an absorption state (4 or 5); firing closes the window (re-arm required).
- Recall/precision (unified matching, frozen): a turning point is covered when a fire lies within [−10 min, +5 min] of the TP and |fire mid − TP price| ≤ tolerance. Primary tolerance 0.50pt, strict sensitivity 0.25pt. Precision = matched fires / all fires. Greedy first-match, each fire used once.
- Day report: integrity chapter (snapshots, crossed, DQ median) + behaviour chapter (TPs, bricks, episodes, HOLD%) + chain chapter (fires, recall, precision), with a configurable behaviour window so held-out periods stay untouched.

## Frozen fixture values (2026-08-13)

Core gate (file 10h00–12h00): 10,421 trades · 25,076 book snapshots · 14,144 states · 2,383 events · 7,074 memory · 8 TPs · source SHA-256 pinned.
Canonical gate (00–12h): 34 TPs · 18 brick locations · 181 episodes (181 closed, 99 HOLD) · 67 chain fires · recall 0.3235 primary / 0.1176 strict · precision 0.1642.

## Continuity statement (honest)

The chain engine is a **reimplementation** of the documented semantics. The original pre-reset engines were lost; their historical chain numbers (e.g. Day 0 recall figures reported before 2026-08-15) are **not 1:1 comparable** to this version and must not be mixed in tables. From this version forward the fixture is the single source of truth; any change to definitions requires a new version + hash + fixture refresh, reported explicitly.

## Environment

Python 3 stdlib only (no external dependencies — the dependency lock is the interpreter itself). Run from repo root. Data expected under `full-tick-data/YYYY-MM-DD/`. Version pinning: every output carries engine name, version and config hash.
