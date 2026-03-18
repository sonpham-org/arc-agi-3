# Author: Claude Opus 4.6
# Date: 2026-03-18 15:00
# PURPOSE: Server-side arena heartbeat — runs evolution + tournament for multiple games.
#   Supports snake (classic + random maps + royale + 2v2), chess960, othello.
#   Game engines dispatched via _ACTIVE_GAMES.
#   Uses ARENA_CLAUDE_KEY env var (Anthropic API key or OAuth token) for agent evolution.
#   Uses server/arena_tool_runner.py for LLM tool-calling loops (no external deps).
#   Tournament: single thread round-robins all games (prevents SQLite corruption).
#   Evolution: one thread per game (LLM-bound, mostly idle waiting on API).
#   Chess960 uses random position each match (time-seeded for true randomization).
#   Program.md versioning: dated files per game, tracked via program_file on agents.
#   Import sandbox: blocklist-based (not allowlist). Missing libraries logged to
#   arena_library_requests table for monitoring. Agents can use any non-blocked package.
#   Monitor via /api/arena/heartbeat/status endpoint.
# SRP/DRY check: Pass — reuses existing db_arena functions, game engines, arena_tool_runner

import json
import math
import os
import random
import re
import sys
import threading
import time
import traceback

# Bundled snake engine and seeds live in server/
_SERVER_DIR = os.path.dirname(os.path.abspath(__file__))
_SEEDS_DIR = os.path.join(_SERVER_DIR, 'arena_seeds')

from db_arena import (
    arena_submit_agent,
    arena_record_game,
    arena_get_program,
    arena_get_leaderboard,
    arena_get_agent,
    arena_get_agent_by_name,
    arena_get_agent_games,
    arena_get_game,
    arena_get_recent_games,
    arena_get_recent_games_with_history,
    arena_increment_generation,
    arena_update_elo,
    arena_count_pair_games,
    arena_post_comment,
    arena_strip_excess_history,
    MAX_STORED_GAMES_PER_PAIR,
    _db,
)


# ═══════════════════════════════════════════════════════════════════════════
#   Config
# ═══════════════════════════════════════════════════════════════════════════

HEARTBEAT_INTERVAL_FAST_FILL = 6 * 60   # 6 minutes per game until 100 agents
HEARTBEAT_INTERVAL_NORMAL = 6 * 60     # 6 minutes per game steady state
HEARTBEAT_INTERVAL_FAST = 6 * 60       # 6 minutes (same — haiku is cheap)
EVOLUTION_STAGGER_SECS = 60            # offset between per-game threads to avoid burst
EVOLUTION_ENABLED = os.environ.get('ARENA_EVOLUTION_ENABLED', '').lower() in ('1', 'true', 'yes')
TOURNAMENT_GAMES_PER_TICK = 20
EVOLUTION_AGENTS_PER_TICK = 1
MAX_TOOL_ROUNDS = 6
ELO_START = 1000.0
ELO_K = 32
ANALYSIS_EVERY_N_EVOS = 10  # post AI analysis comment every N evolutions per game

# Agent evolution model rotation: 3 haiku, 1 sonnet, 1 opus, 1 gemini
# (model_id, label, provider)
_EVOLUTION_MODELS = [
    ('claude-haiku-4-5-20251001', 'claude-haiku-4.5', 'anthropic'),
    ('claude-haiku-4-5-20251001', 'claude-haiku-4.5', 'anthropic'),
    ('claude-haiku-4-5-20251001', 'claude-haiku-4.5', 'anthropic'),
    ('claude-sonnet-4-6', 'claude-sonnet-4.6', 'anthropic'),
    ('claude-opus-4-6', 'claude-opus-4.6', 'anthropic'),
    ('gemini-3.1-pro-preview', 'gemini-3.1-pro', 'gemini'),
]

# Heartbeat state (for monitoring)
_heartbeat_state = {
    'running': False,
    'last_tick': None,
    'last_error': None,
    'ticks': 0,
    'last_comment_check': 0,
    'agents_created': 0,
    'games_played': 0,
    'thread': None,
}

# Ring buffer of recent matches for live tournament canvases.
# Kept in-memory only — no DB bloat. Max 4 entries.
_LIVE_BUFFER_SIZE = 12  # 4 per game × 3 games
_live_matches = []
_live_lock = threading.Lock()


# ═══════════════════════════════════════════════════════════════════════════
#   Default Program.md
# ═══════════════════════════════════════════════════════════════════════════

_GAME_PROGRAM_FILES = {
    'snake': 'default_program.md',
    'snake_random': 'snake_random_program.md',
    'snake_royale': 'snake_royale_program.md',
    'snake_2v2': 'snake_2v2_program.md',
    'chess960': 'chess960_program.md',
    'othello': 'othello_program.md',
}

_GAME_PROGRAM_FALLBACKS = {
    'snake': "Create snake agents with a get_move(state) function.",
    'snake_random': "Create snake agents with a get_move(state) function. state['walls'] contains wall positions.",
    'snake_royale': "Create 4-player snake agents with a get_move(state) function. state['snakes'] has all 4 snakes.",
    'snake_2v2': "Create 2v2 team snake agents with a get_move(state) function. state['ally_snake'] and state['enemies'] available.",
    'chess960': "Create chess960 agents with a get_move(state) function that returns a legal move string.",
    'othello': "Create othello agents with a get_move(state) function that returns [row, col].",
}


def _load_default_program(game_id='snake'):
    """Load default program.md from bundled seeds for the given game.

    Always reads the latest dated version (e.g. snake_random_program-2026-03-17.md)
    so that the LLM prompt matches the filename stored in arena_agents.program_file.
    Falls back to base filename if no dated version exists.
    """
    # Use the resolved filename (latest dated version) so LLM sees what DB records
    filename = _resolve_program_file(game_id)
    path = os.path.join(_SEEDS_DIR, filename)
    if os.path.exists(path):
        with open(path) as f:
            return f.read()
    # Final fallback to base file
    base = _GAME_PROGRAM_FILES.get(game_id, 'default_program.md')
    base_path = os.path.join(_SEEDS_DIR, base)
    if os.path.exists(base_path):
        with open(base_path) as f:
            return f.read()
    return _GAME_PROGRAM_FALLBACKS.get(game_id, "Create agents with a get_move(state) function.")


def _resolve_program_file(game_id='snake'):
    """Resolve the actual program file used for a game_id.

    Checks for a dated version first (e.g. snake_random_program-2026-03-17.md),
    falling back to the base filename. Returns the filename (not full path).
    """
    import glob as _glob
    base = _GAME_PROGRAM_FILES.get(game_id, 'default_program.md')
    stem = base.rsplit('.', 1)[0]  # e.g. 'snake_random_program'

    # Find all dated versions, pick the latest
    pattern = os.path.join(_SEEDS_DIR, f'{stem}-*.md')
    dated = sorted(_glob.glob(pattern))
    if dated:
        return os.path.basename(dated[-1])
    return base


# ═══════════════════════════════════════════════════════════════════════════
#   Game Engines
# ═══════════════════════════════════════════════════════════════════════════

try:
    from server.snake_engine import SnakeGame as _SnakeGameBase
    from server.snake_engine import SnakeRandomGame as _SnakeRandomGameBase
    from server.snake_engine import SnakeGame4P as _SnakeGame4PBase
    _HAS_SNAKE_ENGINE = True
except ImportError:
    _HAS_SNAKE_ENGINE = False
    _SnakeGameBase = None
    _SnakeRandomGameBase = None
    _SnakeGame4PBase = None

try:
    from server.chess960_engine import Chess960Game as _Chess960GameBase
    _HAS_CHESS960_ENGINE = True
except ImportError:
    _HAS_CHESS960_ENGINE = False
    _Chess960GameBase = None

try:
    from server.othello_engine import OthelloGame as _OthelloGameBase
    _HAS_OTHELLO_ENGINE = True
except ImportError:
    _HAS_OTHELLO_ENGINE = False
    _OthelloGameBase = None

# Active arena games — both tournament + evolution loops iterate these
_ACTIVE_GAMES = ['snake', 'snake_random', 'snake_royale', 'snake_2v2', 'chess960', 'othello']


def _run_snake_match(code_a, code_b):
    """Run a headless snake match. Uses engine defaults: 20x20, 350 turns, 8 food.
    Returns winner/turns/scores/history."""
    if not _HAS_SNAKE_ENGINE:
        return {'winner': None, 'turns': 0, 'scores': [3, 3], 'history': [], 'error': 'No snake engine'}

    fn_a = _load_agent_fn(code_a)
    fn_b = _load_agent_fn(code_b)
    if not fn_a or not fn_b:
        return {'winner': None, 'turns': 0, 'scores': [3, 3], 'history': [], 'error': 'Agent load failed'}

    game = _SnakeGameBase()  # defaults: 20x20, 350 turns, 8 food
    try:
        result = game.run(fn_a, fn_b)
        return {
            'winner': result['winner'],
            'turns': result['turns'],
            'scores': result['scores'],
            'history': result.get('history', []),
        }
    except Exception as exc:
        return {'winner': None, 'turns': 0, 'scores': [3, 3], 'history': [], 'error': str(exc)}


def _run_chess960_match(code_a, code_b):
    """Run a headless Chess960 match. Random position each game (time-seeded).
    Returns winner/turns/scores/history."""
    if not _HAS_CHESS960_ENGINE:
        return {'winner': None, 'turns': 0, 'scores': [0, 0], 'history': [], 'error': 'No chess960 engine'}

    fn_a = _load_agent_fn(code_a)
    fn_b = _load_agent_fn(code_b)
    if not fn_a or not fn_b:
        return {'winner': None, 'turns': 0, 'scores': [0, 0], 'history': [], 'error': 'Agent load failed'}

    # Random Fischer Random position — seeded from time for true randomization
    position_id = int(time.time() * 1000000) % 960
    game = _Chess960GameBase(position_id=position_id)
    try:
        result = game.run(fn_a, fn_b)
        return {
            'winner': result['winner'],
            'turns': result['turns'],
            'scores': result['scores'],
            'history': result.get('history', []),
        }
    except Exception as exc:
        return {'winner': None, 'turns': 0, 'scores': [0, 0], 'history': [], 'error': str(exc)}


def _run_othello_match(code_a, code_b):
    """Run a headless Othello match. Returns winner/turns/scores/history."""
    if not _HAS_OTHELLO_ENGINE:
        return {'winner': None, 'turns': 0, 'scores': [2, 2], 'history': [], 'error': 'No othello engine'}

    fn_a = _load_agent_fn(code_a)
    fn_b = _load_agent_fn(code_b)
    if not fn_a or not fn_b:
        return {'winner': None, 'turns': 0, 'scores': [2, 2], 'history': [], 'error': 'Agent load failed'}

    game = _OthelloGameBase()
    try:
        result = game.run(fn_a, fn_b)
        return {
            'winner': result['winner'],
            'turns': result['turns'],
            'scores': result['scores'],
            'history': result.get('history', []),
        }
    except Exception as exc:
        return {'winner': None, 'turns': 0, 'scores': [2, 2], 'history': [], 'error': str(exc)}


def _run_snake_random_match(code_a, code_b):
    """Run a headless snake random-maps match. New seed per match.
    Returns winner/turns/scores/history."""
    if not _HAS_SNAKE_ENGINE:
        return {'winner': None, 'turns': 0, 'scores': [3, 3], 'history': [], 'error': 'No snake engine'}

    fn_a = _load_agent_fn(code_a)
    fn_b = _load_agent_fn(code_b)
    if not fn_a or not fn_b:
        return {'winner': None, 'turns': 0, 'scores': [3, 3], 'history': [], 'error': 'Agent load failed'}

    seed = int(time.time() * 1000) % (2**32)
    game = _SnakeRandomGameBase(seed=seed)
    try:
        result = game.run(fn_a, fn_b)
        return {
            'winner': result['winner'],
            'turns': result['turns'],
            'scores': result['scores'],
            'history': result.get('history', []),
        }
    except Exception as exc:
        return {'winner': None, 'turns': 0, 'scores': [3, 3], 'history': [], 'error': str(exc)}


