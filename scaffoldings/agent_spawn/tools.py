"""Tools and helpers for agent_spawn scaffolding — frame wrappers, grid formatting, frame tools."""

from arcengine import GameAction

from agent import ACTION_NAMES
from grid_analysis import compress_row, compute_change_map


# ═══════════════════════════════════════════════════════════════════════════
# COLOR NAME MAP
# ═══════════════════════════════════════════════════════════════════════════

COLOR_NAMES = {
    0: "White", 1: "LightGray", 2: "Gray", 3: "DarkGray",
    4: "VeryDarkGray", 5: "Black", 6: "Magenta", 7: "LightMagenta",
    8: "Red", 9: "Blue", 10: "LightBlue", 11: "Yellow",
    12: "Orange", 13: "Maroon", 14: "Green", 15: "Purple",
}


# ═══════════════════════════════════════════════════════════════════════════
# EXISTING HELPERS (unchanged API)
# ═══════════════════════════════════════════════════════════════════════════

def format_grid(grid: list) -> str:
    """Format a grid for LLM consumption using RLE compression."""
    if not grid:
        return "(empty)"
    lines = []
    for i, row in enumerate(grid):
        lines.append(f"  Row {i:2d}: {compress_row(row)}")
    if len(lines) > 40:
        lines = lines[:20] + [f"  ... ({len(lines) - 40} more rows)"] + lines[-20:]
    return "\n".join(lines)


def format_change_map(prev_grid: list | None, grid: list) -> str:
    """Format the change map between two grids."""
    if prev_grid is None:
        return "(first observation)"
    cm = compute_change_map(prev_grid, grid)
    return cm if cm else "(no change)"


def format_history(history: list, max_entries: int = 15) -> str:
    """Format recent history for prompt injection."""
    if not history:
        return "(no history)"
    recent = history[-max_entries:]
    lines = []
    for h in recent:
        aname = ACTION_NAMES.get(h.get("action", -1), "?")
        lines.append(
            f"  Step {h['step']}: {aname} -> state={h.get('state', '?')} "
            f"lvl={h.get('levels', '?')} | {h.get('observation', '')[:80]}"
        )
    return "\n".join(lines)


def validate_action(action_id: int, available_actions: list) -> int:
    """Ensure action_id is valid, fallback to first available."""
    if action_id in available_actions:
        return action_id
    return available_actions[0] if available_actions else 1


def make_game_action(action_id: int) -> GameAction:
    """Convert int action_id to GameAction enum, with fallback."""
    try:
        return GameAction.from_id(int(action_id))
    except (ValueError, KeyError):
        return GameAction.ACTION1


# ═══════════════════════════════════════════════════════════════════════════
# FRAME TOOLS (free analysis tools for subagents)
# ═══════════════════════════════════════════════════════════════════════════

def as_render_grid(grid: list) -> str:
    """Text render with numbered rows, each row as space-separated color names or RLE."""
    if not grid:
        return "(empty grid)"
    lines = []
    for i, row in enumerate(grid):
        color_names = [COLOR_NAMES.get(c, str(c)) for c in row]
        # RLE compress color names
        if not color_names:
            lines.append(f"  Row {i:2d}: (empty)")
            continue
        parts = []
        run_color = color_names[0]
        run_len = 1
        for cn in color_names[1:]:
            if cn == run_color:
                run_len += 1
            else:
                parts.append(f"{run_len}x{run_color}" if run_len >= 3 else " ".join([run_color] * run_len))
                run_color = cn
                run_len = 1
        parts.append(f"{run_len}x{run_color}" if run_len >= 3 else " ".join([run_color] * run_len))
        lines.append(f"  Row {i:2d}: {' '.join(parts)}")
    return "\n".join(lines)


def as_find(grid: list, *colors) -> list:
    """Returns list of (row, col) positions for each matching color value."""
    results = []
    for r, row in enumerate(grid):
        for c, val in enumerate(row):
            if val in colors:
                results.append((r, c))
    return results


def as_bounding_box(grid: list, *colors) -> dict:
    """Returns tight bounding box {min_row, max_row, min_col, max_col} for given colors."""
    positions = as_find(grid, *colors)
    if not positions:
        return {"min_row": -1, "max_row": -1, "min_col": -1, "max_col": -1}
    rows = [p[0] for p in positions]
    cols = [p[1] for p in positions]
    return {
        "min_row": min(rows),
        "max_row": max(rows),
        "min_col": min(cols),
        "max_col": max(cols),
    }


