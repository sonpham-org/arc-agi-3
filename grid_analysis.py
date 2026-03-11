# Author: Mark Barney + Cascade (Claude Opus 4.6 thinking)
# Date: 2026-03-11 13:47
# PURPOSE: Grid analysis utilities for ARC-AGI-3 — RLE row compression (compress_row),
#   change map computation (compute_change_map), color histogram (compute_color_histogram),
#   and flood-fill region map (compute_region_map). Used by server.py prompt building and
#   prompt_builder.py. Pure Python + stdlib only — no Flask dependencies.
#   Extracted from server.py in Phase 2a.
# SRP/DRY check: Pass — all grid analysis logic consolidated here; imported by server.py and prompt_builder.py
"""Grid analysis helpers for ARC-AGI-3.

Extracted from server.py (Phase 2a).
No Flask/server dependencies — pure Python + stdlib only.
"""

from collections import deque

from constants import COLOR_NAMES


def compress_row(row: list[int]) -> str:
    """RLE-compress a single grid row into a compact string."""
    if not row:
        return ""
    parts = []
    cur, count = row[0], 1
    for v in row[1:]:
        if v == cur:
            count += 1
        else:
            parts.append(f"{cur}x{count}" if count > 1 else str(cur))
            cur, count = v, 1
    parts.append(f"{cur}x{count}" if count > 1 else str(cur))
    return " ".join(parts)


def _compress_change_row(row: str) -> str:
    """RLE-compress a change-map row string (X=changed, .=unchanged)."""
    if not row:
        return ""
    parts = []
    cur, count = row[0], 1
    for ch in row[1:]:
        if ch == cur:
            count += 1
        else:
            parts.append(f"{cur}x{count}" if count > 3 else cur * count)
            cur, count = ch, 1
    parts.append(f"{cur}x{count}" if count > 3 else cur * count)
    return "".join(parts)


def compute_change_map(prev_grid, curr_grid) -> dict:
    """Diff two grids; return changed cells and a compact change-map text."""
    if not prev_grid or not curr_grid:
        return {"changes": [], "change_count": 0, "change_map_text": ""}
    h = min(len(prev_grid), len(curr_grid))
    w = min(len(prev_grid[0]), len(curr_grid[0])) if h > 0 else 0
    changes, rows = [], []
    for y in range(h):
        row_chars = []
        for x in range(w):
            if prev_grid[y][x] != curr_grid[y][x]:
                changes.append({"x": x, "y": y, "from": prev_grid[y][x], "to": curr_grid[y][x]})
                row_chars.append("X")
            else:
                row_chars.append(".")
        row_str = "".join(row_chars)
        if "X" in row_str:
            rows.append(f"Row {y}: {_compress_change_row(row_str)}")
    return {
        "changes": changes,
        "change_count": len(changes),
        "change_map_text": "\n".join(rows) if rows else "(no changes)",
    }


def compute_color_histogram(grid: list) -> str:
    """Return a text summary of color cell counts for a grid."""
    if not grid:
        return ""
    counts: dict[int, int] = {}
    for row in grid:
        for v in row:
            counts[v] = counts.get(v, 0) + 1
    return "\n".join(
        f"  {v} ({COLOR_NAMES.get(v, '?')}): {cnt} cells"
        for v, cnt in sorted(counts.items())
    )


def compute_region_map(grid: list) -> str:
    """BFS-flood-fill to find connected regions per color; return text summary."""
    if not grid:
        return ""
    h, w = len(grid), len(grid[0])
    visited = [[False] * w for _ in range(h)]
    regions: dict[int, list] = {}
    for sy in range(h):
        for sx in range(w):
            if visited[sy][sx]:
                continue
            color = grid[sy][sx]
            queue = deque([(sy, sx)])
            visited[sy][sx] = True
            cells = []
            while queue:
                y, x = queue.popleft()
                cells.append((y, x))
                for dy, dx in ((-1, 0), (1, 0), (0, -1), (0, 1)):
                    ny, nx = y + dy, x + dx
                    if 0 <= ny < h and 0 <= nx < w and not visited[ny][nx] and grid[ny][nx] == color:
                        visited[ny][nx] = True
                        queue.append((ny, nx))
            ys = [c[0] for c in cells]
            xs = [c[1] for c in cells]
            regions.setdefault(color, []).append({
                "size": len(cells),
                "bbox": f"rows {min(ys)}-{max(ys)}, cols {min(xs)}-{max(xs)}",
            })
    lines = []
    for color in sorted(regions):
        name = COLOR_NAMES.get(color, str(color))
        top = sorted(regions[color], key=lambda r: -r["size"])[:5]
        for r in top:
            lines.append(f"  {color}={name}: {r['size']} cells at {r['bbox']}")
        if len(regions[color]) > 5:
            lines.append(f"  {color}={name}: ... ({len(regions[color]) - 5} more)")
    return "\n".join(lines)