def _run_snake_4p_match(code_a, code_b, mode='royale'):
    """Run a headless 4-player snake match. code_a controls snakes 0,2; code_b controls 1,3.
    Returns winner/turns/scores/history. Winner mapped to agent index (0 or 1) or None."""
    if not _HAS_SNAKE_ENGINE:
        return {'winner': None, 'turns': 0, 'scores': [3, 3], 'history': [], 'error': 'No snake engine'}

    fn_a = _load_agent_fn(code_a)
    fn_b = _load_agent_fn(code_b)
    if not fn_a or not fn_b:
        return {'winner': None, 'turns': 0, 'scores': [3, 3], 'history': [], 'error': 'Agent load failed'}

    if mode == '2v2':
        config = {'width': 24, 'height': 24, 'max_turns': 300, 'food_count': 10, 'mode': '2v2'}
    else:
        config = {'width': 30, 'height': 30, 'max_turns': 400, 'food_count': 12, 'mode': 'royale'}

    game = _SnakeGame4PBase(**config)
    try:
        # Agent A controls snakes 0, 2; Agent B controls snakes 1, 3
        result = game.run([fn_a, fn_b, fn_a, fn_b])

        # Map 4P winner to 2-agent winner
        raw_winner = result['winner']
        if raw_winner is None:
            winner = None
        elif mode == '2v2':
            # 'team0' (snakes 0,2) → agent 0; 'team1' (snakes 1,3) → agent 1
            winner = 0 if raw_winner == 'team0' else (1 if raw_winner == 'team1' else None)
        else:
            # Royale: player index 0,2 → agent 0; player index 1,3 → agent 1
            winner = 0 if raw_winner in (0, 2) else (1 if raw_winner in (1, 3) else None)

        # Aggregate scores: agent 0 = snakes 0+2, agent 1 = snakes 1+3
        scores_4p = result['scores']
        scores = [scores_4p[0] + scores_4p[2], scores_4p[1] + scores_4p[3]]

        return {
            'winner': winner,
            'turns': result['turns'],
            'scores': scores,
            'history': result.get('history', []),
        }
    except Exception as exc:
        return {'winner': None, 'turns': 0, 'scores': [3, 3], 'history': [], 'error': str(exc)}


def _run_match(game_id, code_a, code_b):
    """Dispatch match to the correct game engine."""
    if game_id == 'chess960':
        return _run_chess960_match(code_a, code_b)
    if game_id == 'othello':
        return _run_othello_match(code_a, code_b)
    if game_id == 'snake_random':
        return _run_snake_random_match(code_a, code_b)
    if game_id == 'snake_royale':
        return _run_snake_4p_match(code_a, code_b, mode='royale')
    if game_id == 'snake_2v2':
        return _run_snake_4p_match(code_a, code_b, mode='2v2')
    return _run_snake_match(code_a, code_b)


def _push_live_match(a1, a2, winner_name, history, game_id='snake'):
    """Push a match into the live ring buffer with raw snake state frames.
    a1/a2 are agent dicts with name, elo, wins, losses."""
    if not history:
        return

    entry = {
        'agent1': a1.get('name', '?'),
        'agent2': a2.get('name', '?'),
        'agent1_elo': a1.get('elo', 1000),
        'agent2_elo': a2.get('elo', 1000),
        'agent1_wl': f"{a1.get('wins', 0)}W/{a1.get('losses', 0)}L",
        'agent2_wl': f"{a2.get('wins', 0)}W/{a2.get('losses', 0)}L",
        'winner': winner_name,
        'gameId': game_id,
        'history': history,
    }

    with _live_lock:
        _live_matches.append(entry)
        if len(_live_matches) > _LIVE_BUFFER_SIZE:
            _live_matches.pop(0)


def get_live_matches(game_id='snake'):
    """Return recent matches for the live tournament canvases.
    Primary: in-memory ring buffer (filtered by game_id). Fallback: recent DB games."""
    with _live_lock:
        filtered = [m for m in _live_matches if m.get('gameId', 'snake') == game_id]
        if filtered:
            return filtered

    try:
        db_games = arena_get_recent_games_with_history(game_id, limit=_LIVE_BUFFER_SIZE)
        results = []
        for g in db_games:
            history = g.get('history', [])
            if not history:
                continue
            results.append({
                'agent1': g['agent1_name'],
                'agent2': g['agent2_name'],
                'agent1_elo': g.get('agent1_elo', 1000),
                'agent2_elo': g.get('agent2_elo', 1000),
                'agent1_wl': f"{g.get('agent1_wins', 0)}W/{g.get('agent1_losses', 0)}L",
                'agent2_wl': f"{g.get('agent2_wins', 0)}W/{g.get('agent2_losses', 0)}L",
                'winner': g['winner_name'],
                'gameId': game_id,
                'history': history,
            })
        return results
    except Exception:
        return []


_ALLOWED_MODULES = {'random', 'math', 'collections', 'itertools', 'functools', 'heapq'}
_BLOCKED_MODULES = {
    'os', 'subprocess', 'socket', 'sys', 'shutil', 'signal', 'ctypes',
    'multiprocessing', 'threading', 'pty', 'fcntl', 'resource', 'termios',
    'pwd', 'grp', 'tempfile', 'http', 'urllib', 'requests', 'pathlib',
    'io', 'pickle', 'shelve', 'sqlite3', 'webbrowser', 'code', 'codeop',
    'compileall', 'importlib',
}
_import_log_ctx = {'game_id': 'unknown', 'agent_name': 'unknown'}

def _safe_import(name, *args, **kwargs):
    """Blocklist-based import — block dangerous modules, allow everything else.

    If a non-blocked module is unavailable, logs it as a library request
    to the monitoring system so admins can add it to the runtime.
    """
    if name in _BLOCKED_MODULES:
        raise ImportError(f"Module '{name}' is not allowed")
    try:
        if isinstance(__builtins__, dict):
            return __builtins__['__import__'](name, *args, **kwargs)
        return __import__(name, *args, **kwargs)
    except ImportError:
        # Log missing library request for monitoring
        try:
            from db_arena import arena_log_library_request
            arena_log_library_request(
                game_id=_import_log_ctx.get('game_id', 'unknown'),
                agent_name=_import_log_ctx.get('agent_name', 'unknown'),
                library_name=name,
            )
        except Exception:
            pass
        raise

def _load_agent_fn(code):
    """Safely load a get_move function from Python code string."""
    try:
        namespace = {
            '__builtins__': {
                '__import__': _safe_import,
                'abs': abs, 'min': min, 'max': max, 'len': len, 'range': range,
                'int': int, 'float': float, 'str': str, 'list': list, 'dict': dict,
                'set': set, 'tuple': tuple, 'bool': bool, 'enumerate': enumerate,
                'zip': zip, 'sorted': sorted, 'reversed': reversed, 'sum': sum,
                'any': any, 'all': all, 'map': map, 'filter': filter,
                'isinstance': isinstance, 'type': type, 'ord': ord, 'chr': chr,
                'print': lambda *a, **k: None,
                'True': True, 'False': False, 'None': None,
            }
        }
        exec(code, namespace)
        fn = namespace.get('get_move')
        if callable(fn):
            return fn
        return None
    except Exception:
        return None


# ═══════════════════════════════════════════════════════════════════════════
#   Evolution — Tool Definitions (8 tools, matching default_program.md)
# ═══════════════════════════════════════════════════════════════════════════

_EVOLUTION_TOOLS = [
    {
        'name': 'query_db',
        'description': (
            'Run a SELECT query on the arena database. '
            'Tables: arena_agents (id, game_id, name, code, elo, games_played, wins, losses, draws, active), '
            'arena_games (id, game_id, agent1_id, agent2_id, winner_id, agent1_score, agent2_score, turns, history, is_upset, created_at).'
        ),
        'parameters': {
            'type': 'object',
            'properties': {'sql': {'type': 'string', 'description': 'SQL SELECT query'}},
            'required': ['sql'],
        },
    },
    {
        'name': 'read_agent',
        'description': "Read an agent's full source code by name.",
        'parameters': {
            'type': 'object',
            'properties': {'agent_name': {'type': 'string'}},
            'required': ['agent_name'],
        },
    },
    {
        'name': 'create_agent',
        'description': 'Create a new agent. Code must define get_move(state). Auto-tested against 12 scenarios.',
        'parameters': {
            'type': 'object',
            'properties': {
                'name': {'type': 'string', 'description': 'Unique name (letters/digits/underscores)'},
                'code': {'type': 'string', 'description': 'Full Python source with get_move(state)'},
            },
            'required': ['name', 'code'],
        },
    },
    {
        'name': 'edit_current_agent',
        'description': 'Edit an agent created THIS round (for fixing bugs).',
        'parameters': {
            'type': 'object',
            'properties': {
                'name': {'type': 'string', 'description': 'Name of the agent to edit'},
                'code': {'type': 'string', 'description': 'New full source code'},
            },
            'required': ['name', 'code'],
        },
    },
    {
        'name': 'run_test',
        'description': 'Run validation tests on an agent (syntax, safety, timing, return value).',
        'parameters': {
            'type': 'object',
            'properties': {'agent_name': {'type': 'string'}},
            'required': ['agent_name'],
        },
    },
    {
        'name': 'get_agent_games',
        'description': "Get an agent's recent game results with scores, turns, and key moments.",
        'parameters': {
            'type': 'object',
            'properties': {
                'agent_name': {'type': 'string'},
                'limit': {'type': 'integer', 'description': 'Number of games (default 5)'},
            },
            'required': ['agent_name'],
        },
    },
    {
        'name': 'get_game_replay',
        'description': 'Get a portion of a game replay — snake positions, scores, food per turn.',
        'parameters': {
            'type': 'object',
            'properties': {
                'game_id': {'type': 'integer', 'description': 'Game ID from get_agent_games'},
                'start_turn': {'type': 'integer', 'description': 'First turn (default 0)'},
                'end_turn': {'type': 'integer', 'description': 'Last turn (default 20)'},
            },
            'required': ['game_id'],
        },
    },
    {
        'name': 'test_match',
        'description': 'Run a test match between two agents and see the result.',
        'parameters': {
            'type': 'object',
            'properties': {
                'agent1_name': {'type': 'string'},
                'agent2_name': {'type': 'string'},
            },
            'required': ['agent1_name', 'agent2_name'],
        },
    },
]


# ═══════════════════════════════════════════════════════════════════════════
#   Evolution — LLM Tool-Calling Loop
# ═══════════════════════════════════════════════════════════════════════════