def as_color_counts(grid: list) -> dict:
    """Color histogram — dict mapping each color present to its cell count."""
    counts = {}
    for row in grid:
        for val in row:
            name = COLOR_NAMES.get(val, str(val))
            counts[name] = counts.get(name, 0) + 1
    return counts


def as_diff_frames(old_grid: list, new_grid: list) -> str:
    """Region-grouped diff between old and new grid — shows what changed and where."""
    if not old_grid or not new_grid:
        return "(cannot diff: missing grid)"
    changes = []
    for r in range(min(len(old_grid), len(new_grid))):
        old_row = old_grid[r]
        new_row = new_grid[r]
        for c in range(min(len(old_row), len(new_row))):
            if old_row[c] != new_row[c]:
                old_name = COLOR_NAMES.get(old_row[c], str(old_row[c]))
                new_name = COLOR_NAMES.get(new_row[c], str(new_row[c]))
                changes.append((r, c, old_name, new_name))

    if not changes:
        return "(no changes)"

    # Group by contiguous regions
    lines = [f"Total: {len(changes)} cells changed"]
    # Group by row for readability
    current_row = -1
    for r, c, old_name, new_name in changes:
        if r != current_row:
            current_row = r
            lines.append(f"  Row {r}:")
        lines.append(f"    col {c}: {old_name} -> {new_name}")

    # Truncate if too many changes
    if len(lines) > 60:
        lines = lines[:30] + [f"  ... ({len(changes)} total changes, truncated)"] + lines[-10:]

    return "\n".join(lines)


def as_change_summary(old_grid: list, new_grid: list) -> str:
    """One-line summary of changes: 'N cells changed in rows R1-R2, cols C1-C2'."""
    if not old_grid or not new_grid:
        return "(cannot summarize: missing grid)"
    changed_rows = set()
    changed_cols = set()
    count = 0
    for r in range(min(len(old_grid), len(new_grid))):
        old_row = old_grid[r]
        new_row = new_grid[r]
        for c in range(min(len(old_row), len(new_row))):
            if old_row[c] != new_row[c]:
                count += 1
                changed_rows.add(r)
                changed_cols.add(c)
    if count == 0:
        return "No cells changed."
    return (f"{count} cells changed in rows {min(changed_rows)}-{max(changed_rows)}, "
            f"cols {min(changed_cols)}-{max(changed_cols)}")


def as_dispatch_frame_tool(tool_name: str, grid: list, prev_grid: list | None, args: dict | None) -> str:
    """Dispatcher: calls the right frame tool function based on tool name string.

    Returns the result as a string suitable for prompt injection.
    """
    args = args or {}

    if tool_name == "render_grid":
        return as_render_grid(grid)

    elif tool_name == "diff_frames":
        if prev_grid is None:
            return "(no previous grid to diff against)"
        return as_diff_frames(prev_grid, grid)

    elif tool_name == "change_summary":
        if prev_grid is None:
            return "(no previous grid to compare)"
        return as_change_summary(prev_grid, grid)

    elif tool_name == "find_colors":
        colors = args.get("colors", [])
        if not colors:
            return "(no colors specified — use args: {\"colors\": [1, 2]})"
        positions = as_find(grid, *colors)
        if not positions:
            return f"No cells found with colors {colors}"
        lines = [f"Found {len(positions)} cells with colors {colors}:"]
        for r, c in positions[:100]:
            lines.append(f"  ({r}, {c})")
        if len(positions) > 100:
            lines.append(f"  ... ({len(positions)} total, truncated)")
        return "\n".join(lines)

    elif tool_name == "bounding_box":
        colors = args.get("colors", [])
        if not colors:
            return "(no colors specified — use args: {\"colors\": [1, 2]})"
        bb = as_bounding_box(grid, *colors)
        if bb["min_row"] == -1:
            return f"No cells found with colors {colors}"
        return (f"Bounding box for colors {colors}: "
                f"rows {bb['min_row']}-{bb['max_row']}, cols {bb['min_col']}-{bb['max_col']}")

    elif tool_name == "color_counts":
        counts = as_color_counts(grid)
        lines = ["Color counts:"]
        for name, cnt in sorted(counts.items(), key=lambda x: -x[1]):
            lines.append(f"  {name}: {cnt}")
        return "\n".join(lines)

    else:
        return f"(unknown frame tool: {tool_name})"
