# Quality check plan — pre-launch bug sweep

**Goal**: Eliminate bugs causing high bounce rate before the Arc challenge launch.

---

## Bug log

| Id | Priority | Location | Description | Status |
|----|----------|----------|-------------|--------|
| | | | | |

*Bugs will be logged here as they are found.*

---

## Phase 1: Bug catalog

Systematic audit of all code and user flows. For each bug found, record:
- **Id**: Bug-001, Bug-002, etc.
- **Priority**: P0 (blocker), P1 (annoying), P2 (cosmetic)
- **Location**: file + line number
- **Repro**: steps to trigger
- **Description**: what goes wrong

### Audit targets

| Area | Files | What to check |
|------|-------|---------------|
| First load | `index.html` | Blank screens, js errors, missing assets, flash of unstyled content |
| Game flow | `index.html`, `server.py` | Start game → play → complete. Every button works. |
| Llm agent | `server.py`, `agent.py`, `config.yaml` | Agent calls, error handling, streaming, timeouts |
| Share/replay | `share.html`, `server.py` | Load shared session, scrubber, reasoning view |
| Mobile | `index.html`, `share.html` | Layout breaks, touch targets, overflow, scrolling |
| Api routes | `server.py` | Every endpoint — bad input, missing params, error responses |
| State management | `index.html` | Undo, redo, branch, resume, refresh mid-game |
| Cross-browser | All frontend | Chrome, Firefox, Safari (desktop + mobile) |

---

## Phase 2: Triage

Sort bug list by priority:
- **P0** — Blocks core gameplay or causes visible breakage (fix immediately)
- **P1** — Functional issue with workaround (fix before launch)
- **P2** — Cosmetic or edge case (fix if time permits)

---

## Phase 3: Fix

Work through bugs P0 → P1 → P2:
1. Fix the bug
2. Verify the fix
3. Check for regressions in related features
4. Commit to staging

---

## Phase 4: Regression pass

Full end-to-end walkthrough after all fixes:
- [ ] Fresh visit (incognito, no cache)
- [ ] Pick environment, start game
- [ ] Play manually (all interaction types)
- [ ] Run llm agent, watch reasoning
- [ ] Undo/redo/branch
- [ ] Share a session, open share link
- [ ] Replay shared session with scrubber
- [ ] Mobile (iOS Safari, Android Chrome)
- [ ] Slow network (3G throttle)
- [ ] Refresh mid-game, back button, deep link