def _run_evolution(api_key, game_id='snake'):
    """Run one evolution cycle. Rotates Haiku/Sonnet/Opus/Gemini each generation."""
    generation = arena_increment_generation(game_id)

    model_id, model_label, provider = _EVOLUTION_MODELS[(generation - 1) % len(_EVOLUTION_MODELS)]
    print(f'[evolution] Gen {generation} using {model_label} ({model_id}) [{provider}]')

    # Resolve API key for this provider
    if provider == 'gemini':
        evo_key = os.environ.get('GEMINI_API_KEY', '')
        if not evo_key:
            print(f'[evolution] No GEMINI_API_KEY, skipping gen {generation}')
            return []
    else:
        evo_key = api_key

    program_data = arena_get_program(game_id)
    program_md = (program_data.get('content') if program_data else '') or _load_default_program(game_id)

    agents = arena_get_leaderboard(game_id, limit=10)
    for a in agents[:1]:
        full = arena_get_agent(game_id, a['id'])
        if full:
            a['code'] = full.get('code', '')

    system_prompt = program_md + """

Call create_agent with name and complete Python code.
The agent must have a get_move(state) function.
Must return in <100ms.
You may use any available Python library — test-import with try/except first.
"""

    leaderboard_text = ''
    if agents:
        leaderboard_text = 'Current leaderboard:\n'
        for i, a in enumerate(agents[:5]):
            leaderboard_text += f"  #{i+1} {a['name']} ELO={a['elo']:.0f} W/L/D={a['wins']}/{a['losses']}/{a['draws']}\n"
        top = agents[0]
        if top.get('code'):
            leaderboard_text += f"\nBest agent code ({top['name']}):\n```python\n{top['code']}\n```\n"

    user_prompt = f"""Generation {generation}. {leaderboard_text}
Create ONE agent. Name it gen{generation}_<strategy> (e.g. gen{generation}_flood_fill, gen{generation}_aggro_cutter).
Study the top agents and create a counter-strategy.
Call create_agent with name and full Python code."""

    created = []

    # Track program version + file for agent lineage
    program_version_id = None
    if program_data and program_data.get('versions'):
        for v in program_data['versions']:
            if v.get('applied') == 1:
                program_version_id = v['id']
                break

    program_file = _resolve_program_file(game_id)

    def tool_handler(name, args):
        return _handle_tool(name, args, game_id, agents, created,
                           contributor=model_label, program_version_id=program_version_id,
                           program_file=program_file)

    session_stats = None
    error_msg = None
    try:
        if provider == 'gemini':
            from server.arena_tool_runner import run_tool_loop_gemini
            result = run_tool_loop_gemini(
                api_key=evo_key,
                system_prompt=system_prompt,
                user_message=user_prompt,
                tools=_EVOLUTION_TOOLS,
                handler=tool_handler,
                model=model_id,
                max_tokens=8192,
                max_rounds=MAX_TOOL_ROUNDS,
            )
        else:
            from server.arena_tool_runner import run_tool_loop
            result = run_tool_loop(
                api_key=evo_key,
                system_prompt=system_prompt,
                user_message=user_prompt,
                tools=_EVOLUTION_TOOLS,
                handler=tool_handler,
                model=model_id,
                max_tokens=8192,
                max_rounds=MAX_TOOL_ROUNDS,
            )
        session_stats = result.get('stats', {})
    except Exception as e:
        error_msg = str(e)[:500]
        print(f'[heartbeat] Evolution error: {e}')
        traceback.print_exc()

    # Log one session record (replaces per-call logging)
    try:
        from db_arena import arena_log_evolution_session
        arena_log_evolution_session(
            game_id=game_id,
            generation=generation,
            model=model_id,
            provider=provider,
            status='success' if created else ('error' if error_msg else 'no_agent'),
            agents_created=len(created),
            error_message=error_msg,
            **(session_stats or {}),
        )
    except Exception:
        pass

    return created


def _handle_tool(name, args, game_id, agents, created_list,
                  contributor='arena_heartbeat', program_version_id=None,
                  program_file=None):
    """Handle tool calls during evolution. Supports all 8 tools."""

    if name == 'query_db':
        sql = args.get('sql', '')
        if not sql.strip().upper().startswith('SELECT'):
            return json.dumps({'error': 'Only SELECT queries are allowed.'})
        try:
            with _db() as conn:
                rows = conn.execute(sql).fetchall()
                result = [dict(r) for r in rows]
            result_str = json.dumps(result, default=str)
            if len(result_str) > 8000:
                result_str = result_str[:8000] + '\n... (truncated)'
            return result_str
        except Exception as exc:
            return json.dumps({'error': f'Query failed: {exc}'})

    if name == 'read_agent':
        agent_name = args.get('agent_name', '')
        agent = arena_get_agent_by_name(game_id, agent_name)
        if not agent:
            agent = next((a for a in agents if a['name'] == agent_name), None)
        if not agent:
            return json.dumps({'error': f"Agent '{agent_name}' not found"})
        return agent.get('code', '(no code)')

    if name == 'create_agent':
        return _tool_create_agent(args, game_id, agents, created_list,
                                  contributor=contributor, program_version_id=program_version_id,
                                  program_file=program_file)

    if name == 'edit_current_agent':
        agent_name = args.get('name', '')
        code = args.get('code', '')
        if agent_name not in created_list:
            return json.dumps({'error': f"Can only edit agents created THIS round. '{agent_name}' was not."})
        test_result = _validate_code(game_id, code)
        if test_result:
            return json.dumps({'error': test_result})
        agent = arena_get_agent_by_name(game_id, agent_name)
        if not agent:
            return json.dumps({'error': f"Agent '{agent_name}' not found in DB"})
        try:
            with _db() as conn:
                conn.execute(
                    'UPDATE arena_agents SET code = ?, program_version_id = ?, program_file = ? WHERE id = ?',
                    (code, program_version_id, program_file, agent['id'])
                )
            return json.dumps({'success': True, 'message': f"Agent '{agent_name}' updated and passed tests."})
        except Exception as exc:
            return json.dumps({'error': f'DB error: {exc}'})

    if name == 'run_test':
        agent_name = args.get('agent_name', '')
        agent = arena_get_agent_by_name(game_id, agent_name)
        if not agent:
            return json.dumps({'error': f"Agent '{agent_name}' not found"})
        error = _validate_code(game_id, agent.get('code', ''))
        if error:
            return json.dumps({'passed': False, 'details': error})
        return json.dumps({'passed': True, 'details': 'All 12 tests passed.'})

    if name == 'get_agent_games':
        agent_name = args.get('agent_name', '')
        limit = args.get('limit', 5)
        agent = arena_get_agent_by_name(game_id, agent_name)
        if not agent:
            return json.dumps({'error': f"Agent '{agent_name}' not found"})
        games = arena_get_agent_games(game_id, agent['id'], limit=int(limit))
        results = []
        for g in games:
            summary = {
                'id': g['id'], 'p1': g['agent1_name'], 'p2': g['agent2_name'],
                'winner': g['winner_name'],
                'scores': f"{g['agent1_score']}-{g['agent2_score']}",
                'turns': g['turns'],
            }
            history_raw = g.get('history', '[]')
            if history_raw and history_raw != '[]':
                try:
                    history = json.loads(history_raw) if isinstance(history_raw, str) else history_raw
                    if history:
                        summary['start_scores'] = history[0].get('scores')
                        summary['end_scores'] = history[-1].get('scores')
                        summary['end_alive'] = history[-1].get('alive')
                        summary['total_frames'] = len(history)
                except (json.JSONDecodeError, TypeError):
                    pass
            results.append(summary)
        return json.dumps(results, default=str, indent=1)

    if name == 'get_game_replay':
        match_id = args.get('game_id')
        start_turn = args.get('start_turn', 0)
        end_turn = args.get('end_turn', 20)
        if not match_id:
            return json.dumps({'error': 'game_id required'})
        game = arena_get_game(game_id, int(match_id))
        if not game:
            return json.dumps({'error': f'Game {match_id} not found'})
        history = game.get('history', [])
        if not history:
            return json.dumps({'game_id': match_id, 'message': 'No replay data.'})
        start = max(0, int(start_turn))
        end = min(len(history), int(end_turn))
        frames = []
        for i in range(start, end):
            frame = history[i]
            if game_id == 'chess960':
                # Chess960 replay: board state + last move + check info
                frames.append({
                    'turn': frame.get('turn', i),
                    'scores': frame.get('scores'),
                    'last_move': frame.get('last_move'),
                    'white_to_move': frame.get('white_to_move'),
                    'in_check': frame.get('in_check'),
                    'game_over': frame.get('game_over'),
                    'winner': frame.get('winner'),
                })
            elif game_id == 'othello':
                # Othello replay: board + last move + scores
                frames.append({
                    'turn': frame.get('turn', i),
                    'scores': frame.get('scores'),
                    'last_move': frame.get('last_move'),
                    'current_player': frame.get('current_player'),
                    'game_over': frame.get('game_over'),
                    'winner': frame.get('winner'),
                })
            else:
                # Snake replay: snake positions + food
                frames.append({
                    'turn': frame.get('turn', i),
                    'scores': frame.get('scores'),
                    'alive': frame.get('alive'),
                    'snake1_head': frame['snakes'][0][0] if frame.get('snakes') and frame['snakes'][0] else None,
                    'snake2_head': frame['snakes'][1][0] if frame.get('snakes') and len(frame['snakes']) > 1 and frame['snakes'][1] else None,
                    'food': frame.get('food'),
                })
        return json.dumps({
            'game_id': match_id, 'p1': game.get('agent1_name'), 'p2': game.get('agent2_name'),
            'winner': game.get('winner_name'), 'total_turns': len(history),
            'showing': f'turns {start}-{end}', 'frames': frames,
        }, indent=1)

    if name == 'test_match':
        a1_name = args.get('agent1_name', '')
        a2_name = args.get('agent2_name', '')
        a1 = arena_get_agent_by_name(game_id, a1_name) or next((a for a in agents if a['name'] == a1_name), None)
        a2 = arena_get_agent_by_name(game_id, a2_name) or next((a for a in agents if a['name'] == a2_name), None)
        if not a1:
            return json.dumps({'error': f"Agent '{a1_name}' not found"})
        if not a2:
            return json.dumps({'error': f"Agent '{a2_name}' not found"})
        result = _run_match(game_id, a1.get('code', ''), a2.get('code', ''))
        winner_name = a1_name if result['winner'] == 0 else (a2_name if result['winner'] == 1 else 'Draw')
        return json.dumps({'winner': winner_name, 'turns': result['turns'], 'scores': result['scores']})

    return json.dumps({'error': f'Unknown tool: {name}'})


# ═══════════════════════════════════════════════════════════════════════════
#   Agent Validation — 12 scenarios
# ═══════════════════════════════════════════════════════════════════════════

_VALID_MOVES = {'UP', 'DOWN', 'LEFT', 'RIGHT'}

