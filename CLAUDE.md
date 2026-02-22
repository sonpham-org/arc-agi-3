# ARC-AGI-3 Project Instructions

## Terminology

- **"Replay"** = the share page (`share.html` / `/share/<id>` endpoint), NOT the in-app replay in `index.html`

## Reasoning View Consistency

The Reasoning view must look the same across ALL viewing modes and pages:
- **`index.html`**: live agent session, resumed session, branched session, in-app replay (all use `renderRestoredReasoning()`)
- **`share.html`**: public share/replay page (has its own rendering but must match the same grouped format)

When updating reasoning rendering in one place, update ALL others to match. Key principles:
- Steps are grouped into plan groups (LLM call + its plan followers), not shown individually
- Plan steps show as numbered action buttons; green = completed/current, unlit = pending
- Scrubber progressively lights up plan steps as you advance
- Human actions show separately in yellow
- Both pages must use the same grouping logic (check `llm_response.parsed` for plan leader, absorb followers by plan capacity)
- Branched sessions must show parent reasoning up to the branch point (trace back via `parent_session_id` / `branch_at_step`)
