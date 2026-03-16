# AutoResearch Arena Redesign Plan

**Date:** 2026-03-14
**Author:** Claude Opus 4.6

## Scope

**In:**
- Rename page from "Agent vs Agent" → "AutoResearch Arena"
- New logo: two blocks facing each other with alternating turn-by-turn pulse animation
- Full-screen layout (remove max-width constraints on game selection)
- Split game selection view: left side = Agent A harness/settings, right side = Agent B harness/settings, center = game preview
- Each agent side has its own settings panel (strategy, config) that transitions into an observability panel (reasoning log) during match playback
- Observatory view keeps the split layout: left = Agent A log, center = game canvas + scrubber, right = Agent B log

**Out:**
- LLM-based AI agents (future work — current built-in strategies remain)
- Server-side changes beyond the route (already done)
- New games (Snake Battle stays as the demo)

## Architecture

**Files touched:**
- `templates/arena.html` — Restructure layout, new logo SVG, rename
- `static/css/arena.css` — Full-screen styles, split selection view, settings panels
- `static/js/arena.js` — Add file header, update view logic for split selection

**No new files needed.** All changes are to existing arena files.

## Logo Design

Two 4x4 blocks facing each other with inner 2x2 detail, connected by dashes. Both sides same color (accent blue). Alternating pulse animation — left block pulses on even beats, right on odd beats, simulating turn-by-turn play.

```
┌──┐          ┌──┐
│OO│ ── ── ── │OO│
│OO│ ── ── ── │OO│
└──┘          └──┘
```

SVG: Two `<rect>` outer frames + two `<rect>` inner fills + three small connector dots/dashes. Alternating `<animate>` on opacity with offset timing.

## TODOs

1. Update logo SVG in `arena.html` — two-block design with alternating pulse
2. Rename all "Agent vs Agent" references → "AutoResearch Arena"
3. Redesign game selection view:
   - Left panel: Agent A settings (strategy picker, name)
   - Center: Game card/preview + "Start Match" button
   - Right panel: Agent B settings (strategy picker, name)
   - Full-screen width, no max-width container
4. Update observatory view to full-screen width
5. Add file headers to all three arena files
6. Verify: load page, check logo animation, check split selection, run a match, verify scrubber + logs still work

## Docs / Changelog

- Add CHANGELOG.md entry for the arena redesign
