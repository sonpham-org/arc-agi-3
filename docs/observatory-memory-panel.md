# Observatory Memory Panel — Design Document

**Status:** Future work
**Date:** 2026-03-12

## Overview

Split the Observatory's Reasoning Log area into two side-by-side panels:

- **Left — Reasoning Log**: The existing LLM call / plan / action display (unchanged).
- **Right — Memory Panel**: A structured view of the agent's accumulated variables and knowledge at the currently-viewed step.

The memory is **computed, not stored** — the execution log is replayed to derive what the agent "knew" at any given step, rather than snapshotting memory at every step.

## Motivation

During autoplay and replay, the reasoning log shows *what the agent did* but not *what it knows*. The memory panel closes this gap by showing the accumulated state — REPL variables, discovered rules, observations, compact summaries — at each point in the session. This makes it possible to understand the agent's decision-making context without digging through sub-call details.

## What "Memory" Means Per Scaffolding Type

| Scaffolding | Memory State |
|-------------|-------------|
| **Linear / Linear-Interrupt** | `observations[]` (accumulated), `compactSummary` (LLM-generated knowledge), `hardMemory` (user prompt) |
| **RLM** | REPL namespace variables (Python dict from Pyodide execution), sub-call results |
| **Three-System / Two-System** | `rules_doc` (discovered game rules, versioned), `observations[]`, grid snapshots |
| **Agent Spawn** | `facts[]`, `hypotheses[]`, `observations[]`, agent action log |

RLM is the richest case — actual Python variables evolving over time. The others are more declarative (append-only lists, versioned text).

## Architecture: `MemoryStateTracker`

A state machine per scaffolding type that processes step entries sequentially to produce a memory snapshot.

```
MemoryStateTracker
  ├── constructor(scaffoldingType)
  ├── processStep(stepEntry)   // updates internal state from one step's llm_response
  ├── getSnapshot() → {}       // returns current variables/knowledge for rendering
  └── reset()                  // back to initial state
```

### Scrubbing to step N

```
tracker.reset()
for i = 0..N:
  tracker.processStep(steps[i])
renderMemoryPanel(tracker.getSnapshot())
```

### Live autoplay

Each new step calls `processStep()` incrementally — no replay needed.

### RLM variable extraction

Each step's `llm_response.rlm.log[]` contains the REPL iterations (code + stdout). Two approaches:

1. **Output parsing (recommended default)** — Extract variable state from `SHOW_VARS()` output already captured in iteration logs. Cheap, usually sufficient.
2. **Pyodide replay (optional full-fidelity mode)** — Re-execute the actual code in an isolated Pyodide namespace. Accurate but heavier. Reserved for cases where parsed output is insufficient.

### Non-REPL scaffoldings

For Linear and Three-System, the tracker accumulates observations and tracks text summaries (compact summary or rules_doc). The state changes are well-structured and declarative — no code replay needed.

## Performance: Incremental Replay with Checkpoint Caching

Replaying from step 0 on every scrub position change is wasteful. Instead:

- **Cache the tracker state at the current position.**
- **Scrub forward**: Continue from cache (process only new steps).
- **Scrub backward**: Replay from beginning or nearest cached checkpoint.
- **Periodic checkpoints**: Every ~20 steps, snapshot the tracker state so backward scrub costs at most 20 step replays.

This makes scrubbing feel instant even on 200+ step sessions.

## DOM / CSS Changes

In `.obs-reasoning-wrap`, replace the single-column layout with a side-by-side split:

```
.obs-reasoning-wrap (existing container)
  ├── .obs-reasoning-log  (left ~55%, scrollable — existing content moves here)
  └── .obs-memory-panel   (right ~45%, scrollable — new)
       ├── h4 "Agent Memory"
       ├── .memory-section "Variables"     (RLM: name/type/value table)
       ├── .memory-section "Knowledge"     (compact summary or rules_doc text)
       └── .memory-section "Observations"  (accumulated observation list)
```

The memory panel re-renders whenever:

1. A new step executes (live autoplay).
2. The scrubber position changes.
3. The user clicks a reasoning entry.

## Files to Change

| File | Change |
|------|--------|
| `templates/index.html` | Split `.obs-reasoning-wrap` into two-column layout |
| `static/css/main.css` | Flexbox for the split, memory panel styling |
| **New:** `static/js/observatory/obs-memory.js` | `MemoryStateTracker` class + render function |
| `static/js/observatory/obs-lifecycle.js` | Initialize tracker on enter, wire to reasoning sync |
| `static/js/observatory/obs-scrubber.js` | Call tracker on scrub position change |
| `static/js/observatory.js` | Feed new steps to tracker during live autoplay |
| `static/js/share-page.js` | Same split for replay page consistency |

`static/js/reasoning.js` is **unchanged** — log rendering stays the same.

## Open Questions

1. **Share page scope** — Should `share.html` get the same memory panel, or is this Observatory-only initially?
2. **Settings view** — Should the Reasoning tab in the settings right-panel also get a memory column, or only the Observatory view?
3. **RLM fidelity** — Is `SHOW_VARS()` parsing sufficient for the default experience, or is Pyodide replay needed from day one?
4. **Memory panel sections** — Should sections (Variables, Knowledge, Observations) be collapsible `<details>` elements, or always visible?