_TEST_STATES = [
    ('center', {'grid_size': (20, 20), 'my_snake': [[10, 10], [9, 10], [8, 10]], 'my_direction': 'RIGHT', 'enemy_snake': [[15, 15], [16, 15], [17, 15]], 'enemy_direction': 'LEFT', 'food': [[5, 5], [12, 8], [18, 2]], 'turn': 50, 'prev_moves': [], 'memory': {}}),
    ('near_top_wall', {'grid_size': (20, 20), 'my_snake': [[10, 0], [10, 1], [10, 2]], 'my_direction': 'UP', 'enemy_snake': [[15, 15], [16, 15], [17, 15]], 'enemy_direction': 'LEFT', 'food': [[5, 5], [12, 8]], 'turn': 30, 'prev_moves': [], 'memory': {}}),
    ('near_bottom_wall', {'grid_size': (20, 20), 'my_snake': [[10, 19], [10, 18], [10, 17]], 'my_direction': 'DOWN', 'enemy_snake': [[5, 5], [4, 5], [3, 5]], 'enemy_direction': 'RIGHT', 'food': [[15, 10]], 'turn': 100, 'prev_moves': [], 'memory': {}}),
    ('near_left_wall', {'grid_size': (20, 20), 'my_snake': [[0, 10], [1, 10], [2, 10]], 'my_direction': 'LEFT', 'enemy_snake': [[19, 10], [18, 10], [17, 10]], 'enemy_direction': 'RIGHT', 'food': [[10, 10]], 'turn': 75, 'prev_moves': [], 'memory': {}}),
    ('corner_top_left', {'grid_size': (20, 20), 'my_snake': [[0, 0], [1, 0], [2, 0]], 'my_direction': 'LEFT', 'enemy_snake': [[19, 19], [18, 19], [17, 19]], 'enemy_direction': 'LEFT', 'food': [[10, 10]], 'turn': 10, 'prev_moves': [], 'memory': {}}),
    ('corner_bottom_right', {'grid_size': (20, 20), 'my_snake': [[19, 19], [18, 19], [17, 19]], 'my_direction': 'RIGHT', 'enemy_snake': [[0, 0], [1, 0], [2, 0]], 'enemy_direction': 'RIGHT', 'food': [[10, 10]], 'turn': 10, 'prev_moves': [], 'memory': {}}),
    ('long_snake', {'grid_size': (20, 20), 'my_snake': [[10, 10], [10, 11], [10, 12], [10, 13], [10, 14], [10, 15], [10, 16], [10, 17], [9, 17], [8, 17], [7, 17], [6, 17], [5, 17], [4, 17], [3, 17]], 'my_direction': 'UP', 'enemy_snake': [[5, 5], [4, 5], [3, 5]], 'enemy_direction': 'RIGHT', 'food': [[15, 5], [2, 2], [18, 18]], 'turn': 200, 'prev_moves': [], 'memory': {}}),
    ('enemy_adjacent', {'grid_size': (20, 20), 'my_snake': [[10, 10], [9, 10], [8, 10]], 'my_direction': 'RIGHT', 'enemy_snake': [[12, 10], [13, 10], [14, 10]], 'enemy_direction': 'LEFT', 'food': [[10, 5], [10, 15]], 'turn': 80, 'prev_moves': [], 'memory': {}}),
    ('enemy_dead', {'grid_size': (20, 20), 'my_snake': [[10, 10], [9, 10], [8, 10]], 'my_direction': 'RIGHT', 'enemy_snake': [], 'enemy_direction': None, 'food': [[15, 15], [5, 5]], 'turn': 300, 'prev_moves': [], 'memory': {}}),
    ('tight_space', {'grid_size': (20, 20), 'my_snake': [[5, 5], [5, 6], [5, 7], [4, 7], [3, 7], [3, 6], [3, 5], [4, 5]], 'my_direction': 'UP', 'enemy_snake': [[15, 15], [16, 15]], 'enemy_direction': 'LEFT', 'food': [[10, 10]], 'turn': 150, 'prev_moves': [], 'memory': {}}),
    ('start_of_game', {'grid_size': (20, 20), 'my_snake': [[3, 3], [2, 3], [1, 3]], 'my_direction': 'RIGHT', 'enemy_snake': [[16, 16], [17, 16], [18, 16]], 'enemy_direction': 'LEFT', 'food': [[10, 5], [7, 12], [15, 3]], 'turn': 0, 'prev_moves': [], 'memory': {}}),
    ('late_game', {'grid_size': (20, 20), 'my_snake': [[10, 10], [10, 11], [10, 12], [10, 13], [10, 14], [10, 15]], 'my_direction': 'UP', 'enemy_snake': [[5, 5], [5, 6], [5, 7], [5, 8], [5, 9], [5, 10], [5, 11]], 'enemy_direction': 'UP', 'food': [[18, 18], [1, 1], [15, 3]], 'turn': 450, 'prev_moves': [], 'memory': {}}),
]


def _validate_agent_code(code):
    """Validate agent code against 12 game scenarios. Returns error string or None."""
    forbidden = ['import os', 'import subprocess', 'import socket', 'import sys',
                  'open(', '__import__', 'exec(', 'eval(']
    for pat in forbidden:
        if pat in code:
            return f'Forbidden pattern: {pat}'

    fn = _load_agent_fn(code)
    if not fn:
        return 'get_move function not found or syntax error.'

    failures = []
    for scenario_name, state in _TEST_STATES:
        try:
            start = time.time()
            result = fn(state)
            elapsed = time.time() - start
            if elapsed > 0.1:
                failures.append(f'{scenario_name}: too slow ({elapsed*1000:.0f}ms)')
            elif result not in _VALID_MOVES:
                failures.append(f"{scenario_name}: returned '{result}'")
        except Exception as exc:
            failures.append(f'{scenario_name}: CRASH — {type(exc).__name__}: {exc}')

    if failures:
        return 'Test failures:\n  ' + '\n  '.join(failures)
    return None


# ═══════════════════════════════════════════════════════════════════════════
#   Chess960 Agent Validation — 12 scenarios (lazily built from engine)
# ═══════════════════════════════════════════════════════════════════════════

_chess960_test_states_cache = None


def _get_chess960_test_states():
    """Build chess960 test states lazily using the engine."""
    global _chess960_test_states_cache
    if _chess960_test_states_cache is not None:
        return _chess960_test_states_cache
    if not _HAS_CHESS960_ENGINE:
        return []

    sequences = [
        ('opening_white', 518, [], 'white'),
        ('opening_black', 518, ['e2e4'], 'black'),
        ('early_game', 518, ['e2e4', 'e7e5'], 'white'),
        ('developed', 518, ['e2e4', 'e7e5', 'g1f3'], 'black'),
        ('italian', 518, ['e2e4', 'e7e5', 'g1f3', 'b8c6', 'f1c4'], 'black'),
        ('sicilian', 518, ['e2e4', 'c7c5'], 'white'),
        ('queens_pawn', 518, ['d2d4', 'd7d5', 'c2c4'], 'black'),
        ('center_tension', 518, ['e2e4', 'e7e5', 'd2d4', 'e5d4', 'g1f3'], 'black'),
        ('fischer_pos_42', 42, [], 'white'),
        ('fischer_pos_777', 777, ['d2d4'], 'black'),
        ('knights_out', 518, ['g1f3', 'b8c6', 'b1c3', 'g8f6'], 'white'),
        ('fischer_pos_0', 0, [], 'white'),
    ]

    states = []
    for name, pos_id, moves, color in sequences:
        try:
            game = _Chess960GameBase(position_id=pos_id)
            game.setup()
            for m in moves:
                game.step(m)
            state = game.get_state(color)
            if state.get('legal_moves'):
                states.append((name, state))
        except Exception:
            pass
    _chess960_test_states_cache = states
    return states


def _validate_chess960_code(code):
    """Validate chess960 agent code against 12 game scenarios. Returns error string or None."""
    forbidden = ['import os', 'import subprocess', 'import socket', 'import sys',
                  'open(', '__import__', 'exec(', 'eval(']
    for pat in forbidden:
        if pat in code:
            return f'Forbidden pattern: {pat}'

    fn = _load_agent_fn(code)
    if not fn:
        return 'get_move function not found or syntax error.'

    test_states = _get_chess960_test_states()
    if not test_states:
        return 'Chess960 engine not available for validation.'

    failures = []
    for scenario_name, state in test_states:
        try:
            start = time.time()
            result = fn(state)
            elapsed = time.time() - start
            if elapsed > 0.1:
                failures.append(f'{scenario_name}: too slow ({elapsed*1000:.0f}ms)')
            elif not isinstance(result, str) or result not in state['legal_moves']:
                failures.append(f"{scenario_name}: returned '{result}' (not a legal move)")
        except Exception as exc:
            failures.append(f'{scenario_name}: CRASH — {type(exc).__name__}: {exc}')

    if failures:
        return 'Test failures:\n  ' + '\n  '.join(failures)
    return None


# ═══════════════════════════════════════════════════════════════════════════
#   Othello Agent Validation — 12 scenarios (lazily built from engine)
# ═══════════════════════════════════════════════════════════════════════════

_othello_test_states_cache = None


def _get_othello_test_states():
    """Build Othello test states lazily using the engine."""
    global _othello_test_states_cache
    if _othello_test_states_cache is not None:
        return _othello_test_states_cache
    if not _HAS_OTHELLO_ENGINE:
        return []

    # Play through specific move sequences to create interesting board states
    sequences = [
        ('opening_black', [], 1),                           # standard opening
        ('opening_white', [[3, 2]], -1),                    # after 1 move
        ('early_game', [[3, 2], [2, 2]], 1),                # after 2 moves
        ('developing', [[3, 2], [2, 2], [1, 2]], -1),      # after 3 moves
        ('mid_game', [[3, 2], [2, 2], [1, 2], [4, 2], [5, 3]], -1),
        ('edge_play', [[3, 2], [2, 4], [5, 3], [4, 2], [5, 4], [2, 2]], 1),
        ('corner_area', [[3, 2], [2, 4], [5, 3], [4, 2], [5, 4], [2, 2], [1, 2]], -1),
        ('complex', [[3, 2], [2, 2], [1, 2], [4, 2], [5, 3], [5, 4], [5, 5]], -1),
        ('black_mid', [[3, 2], [2, 4], [5, 3], [4, 2]], 1),
        ('white_mid', [[3, 2], [2, 4], [5, 3]], -1),
        ('many_moves', [[3, 2], [2, 2], [1, 2], [4, 2], [5, 3], [5, 4], [5, 5], [2, 4]], 1),
        ('late_opening', [[3, 2], [2, 2], [1, 2], [4, 2], [5, 3], [5, 2]], 1),
    ]

    states = []
    for name, moves, color in sequences:
        try:
            game = _OthelloGameBase()
            game.setup()
            for m in moves:
                game.step(m)
            state = game.get_state(color)
            if state.get('legal_moves'):
                states.append((name, state))
        except Exception:
            pass
    _othello_test_states_cache = states
    return states


def _validate_othello_code(code):
    """Validate Othello agent code against 12 game scenarios. Returns error string or None."""
    forbidden = ['import os', 'import subprocess', 'import socket', 'import sys',
                  'open(', '__import__', 'exec(', 'eval(']
    for pat in forbidden:
        if pat in code:
            return f'Forbidden pattern: {pat}'

    fn = _load_agent_fn(code)
    if not fn:
        return 'get_move function not found or syntax error.'

    test_states = _get_othello_test_states()
    if not test_states:
        return 'Othello engine not available for validation.'

    failures = []
    for scenario_name, state in test_states:
        try:
            start = time.time()
            result = fn(state)
            elapsed = time.time() - start
            if elapsed > 0.1:
                failures.append(f'{scenario_name}: too slow ({elapsed*1000:.0f}ms)')
            elif not isinstance(result, (list, tuple)) or len(result) != 2:
                failures.append(f"{scenario_name}: returned '{result}' (must be [row, col])")
            elif [int(result[0]), int(result[1])] not in state['legal_moves']:
                failures.append(f"{scenario_name}: returned {list(result)} (not a legal move)")
        except Exception as exc:
            failures.append(f'{scenario_name}: CRASH — {type(exc).__name__}: {exc}')

    if failures:
        return 'Test failures:\n  ' + '\n  '.join(failures)
    return None


# ═══════════════════════════════════════════════════════════════════════════
#   Snake Random Maps Validation — 12 scenarios (2P + walls)
# ═══════════════════════════════════════════════════════════════════════════

_TEST_STATES_RANDOM = [
    ('center_walls', {'grid_size': (20, 20), 'my_snake': [[10, 10], [9, 10], [8, 10]], 'my_direction': 'RIGHT', 'enemy_snake': [[15, 15], [16, 15], [17, 15]], 'enemy_direction': 'LEFT', 'food': [[5, 5], [12, 8]], 'walls': [[7, 7], [7, 8], [7, 9], [12, 5], [13, 5]], 'turn': 50, 'prev_moves': [], 'memory': {}}),
    ('wall_above', {'grid_size': (20, 20), 'my_snake': [[10, 5], [10, 6], [10, 7]], 'my_direction': 'UP', 'enemy_snake': [[15, 15], [16, 15], [17, 15]], 'enemy_direction': 'LEFT', 'food': [[5, 5]], 'walls': [[10, 4], [9, 4], [11, 4]], 'turn': 30, 'prev_moves': [], 'memory': {}}),
    ('wall_corridor', {'grid_size': (20, 20), 'my_snake': [[5, 10], [4, 10], [3, 10]], 'my_direction': 'RIGHT', 'enemy_snake': [[15, 10], [16, 10], [17, 10]], 'enemy_direction': 'LEFT', 'food': [[10, 5]], 'walls': [[5, 9], [6, 9], [7, 9], [5, 11], [6, 11], [7, 11]], 'turn': 60, 'prev_moves': [], 'memory': {}}),
    ('near_border', {'grid_size': (20, 20), 'my_snake': [[1, 10], [2, 10], [3, 10]], 'my_direction': 'LEFT', 'enemy_snake': [[18, 10], [17, 10], [16, 10]], 'enemy_direction': 'RIGHT', 'food': [[10, 10]], 'walls': [[5, 5], [5, 6]], 'turn': 40, 'prev_moves': [], 'memory': {}}),
    ('corner_walls', {'grid_size': (20, 20), 'my_snake': [[2, 2], [3, 2], [4, 2]], 'my_direction': 'LEFT', 'enemy_snake': [[17, 17], [16, 17], [15, 17]], 'enemy_direction': 'RIGHT', 'food': [[10, 10]], 'walls': [[3, 3], [3, 4], [4, 3]], 'turn': 20, 'prev_moves': [], 'memory': {}}),
    ('many_walls', {'grid_size': (20, 20), 'my_snake': [[10, 10], [9, 10], [8, 10]], 'my_direction': 'RIGHT', 'enemy_snake': [[15, 15], [16, 15], [17, 15]], 'enemy_direction': 'LEFT', 'food': [[5, 5]], 'walls': [[3, 3], [3, 4], [3, 5], [7, 7], [7, 8], [12, 3], [12, 4], [12, 5], [15, 8], [15, 9], [15, 10]], 'turn': 100, 'prev_moves': [], 'memory': {}}),
    ('wall_trap', {'grid_size': (20, 20), 'my_snake': [[8, 8], [8, 9], [8, 10]], 'my_direction': 'UP', 'enemy_snake': [[15, 15], [14, 15], [13, 15]], 'enemy_direction': 'RIGHT', 'food': [[12, 12]], 'walls': [[7, 7], [8, 7], [9, 7], [9, 8]], 'turn': 80, 'prev_moves': [], 'memory': {}}),
    ('enemy_near_wall', {'grid_size': (20, 20), 'my_snake': [[10, 10], [9, 10], [8, 10]], 'my_direction': 'RIGHT', 'enemy_snake': [[12, 10], [13, 10], [14, 10]], 'enemy_direction': 'LEFT', 'food': [[10, 5]], 'walls': [[11, 9], [11, 11]], 'turn': 90, 'prev_moves': [], 'memory': {}}),
    ('enemy_dead_walls', {'grid_size': (20, 20), 'my_snake': [[10, 10], [9, 10], [8, 10]], 'my_direction': 'RIGHT', 'enemy_snake': [], 'enemy_direction': None, 'food': [[15, 15]], 'walls': [[5, 5], [5, 6], [6, 5]], 'turn': 150, 'prev_moves': [], 'memory': {}}),
    ('no_walls', {'grid_size': (20, 20), 'my_snake': [[10, 10], [9, 10], [8, 10]], 'my_direction': 'RIGHT', 'enemy_snake': [[15, 15], [16, 15], [17, 15]], 'enemy_direction': 'LEFT', 'food': [[5, 5]], 'walls': [], 'turn': 10, 'prev_moves': [], 'memory': {}}),
    ('start_walls', {'grid_size': (20, 20), 'my_snake': [[3, 3], [2, 3], [1, 3]], 'my_direction': 'RIGHT', 'enemy_snake': [[16, 16], [17, 16], [18, 16]], 'enemy_direction': 'LEFT', 'food': [[10, 5]], 'walls': [[5, 3], [5, 4], [5, 5], [10, 10], [11, 10]], 'turn': 0, 'prev_moves': [], 'memory': {}}),
    ('late_game_walls', {'grid_size': (20, 20), 'my_snake': [[10, 10], [10, 11], [10, 12], [10, 13], [10, 14]], 'my_direction': 'UP', 'enemy_snake': [[5, 5], [5, 6], [5, 7], [5, 8]], 'enemy_direction': 'UP', 'food': [[18, 18]], 'walls': [[8, 8], [8, 9], [9, 8], [12, 12], [12, 13]], 'turn': 180, 'prev_moves': [], 'memory': {}}),
]


def _validate_snake_random_code(code):
    """Validate agent code against 12 snake random-maps scenarios."""
    forbidden = ['import os', 'import subprocess', 'import socket', 'import sys',
                  'open(', '__import__', 'exec(', 'eval(']
    for pat in forbidden:
        if pat in code:
            return f'Forbidden pattern: {pat}'

    fn = _load_agent_fn(code)
    if not fn:
        return 'get_move function not found or syntax error.'

    failures = []
    for scenario_name, state in _TEST_STATES_RANDOM:
        try:
            start = time.time()
            result = fn(state)
            elapsed = time.time() - start
            if elapsed > 0.1:
                failures.append(f'{scenario_name}: too slow ({elapsed*1000:.0f}ms)')
            elif result not in _VALID_MOVES:
                failures.append(f"{scenario_name}: returned '{result}'")
        except Exception as exc:
            failures.append(f'{scenario_name}: CRASH — {type(exc).__name__}: {exc}')

    if failures:
        return 'Test failures:\n  ' + '\n  '.join(failures)
    return None


# ═══════════════════════════════════════════════════════════════════════════
#   Snake Battle Royale (4P) Validation — 12 scenarios
# ═══════════════════════════════════════════════════════════════════════════

def _make_4p_state(my_idx, my_body, my_dir, snakes_data, food, turn, grid_size=(30, 30)):
    """Build a 4P state dict for testing."""
    snakes = []
    for i, (body, direction, alive) in enumerate(snakes_data):
        snakes.append({
            'body': body, 'direction': direction, 'alive': alive,
            'is_ally': False,  # royale: no allies
        })
    return {
        'grid_size': grid_size,
        'my_snake': my_body,
        'my_direction': my_dir,
        'my_index': my_idx,
        'snakes': snakes,
        'food': food,
        'turn': turn,
        'prev_moves': [],
    }

_TEST_STATES_ROYALE = [
    ('center_4p', _make_4p_state(0, [[15, 15], [14, 15], [13, 15]], 'RIGHT',
        [([[15, 15], [14, 15], [13, 15]], 'RIGHT', True), ([[25, 4], [26, 4], [27, 4]], 'LEFT', True),
         ([[4, 25], [3, 25], [2, 25]], 'RIGHT', True), ([[25, 25], [26, 25], [27, 25]], 'LEFT', True)],
        [[10, 10], [20, 20], [5, 25]], 50)),
    ('near_wall_4p', _make_4p_state(0, [[1, 15], [2, 15], [3, 15]], 'LEFT',
        [([[1, 15], [2, 15], [3, 15]], 'LEFT', True), ([[25, 4], [26, 4], [27, 4]], 'LEFT', True),
         ([[4, 25], [3, 25], [2, 25]], 'RIGHT', True), ([[25, 25], [26, 25], [27, 25]], 'LEFT', True)],
        [[10, 10]], 30)),
    ('corner_4p', _make_4p_state(0, [[1, 1], [2, 1], [3, 1]], 'LEFT',
        [([[1, 1], [2, 1], [3, 1]], 'LEFT', True), ([[28, 1], [27, 1], [26, 1]], 'RIGHT', True),
         ([[1, 28], [2, 28], [3, 28]], 'LEFT', True), ([[28, 28], [27, 28], [26, 28]], 'RIGHT', True)],
        [[15, 15]], 10)),
    ('two_dead_4p', _make_4p_state(0, [[15, 15], [14, 15], [13, 15]], 'RIGHT',
        [([[15, 15], [14, 15], [13, 15]], 'RIGHT', True), ([[25, 4], [26, 4], [27, 4]], 'LEFT', True),
         ([], None, False), ([], None, False)],
        [[10, 10]], 200)),
    ('enemy_adjacent_4p', _make_4p_state(0, [[15, 15], [14, 15], [13, 15]], 'RIGHT',
        [([[15, 15], [14, 15], [13, 15]], 'RIGHT', True), ([[17, 15], [18, 15], [19, 15]], 'LEFT', True),
         ([[15, 17], [15, 18], [15, 19]], 'UP', True), ([[25, 25], [26, 25], [27, 25]], 'LEFT', True)],
        [[10, 10], [20, 20]], 80)),
    ('long_snake_4p', _make_4p_state(0, [[15, 15], [15, 16], [15, 17], [15, 18], [15, 19], [15, 20], [15, 21]], 'UP',
        [([[15, 15], [15, 16], [15, 17], [15, 18], [15, 19], [15, 20], [15, 21]], 'UP', True),
         ([[5, 5], [4, 5], [3, 5]], 'RIGHT', True),
         ([[25, 5], [26, 5], [27, 5]], 'LEFT', True), ([[25, 25], [26, 25], [27, 25]], 'LEFT', True)],
        [[10, 10], [20, 20], [5, 25]], 150)),
    ('start_4p', _make_4p_state(0, [[4, 4], [3, 4], [2, 4]], 'RIGHT',
        [([[4, 4], [3, 4], [2, 4]], 'RIGHT', True), ([[25, 4], [26, 4], [27, 4]], 'LEFT', True),
         ([[4, 25], [3, 25], [2, 25]], 'RIGHT', True), ([[25, 25], [26, 25], [27, 25]], 'LEFT', True)],
        [[10, 10], [20, 10], [10, 20], [20, 20]], 0)),
    ('last_alive_4p', _make_4p_state(0, [[15, 15], [14, 15], [13, 15]], 'RIGHT',
        [([[15, 15], [14, 15], [13, 15]], 'RIGHT', True), ([], None, False),
         ([], None, False), ([], None, False)],
        [[10, 10]], 300)),
    ('crowded_4p', _make_4p_state(0, [[15, 15], [14, 15], [13, 15]], 'RIGHT',
        [([[15, 15], [14, 15], [13, 15]], 'RIGHT', True), ([[16, 14], [17, 14], [18, 14]], 'LEFT', True),
         ([[14, 16], [13, 16], [12, 16]], 'RIGHT', True), ([[16, 16], [17, 16], [18, 16]], 'LEFT', True)],
        [[15, 10], [15, 20]], 100)),
    ('as_player2_4p', _make_4p_state(1, [[25, 4], [26, 4], [27, 4]], 'LEFT',
        [([[4, 4], [3, 4], [2, 4]], 'RIGHT', True), ([[25, 4], [26, 4], [27, 4]], 'LEFT', True),
         ([[4, 25], [3, 25], [2, 25]], 'RIGHT', True), ([[25, 25], [26, 25], [27, 25]], 'LEFT', True)],
        [[15, 15]], 20)),
    ('as_player3_4p', _make_4p_state(2, [[4, 25], [3, 25], [2, 25]], 'RIGHT',
        [([[4, 4], [3, 4], [2, 4]], 'RIGHT', True), ([[25, 4], [26, 4], [27, 4]], 'LEFT', True),
         ([[4, 25], [3, 25], [2, 25]], 'RIGHT', True), ([[25, 25], [26, 25], [27, 25]], 'LEFT', True)],
        [[15, 15]], 20)),
    ('late_game_4p', _make_4p_state(0, [[15, 15], [15, 16], [15, 17], [15, 18], [15, 19]], 'UP',
        [([[15, 15], [15, 16], [15, 17], [15, 18], [15, 19]], 'UP', True),
         ([[10, 10], [10, 11], [10, 12], [10, 13]], 'UP', True),
         ([], None, False), ([], None, False)],
        [[5, 5], [25, 25]], 350)),
]


def _validate_snake_royale_code(code):
    """Validate agent code against 12 snake royale (4P) scenarios."""
    forbidden = ['import os', 'import subprocess', 'import socket', 'import sys',
                  'open(', '__import__', 'exec(', 'eval(']
    for pat in forbidden:
        if pat in code:
            return f'Forbidden pattern: {pat}'

    fn = _load_agent_fn(code)
    if not fn:
        return 'get_move function not found or syntax error.'

    failures = []
    for scenario_name, state in _TEST_STATES_ROYALE:
        try:
            start = time.time()
            result = fn(state)
            elapsed = time.time() - start
            if elapsed > 0.1:
                failures.append(f'{scenario_name}: too slow ({elapsed*1000:.0f}ms)')
            elif result not in _VALID_MOVES:
                failures.append(f"{scenario_name}: returned '{result}'")
        except Exception as exc:
            failures.append(f'{scenario_name}: CRASH — {type(exc).__name__}: {exc}')

    if failures:
        return 'Test failures:\n  ' + '\n  '.join(failures)
    return None


# ═══════════════════════════════════════════════════════════════════════════
#   Snake 2v2 Teams (4P) Validation — 12 scenarios
# ═══════════════════════════════════════════════════════════════════════════

def _make_2v2_state(my_idx, my_body, my_dir, snakes_data, food, turn, grid_size=(24, 24)):
    """Build a 2v2 state dict for testing. Teams: (0,2) vs (1,3)."""
    my_team = my_idx % 2
    snakes = []
    for i, (body, direction, alive) in enumerate(snakes_data):
        snakes.append({
            'body': body, 'direction': direction, 'alive': alive,
            'is_ally': (i % 2) == my_team,
        })
    # Add 2v2-specific fields
    ally_idx = {0: 2, 1: 3, 2: 0, 3: 1}[my_idx]
    ally_data = snakes_data[ally_idx]
    enemy_indices = [i for i in range(4) if i != my_idx and (i % 2) != my_team]
    return {
        'grid_size': grid_size,
        'my_snake': my_body,
        'my_direction': my_dir,
        'my_index': my_idx,
        'snakes': snakes,
        'ally_snake': ally_data[0] if ally_data[2] else [],
        'ally_direction': ally_data[1] if ally_data[2] else None,
        'enemies': [{'body': snakes_data[i][0] if snakes_data[i][2] else [],
                      'direction': snakes_data[i][1] if snakes_data[i][2] else None,
                      'alive': snakes_data[i][2]} for i in enemy_indices],
        'food': food,
        'turn': turn,
        'prev_moves': [],
    }

_TEST_STATES_2V2 = [
    ('center_2v2', _make_2v2_state(0, [[12, 12], [11, 12], [10, 12]], 'RIGHT',
        [([[12, 12], [11, 12], [10, 12]], 'RIGHT', True), ([[19, 4], [20, 4], [21, 4]], 'LEFT', True),
         ([[4, 19], [3, 19], [2, 19]], 'RIGHT', True), ([[19, 19], [20, 19], [21, 19]], 'LEFT', True)],
        [[8, 8], [16, 16]], 50)),
    ('near_wall_2v2', _make_2v2_state(0, [[1, 12], [2, 12], [3, 12]], 'LEFT',
        [([[1, 12], [2, 12], [3, 12]], 'LEFT', True), ([[19, 4], [20, 4], [21, 4]], 'LEFT', True),
         ([[4, 19], [3, 19], [2, 19]], 'RIGHT', True), ([[19, 19], [20, 19], [21, 19]], 'LEFT', True)],
        [[12, 12]], 30)),
    ('ally_nearby_2v2', _make_2v2_state(0, [[10, 10], [9, 10], [8, 10]], 'RIGHT',
        [([[10, 10], [9, 10], [8, 10]], 'RIGHT', True), ([[19, 4], [20, 4], [21, 4]], 'LEFT', True),
         ([[11, 10], [11, 11], [11, 12]], 'UP', True), ([[19, 19], [20, 19], [21, 19]], 'LEFT', True)],
        [[5, 5]], 40)),
    ('enemy_adjacent_2v2', _make_2v2_state(0, [[10, 10], [9, 10], [8, 10]], 'RIGHT',
        [([[10, 10], [9, 10], [8, 10]], 'RIGHT', True), ([[12, 10], [13, 10], [14, 10]], 'LEFT', True),
         ([[4, 19], [3, 19], [2, 19]], 'RIGHT', True), ([[19, 19], [20, 19], [21, 19]], 'LEFT', True)],
        [[10, 5]], 70)),
    ('ally_dead_2v2', _make_2v2_state(0, [[12, 12], [11, 12], [10, 12]], 'RIGHT',
        [([[12, 12], [11, 12], [10, 12]], 'RIGHT', True), ([[19, 4], [20, 4], [21, 4]], 'LEFT', True),
         ([], None, False), ([[19, 19], [20, 19], [21, 19]], 'LEFT', True)],
        [[8, 8]], 150)),
    ('enemies_dead_2v2', _make_2v2_state(0, [[12, 12], [11, 12], [10, 12]], 'RIGHT',
        [([[12, 12], [11, 12], [10, 12]], 'RIGHT', True), ([], None, False),
         ([[4, 19], [3, 19], [2, 19]], 'RIGHT', True), ([], None, False)],
        [[8, 8]], 200)),
    ('start_2v2', _make_2v2_state(0, [[4, 4], [3, 4], [2, 4]], 'RIGHT',
        [([[4, 4], [3, 4], [2, 4]], 'RIGHT', True), ([[19, 4], [20, 4], [21, 4]], 'LEFT', True),
         ([[4, 19], [3, 19], [2, 19]], 'RIGHT', True), ([[19, 19], [20, 19], [21, 19]], 'LEFT', True)],
        [[8, 8], [16, 8], [8, 16], [16, 16]], 0)),
    ('as_player1_2v2', _make_2v2_state(1, [[19, 4], [20, 4], [21, 4]], 'LEFT',
        [([[4, 4], [3, 4], [2, 4]], 'RIGHT', True), ([[19, 4], [20, 4], [21, 4]], 'LEFT', True),
         ([[4, 19], [3, 19], [2, 19]], 'RIGHT', True), ([[19, 19], [20, 19], [21, 19]], 'LEFT', True)],
        [[12, 12]], 20)),
    ('as_player2_2v2', _make_2v2_state(2, [[4, 19], [3, 19], [2, 19]], 'RIGHT',
        [([[4, 4], [3, 4], [2, 4]], 'RIGHT', True), ([[19, 4], [20, 4], [21, 4]], 'LEFT', True),
         ([[4, 19], [3, 19], [2, 19]], 'RIGHT', True), ([[19, 19], [20, 19], [21, 19]], 'LEFT', True)],
        [[12, 12]], 20)),
    ('long_snake_2v2', _make_2v2_state(0, [[12, 12], [12, 13], [12, 14], [12, 15], [12, 16], [12, 17]], 'UP',
        [([[12, 12], [12, 13], [12, 14], [12, 15], [12, 16], [12, 17]], 'UP', True),
         ([[5, 5], [4, 5], [3, 5]], 'RIGHT', True),
         ([[4, 19], [3, 19], [2, 19]], 'RIGHT', True), ([[19, 19], [20, 19], [21, 19]], 'LEFT', True)],
        [[8, 8], [16, 16]], 120)),
    ('corner_2v2', _make_2v2_state(0, [[1, 1], [2, 1], [3, 1]], 'LEFT',
        [([[1, 1], [2, 1], [3, 1]], 'LEFT', True), ([[22, 1], [21, 1], [20, 1]], 'RIGHT', True),
         ([[1, 22], [2, 22], [3, 22]], 'LEFT', True), ([[22, 22], [21, 22], [20, 22]], 'RIGHT', True)],
        [[12, 12]], 10)),
    ('late_game_2v2', _make_2v2_state(0, [[12, 12], [12, 13], [12, 14], [12, 15]], 'UP',
        [([[12, 12], [12, 13], [12, 14], [12, 15]], 'UP', True),
         ([[8, 8], [8, 9], [8, 10], [8, 11], [8, 12]], 'UP', True),
         ([[4, 19], [3, 19], [2, 19]], 'RIGHT', True), ([], None, False)],
        [[5, 5], [20, 20]], 250)),
]


def _validate_snake_2v2_code(code):
    """Validate agent code against 12 snake 2v2 team scenarios."""
    forbidden = ['import os', 'import subprocess', 'import socket', 'import sys',
                  'open(', '__import__', 'exec(', 'eval(']
    for pat in forbidden:
        if pat in code:
            return f'Forbidden pattern: {pat}'

    fn = _load_agent_fn(code)
    if not fn:
        return 'get_move function not found or syntax error.'

    failures = []
    for scenario_name, state in _TEST_STATES_2V2:
        try:
            start = time.time()
            result = fn(state)
            elapsed = time.time() - start
            if elapsed > 0.1:
                failures.append(f'{scenario_name}: too slow ({elapsed*1000:.0f}ms)')
            elif result not in _VALID_MOVES:
                failures.append(f"{scenario_name}: returned '{result}'")
        except Exception as exc:
            failures.append(f'{scenario_name}: CRASH — {type(exc).__name__}: {exc}')

    if failures:
        return 'Test failures:\n  ' + '\n  '.join(failures)
    return None


def _validate_code(game_id, code):
    """Dispatch validation to the correct game validator."""
    if game_id == 'chess960':
        return _validate_chess960_code(code)
    if game_id == 'othello':
        return _validate_othello_code(code)
    if game_id == 'snake_random':
        return _validate_snake_random_code(code)
    if game_id == 'snake_royale':
        return _validate_snake_royale_code(code)
    if game_id == 'snake_2v2':
        return _validate_snake_2v2_code(code)
    return _validate_agent_code(code)


def _tool_create_agent(args, game_id, agents, created_list,
                       contributor='arena_heartbeat', program_version_id=None,
                       program_file=None):
    """Handle the create_agent tool call."""
    agent_name = args.get('name', '')
    code = args.get('code', '')

    if not re.match(r'^[a-zA-Z_][a-zA-Z0-9_]*$', agent_name):
        return json.dumps({'error': 'Invalid name. Letters, digits, underscores only.'})

    error = _validate_code(game_id, code)
    if error:
        return json.dumps({'error': f'Code validation failed: {error}'})

    try:
        result = arena_submit_agent(game_id, agent_name, code, contributor=contributor,
                                    program_version_id=program_version_id,
                                    program_file=program_file)
        if isinstance(result, str):
            return json.dumps({'error': result})
        created_list.append(agent_name)

        test_note = ''
        if agents:
            opp = random.choice(agents[:5])
            match_result = _run_match(game_id, code, opp.get('code', ''))
            if match_result.get('winner') == 0:
                test_note = f" Quick test vs {opp['name']}: WIN in {match_result['turns']} turns."
            elif match_result.get('winner') == 1:
                test_note = f" Quick test vs {opp['name']}: LOSS in {match_result['turns']} turns."
            else:
                test_note = f" Quick test vs {opp['name']}: DRAW in {match_result['turns']} turns."

        return json.dumps({'success': True, 'message': f"Agent '{agent_name}' created (ELO: 1000).{test_note}"})
    except Exception as exc:
        return json.dumps({'error': f'DB error: {exc}'})


# ═══════════════════════════════════════════════════════════════════════════
#   Tournament — ELO-Scaled Matchmaking
# ═══════════════════════════════════════════════════════════════════════════

def _max_games_for_pair(elo_gap):
    """Scale max games per pair by ELO proximity."""
    if elo_gap < 50:  return 10
    if elo_gap < 100: return 7
    if elo_gap < 200: return 5
    if elo_gap < 300: return 3
    if elo_gap < 400: return 2
    return 0


def _run_tournament(game_id='snake', match_count=20):
    """Run a tournament round: schedule all matchups first, play them, then publish results.

    Phase 1 — LOAD: Fetch all agents + code once.
    Phase 2 — SCHEDULE: Generate all pairings (Swiss ELO-weighted).
    Phase 3 — PLAY: Run all matches (CPU-bound, no DB queries).
    Phase 4 — PUBLISH: Write all results to DB + push live buffer.
    """
    # ── Phase 1: Load ──
    agents = arena_get_leaderboard(game_id, limit=200)
    for a in agents:
        full = arena_get_agent(game_id, a['id'])
        if full:
            a['code'] = full.get('code', '')
    if len(agents) < 2:
        return 0

    # Pre-fetch pair counts in bulk
    pair_counts = {}
    for i, a1 in enumerate(agents):
        for a2 in agents[i+1:]:
            cnt = arena_count_pair_games(a1['id'], a2['id'])
            pair_counts[(a1['id'], a2['id'])] = cnt
            pair_counts[(a2['id'], a1['id'])] = cnt

    # ── Phase 2: Schedule ──
    schedule = []
    for _ in range(match_count):
        idx = random.randint(0, min(len(agents) - 1, 9))
        a1 = agents[idx]

        candidates = [a for a in agents if a['id'] != a1['id']]
        if not candidates:
            break

        weights = [1 / (abs(a1['elo'] - c['elo']) + 50) for c in candidates]
        total_w = sum(weights)
        r = random.random() * total_w
        cumul = 0
        a2 = candidates[0]
        for j, c in enumerate(candidates):
            cumul += weights[j]
            if r <= cumul:
                a2 = c
                break

        elo_gap = abs(a1['elo'] - a2['elo'])
        max_games = _max_games_for_pair(elo_gap)
        if max_games == 0:
            continue

        pair_key = (a1['id'], a2['id'])
        if pair_counts.get(pair_key, 0) >= max_games:
            continue

        code1 = a1.get('code', '')
        code2 = a2.get('code', '')
        if not code1 or not code2:
            continue

        schedule.append((a1, a2, code1, code2))
        # Increment local pair count to avoid scheduling same pair repeatedly
        pair_counts[pair_key] = pair_counts.get(pair_key, 0) + 1
        pair_counts[(a2['id'], a1['id'])] = pair_counts[pair_key]

    if not schedule:
        return 0

    # ── Phase 3: Play (CPU-bound, no DB) ──
    results = []
    for a1, a2, code1, code2 in schedule:
        result = _run_match(game_id, code1, code2)
        if result.get('error'):
            continue
        winner_id = a1['id'] if result['winner'] == 0 else (a2['id'] if result['winner'] == 1 else None)
        winner_name = a1['name'] if result['winner'] == 0 else (a2['name'] if result['winner'] == 1 else 'Draw')
        results.append((a1, a2, winner_id, winner_name, result))

    # ── Phase 4: Publish (batch DB writes) ──
    games_played = 0
    for a1, a2, winner_id, winner_name, result in results:
        try:
            arena_record_game(
                game_id=game_id,
                agent1_id=a1['id'],
                agent2_id=a2['id'],
                winner_id=winner_id,
                scores=result['scores'],
                turns=result['turns'],
                history=result.get('history'),
            )
            games_played += 1
            _push_live_match(a1, a2, winner_name, result.get('history', []), game_id)
        except Exception as e:
            print(f'[tournament:{game_id}] Record error: {e}')

    return games_played


# ═══════════════════════════════════════════════════════════════════════════
#   Heartbeat Threads
# ═══════════════════════════════════════════════════════════════════════════

def _has_new_feedback(game_id='snake'):
    try:
        from db_arena import arena_get_comments
        comments = arena_get_comments(game_id, limit=5)
        if not comments:
            return False
        newest = max(c['created_at'] for c in comments)
        if newest > _heartbeat_state['last_comment_check']:
            _heartbeat_state['last_comment_check'] = newest
            return True
        return False
    except Exception:
        return False


MATCH_DELAY = 0        # no delay — burn CPU on matches
TOURNAMENT_BATCH = 10  # matches per tick before checking state

def _warm_live_buffer(game_id='snake'):
    """Pre-fill live match buffer from DB on startup."""
    try:
        db_games = arena_get_recent_games_with_history(game_id, limit=_LIVE_BUFFER_SIZE)
        for g in db_games:
            history = g.get('history', [])
            if not history:
                continue
            entry = {
                'agent1': g['agent1_name'], 'agent2': g['agent2_name'],
                'agent1_elo': g.get('agent1_elo', 1000), 'agent2_elo': g.get('agent2_elo', 1000),
                'agent1_wl': f"{g.get('agent1_wins', 0)}W/{g.get('agent1_losses', 0)}L",
                'agent2_wl': f"{g.get('agent2_wins', 0)}W/{g.get('agent2_losses', 0)}L",
                'winner': g['winner_name'], 'gameId': game_id, 'history': history,
            }
            with _live_lock:
                _live_matches.append(entry)
        if _live_matches:
            print(f'[tournament] Warmed live buffer with {len(_live_matches)} games from DB')
    except Exception as exc:
        print(f'[tournament] Warm buffer failed (non-fatal): {exc}')


def _tournament_loop():
    """Single tournament thread — round-robins all games sequentially.

    One thread handles all games to avoid concurrent DB writes that corrupt SQLite.
    Each iteration: pick next game, run a batch of matches, move to next game.
    Only sleeps when ALL games had zero matches in a full round.
    """
    time.sleep(5)
    for game_id in _ACTIVE_GAMES:
        _warm_live_buffer(game_id)
        _seed_if_empty(game_id)
    print(f'[tournament] Single-threaded loop started (games: {_ACTIVE_GAMES})')

    totals = {gid: 0 for gid in _ACTIVE_GAMES}
    last_cleanup = {gid: time.time() for gid in _ACTIVE_GAMES}

    while _heartbeat_state['running']:
        any_played = False

        for game_id in _ACTIVE_GAMES:
            if not _heartbeat_state['running']:
                break

            try:
                played = _run_tournament(game_id=game_id, match_count=TOURNAMENT_BATCH)
                if played > 0:
                    totals[game_id] += played
                    _heartbeat_state['games_played'] += played
                    any_played = True
                    if totals[game_id] % 50 == 0:
                        print(f'[tournament:{game_id}] {totals[game_id]} games played')
            except Exception as e:
                _heartbeat_state['last_error'] = f'tournament({game_id}): {e}'
                print(f'[tournament:{game_id}] Error: {e}')
                traceback.print_exc()

            # Periodic cleanup — strip old history blobs every 10 min
            if time.time() - last_cleanup[game_id] > 600:
                try:
                    arena_strip_excess_history(game_id)
                except Exception:
                    pass
                last_cleanup[game_id] = time.time()

        # If no game had any matches this round, back off before retrying
        if not any_played:
            time.sleep(30)


_GAME_SEEDS = {
    'snake': {
        'seed_random': 'random_agent.py',
        'seed_greedy': 'greedy_agent.py',
        'seed_wall_avoider': 'wall_avoider.py',
    },
    'snake_random': {
        'seed_random': 'snake_random_random_agent.py',
        'seed_greedy': 'snake_random_greedy_agent.py',
        'seed_wall_avoider': 'snake_random_wall_avoider.py',
    },
    'snake_royale': {
        'seed_random': 'snake_royale_random_agent.py',
        'seed_greedy': 'snake_royale_greedy_agent.py',
        'seed_cautious': 'snake_royale_cautious_agent.py',
    },
    'snake_2v2': {
        'seed_random': 'snake_2v2_random_agent.py',
        'seed_greedy': 'snake_2v2_greedy_agent.py',
        'seed_team': 'snake_2v2_team_agent.py',
    },
    'chess960': {
        'chess960_seed_random': 'chess960_random_agent.py',
        'chess960_seed_greedy': 'chess960_greedy_agent.py',
        'chess960_seed_positional': 'chess960_positional_agent.py',
    },
    'othello': {
        'othello_seed_random': 'othello_random_agent.py',
        'othello_seed_greedy': 'othello_greedy_agent.py',
        'othello_seed_positional': 'othello_positional_agent.py',
    },
}


def _seed_if_empty(game_id):
    agents = arena_get_leaderboard(game_id, limit=1)
    if agents:
        return
    print(f'[tournament] No agents found for {game_id}, seeding baselines...')
    seeds = _GAME_SEEDS.get(game_id, {})
    for name, filename in seeds.items():
        path = os.path.join(_SEEDS_DIR, filename)
        if os.path.exists(path):
            with open(path) as f:
                code = f.read()
            result = arena_submit_agent(game_id, name, code, generation=0,
                                       contributor='seed', is_anchor=1)
            if isinstance(result, dict):
                print(f'[tournament] Seeded {name} for {game_id} (id={result["id"]})')
            else:
                print(f'[tournament] Seed {name} for {game_id} failed: {result}')
    print(f'[tournament] Seeding complete for {game_id}')


# ═══════════════════════════════════════════════════════════════════════════
#   AI Heartbeat Analysis — periodic LLM-powered status reports
# ═══════════════════════════════════════════════════════════════════════════

_evo_counts = {}  # per-game counter for analysis cadence


def _run_ai_analysis(api_key, game_id):
    """Use Haiku to analyze evolution state and post a status report as a heartbeat comment."""
    try:
        from db_arena import arena_get_llm_monitor_stats
        stats = arena_get_llm_monitor_stats()
    except Exception as exc:
        print(f'[analysis:{game_id}] Failed to get stats: {exc}')
        return

    # Build a data snapshot for the LLM
    agents = arena_get_leaderboard(game_id, limit=20)
    if not agents:
        return

    # Top agents summary
    top_agents = []
    for a in agents[:10]:
        win_rate = a['wins'] / max(a['games_played'], 1) * 100
        top_agents.append(
            f"  #{len(top_agents)+1} {a['name']} ELO={a['elo']:.0f} "
            f"W/L/D={a['wins']}/{a['losses']}/{a['draws']} "
            f"({win_rate:.0f}% WR, {a['games_played']} games)"
        )

    # Recent evolutions for this game
    recent = [s for s in stats.get('recent_sessions', []) if s['game_id'] == game_id][:15]
    evo_lines = []
    for s in recent:
        evo_lines.append(
            f"  Gen {s['generation']}: {s['model'].replace('claude-', '').replace('-20251001', '')} "
            f"→ {s['status']} ({s['agents_created']} agents, ${s['cost_usd']:.4f}, "
            f"{s['total_latency_ms']/1000:.1f}s)"
        )

    # Per-game stats
    game_stats = next((g for g in stats.get('by_game', []) if g['game_id'] == game_id), {})

    # Per-model stats for this game (from recent sessions)
    model_perf = {}
    for s in [r for r in stats.get('recent_sessions', []) if r['game_id'] == game_id]:
        m = s['model'].replace('claude-', '').replace('-20251001', '')
        if m not in model_perf:
            model_perf[m] = {'sessions': 0, 'agents': 0, 'cost': 0}
        model_perf[m]['sessions'] += 1
        model_perf[m]['agents'] += (s['agents_created'] or 0)
        model_perf[m]['cost'] += (s['cost_usd'] or 0)

    model_lines = []
    for m, p in sorted(model_perf.items(), key=lambda x: -x[1]['sessions']):
        rate = p['agents'] / max(p['sessions'], 1) * 100
        model_lines.append(f"  {m}: {p['sessions']} sessions, {p['agents']} agents ({rate:.0f}% creation rate), ${p['cost']:.4f}")

    data_block = f"""=== {game_id} Arena Status ===

Top Agents:
{chr(10).join(top_agents)}

Recent Evolutions (last {len(evo_lines)}):
{chr(10).join(evo_lines) if evo_lines else '  (none)'}

Model Performance:
{chr(10).join(model_lines) if model_lines else '  (none)'}

Totals for {game_id}: {game_stats.get('sessions', 0)} evolutions, {game_stats.get('agents', 0)} agents, ${game_stats.get('cost', 0):.4f} spent
Overall: {stats['all_time'].get('total_sessions', 0)} evolutions across all games, ${stats['all_time'].get('total_cost', 0):.4f} total
"""

    system = """You are the AI Heartbeat for an agent evolution arena. You analyze evolution data and post a brief status report.

Your report should be 3-5 bullet points covering:
- Which strategies are dominating and why (look at top ELO agents and their names for clues)
- Which models are most effective at creating agents (creation rate, cost efficiency)
- Any issues (high error rates, models failing to create agents, stagnation)
- What strategy direction the next evolutions should explore

Use markdown formatting: **bold** for agent names and key metrics, *italic* for strategy descriptions and commentary. Do NOT use headings (#), just bullet points with bold/italic emphasis. Be concise and specific. No pleasantries."""

    user = f"Analyze this evolution data and write a brief status report:\n\n{data_block}"

    try:
        import httpx as _httpx
        from llm_providers_anthropic import _anthropic_auth_headers
        headers = _anthropic_auth_headers(api_key)
        resp = _httpx.post(
            "https://api.anthropic.com/v1/messages",
            headers=headers,
            json={
                "model": "claude-haiku-4-5-20251001",
                "max_tokens": 1024,
                "system": system,
                "messages": [{"role": "user", "content": user}],
            },
            timeout=60.0,
        )
        if resp.status_code != 200:
            print(f'[analysis:{game_id}] API error: {resp.status_code}')
            return

        data = resp.json()
        text = data.get('content', [{}])[0].get('text', '')
        if not text:
            return

        # Truncate to reasonable comment length
        if len(text) > 1500:
            text = text[:1500] + '...'

        arena_post_comment(
            game_id, 'ai-heartbeat', 'AI Heartbeat',
            text, comment_type='heartbeat'
        )
        print(f'[analysis:{game_id}] Posted status report ({len(text)} chars)')

    except Exception as exc:
        print(f'[analysis:{game_id}] Error: {exc}')


def _evolution_loop_for_game(game_id, stagger_secs):
    """Per-game evolution loop. Each game gets its own thread, staggered to avoid API bursts."""
    time.sleep(10 + stagger_secs)
    _evo_counts[game_id] = 0
    print(f'[evolution:{game_id}] Started (stagger={stagger_secs}s, interval={HEARTBEAT_INTERVAL_NORMAL}s)')

    while _heartbeat_state['running']:
        if not EVOLUTION_ENABLED:
            time.sleep(HEARTBEAT_INTERVAL_NORMAL)
            continue

        api_key = os.environ.get('ARENA_CLAUDE_KEY', '')
        gemini_key = os.environ.get('GEMINI_API_KEY', '')
        if not api_key and not gemini_key:
            time.sleep(HEARTBEAT_INTERVAL_NORMAL)
            continue

        created = []
        try:
            tick_start = time.time()
            _heartbeat_state['ticks'] += 1
            print(f'[evolution:{game_id}] Tick starting...')
            created = _run_evolution(api_key, game_id=game_id)
            _heartbeat_state['agents_created'] += len(created)
            if created:
                print(f'[evolution:{game_id}] Created {len(created)} agent(s): {", ".join(created)}')
                try:
                    gen = _heartbeat_state['ticks']
                    msg = f"Gen {gen}: created {len(created)} new agent(s) — {', '.join(created)}"
                    arena_post_comment(game_id, 'ai-heartbeat', 'Heartbeat', msg,
                                       comment_type='heartbeat')
                except Exception:
                    pass
            elapsed = time.time() - tick_start
            _heartbeat_state['last_tick'] = time.time()
            _heartbeat_state['last_error'] = None
            print(f'[evolution:{game_id}] Done in {elapsed:.1f}s')
        except Exception as e:
            _heartbeat_state['last_error'] = f'{game_id}: {e}'
            print(f'[evolution:{game_id}] Error: {e}')
            traceback.print_exc()

        # Periodic AI analysis — post status report every N evolutions
        _evo_counts[game_id] = _evo_counts.get(game_id, 0) + 1
        if _evo_counts[game_id] % ANALYSIS_EVERY_N_EVOS == 0 and api_key:
            try:
                _run_ai_analysis(api_key, game_id)
            except Exception as exc:
                print(f'[analysis:{game_id}] Error (non-fatal): {exc}')

        if created or time.time() - _last_export_time >= EXPORT_INTERVAL:
            try:
                run_export(game_id)
            except Exception as exc:
                print(f'[evolution:{game_id}] Export error (non-fatal): {exc}')

        try:
            agent_count = len(arena_get_leaderboard(game_id, limit=200))
        except Exception:
            agent_count = 100  # default to normal interval on DB error
        if agent_count < 100:
            interval = HEARTBEAT_INTERVAL_FAST_FILL
        else:
            interval = HEARTBEAT_INTERVAL_NORMAL
        time.sleep(interval)


def _evolution_loop():
    """Spawns one evolution thread per game, staggered by EVOLUTION_STAGGER_SECS."""
    _heartbeat_state['last_comment_check'] = time.time()
    print(f'[evolution] Launching per-game evolution threads (games: {_ACTIVE_GAMES}, stagger: {EVOLUTION_STAGGER_SECS}s)')
    for i, game_id in enumerate(_ACTIVE_GAMES):
        stagger = i * EVOLUTION_STAGGER_SECS
        t = threading.Thread(
            target=_evolution_loop_for_game,
            args=(game_id, stagger),
            daemon=True,
            name=f'arena-evo-{game_id}',
        )
        t.start()


# ═══════════════════════════════════════════════════════════════════════════
#   Periodic Export — agents, games, program.md
# ═══════════════════════════════════════════════════════════════════════════

EXPORT_INTERVAL = 60 * 60  # every hour
EXPORT_MAX_KEPT = 5        # keep last 5 exports
_last_export_time = 0


def run_export(game_id='snake'):
    """Export all arena data to the Railway persistent volume (/data/arena_exports/).

    Permanent files (never deleted):
      agents/<name>.py  — each agent's code as a standalone Python file
      agents/index.json — all agent metadata (ELO, W/L/D, contributor)

    Rotating snapshots (last 5):
      snapshots/export_<ts>/games.json  — match outcomes
      snapshots/export_<ts>/program.md  — evolution program
    """
    global _last_export_time

    base_dir = os.path.join(os.environ.get('DB_DATA_DIR', '.'), 'arena_exports')
    agents_dir = os.path.join(base_dir, 'agents')
    snapshots_dir = os.path.join(base_dir, 'snapshots')
    os.makedirs(agents_dir, exist_ok=True)
    os.makedirs(snapshots_dir, exist_ok=True)

    ts = time.strftime('%Y%m%d_%H%M%S')

    try:
        # 1. Permanent: export each agent as a .py file + index.json
        agents = arena_get_leaderboard(game_id, limit=500)
        agent_index = []
        for a in agents:
            full = arena_get_agent(game_id, a['id'])
            code = full.get('code', '') if full else ''
            # Save code as individual .py file (permanent, overwrites with latest)
            if code and a.get('name'):
                safe_name = re.sub(r'[^\w]', '_', a['name'])
                with open(os.path.join(agents_dir, f'{safe_name}.py'), 'w') as f:
                    f.write(code)
            agent_index.append({
                'id': a['id'], 'name': a['name'],
                'elo': round(a['elo'], 1), 'peak_elo': round(a.get('peak_elo', a['elo']), 1),
                'games_played': a['games_played'],
                'wins': a['wins'], 'losses': a['losses'], 'draws': a['draws'],
                'contributor': a.get('contributor', ''),
                'is_anchor': a.get('is_anchor', 0),
            })
        with open(os.path.join(agents_dir, 'index.json'), 'w') as f:
            json.dump({'game_id': game_id, 'exported_at': ts, 'agents': agent_index}, f, indent=1)

        # 2. Rotating snapshot: match outcomes + program.md
        snap_dir = os.path.join(snapshots_dir, f'export_{ts}')
        os.makedirs(snap_dir, exist_ok=True)

        games = arena_get_recent_games(game_id, limit=10000)
        game_data = [{
            'id': g['id'],
            'agent1': g['agent1_name'], 'agent2': g['agent2_name'],
            'winner': g['winner_name'],
            'agent1_score': g['agent1_score'], 'agent2_score': g['agent2_score'],
            'turns': g['turns'], 'is_upset': g.get('is_upset', 0),
            'created_at': g.get('created_at', 0),
        } for g in games]
        with open(os.path.join(snap_dir, 'games.json'), 'w') as f:
            json.dump({'game_id': game_id, 'exported_at': ts, 'count': len(game_data), 'games': game_data}, f, indent=1)

        program_data = arena_get_program(game_id)
        program_content = (program_data.get('content') if program_data else '') or _load_default_program(game_id)
        with open(os.path.join(snap_dir, 'program.md'), 'w') as f:
            f.write(program_content)

        _last_export_time = time.time()
        print(f'[export] Saved {len(agent_index)} agents to {agents_dir}, snapshot to {snap_dir} ({len(game_data)} games)')

        # Rotate old snapshots
        existing = sorted([d for d in os.listdir(snapshots_dir) if d.startswith('export_')])
        while len(existing) > EXPORT_MAX_KEPT:
            old = existing.pop(0)
            old_path = os.path.join(snapshots_dir, old)
            for fname in os.listdir(old_path):
                os.remove(os.path.join(old_path, fname))
            os.rmdir(old_path)

    except Exception as exc:
        print(f'[export] Export failed: {exc}')
        traceback.print_exc()


def get_latest_export():
    """Return the latest export as a dict for the API endpoint."""
    base_dir = os.path.join(os.environ.get('DB_DATA_DIR', '.'), 'arena_exports')
    agents_dir = os.path.join(base_dir, 'agents')
    snapshots_dir = os.path.join(base_dir, 'snapshots')
    result = {}

    # Agent index (permanent)
    idx_path = os.path.join(agents_dir, 'index.json')
    if os.path.exists(idx_path):
        with open(idx_path) as f:
            result['agents'] = json.load(f)

    # Latest snapshot (games + program)
    if os.path.isdir(snapshots_dir):
        existing = sorted([d for d in os.listdir(snapshots_dir) if d.startswith('export_')])
        if existing:
            latest = os.path.join(snapshots_dir, existing[-1])
            result['snapshot'] = existing[-1]
            games_path = os.path.join(latest, 'games.json')
            if os.path.exists(games_path):
                with open(games_path) as f:
                    result['games'] = json.load(f)
            prog_path = os.path.join(latest, 'program.md')
            if os.path.exists(prog_path):
                with open(prog_path) as f:
                    result['program'] = f.read()

    return result if result else None


# ═══════════════════════════════════════════════════════════════════════════
#   Start / Stop / Status
# ═══════════════════════════════════════════════════════════════════════════

def start_arena_heartbeat():
    if _heartbeat_state.get('thread') and _heartbeat_state['thread'].is_alive():
        print('[heartbeat] Already running')
        return
    _heartbeat_state['running'] = True
    t1 = threading.Thread(target=_tournament_loop, daemon=True, name='arena-tournament')
    _heartbeat_state['thread'] = t1
    t1.start()
    t2 = threading.Thread(target=_evolution_loop, daemon=True, name='arena-evolution')
    _heartbeat_state['evo_thread'] = t2
    t2.start()


def stop_arena_heartbeat():
    _heartbeat_state['running'] = False


def get_heartbeat_status():
    t1 = _heartbeat_state.get('thread')
    t2 = _heartbeat_state.get('evo_thread')
    return {
        'running': _heartbeat_state['running'],
        'tournament_alive': t1.is_alive() if t1 else False,
        'evolution_alive': t2.is_alive() if t2 else False,
        'ticks': _heartbeat_state['ticks'],
        'last_tick': _heartbeat_state['last_tick'],
        'last_error': _heartbeat_state['last_error'],
        'agents_created': _heartbeat_state['agents_created'],
        'games_played': _heartbeat_state['games_played'],
        'has_api_key': bool(os.environ.get('ARENA_CLAUDE_KEY', '')),
        'snake_engine': _HAS_SNAKE_ENGINE,
        'chess960_engine': _HAS_CHESS960_ENGINE,
        'othello_engine': _HAS_OTHELLO_ENGINE,
        'active_games': _ACTIVE_GAMES,
    }
