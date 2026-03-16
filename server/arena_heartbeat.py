# Author: Claude Opus 4.6
# Date: 2026-03-15 22:00
# PURPOSE: Server-side arena heartbeat — runs evolution + tournament continuously.
#   Uses ARENA_CLAUDE_KEY env var (Anthropic API key or OAuth token) for agent evolution.
#   Uses server/arena_tool_runner.py for LLM tool-calling loops (no external deps).
#   Runs in two daemon threads: tournament (continuous) + evolution (5-min cycle).
#   Monitor via /api/arena/heartbeat/status endpoint.
# SRP/DRY check: Pass — reuses existing db_arena functions, snake engine, arena_tool_runner

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
    MAX_STORED_GAMES_PER_PAIR,
    _db,
)


# ═══════════════════════════════════════════════════════════════════════════
#   Config
# ═══════════════════════════════════════════════════════════════════════════

HEARTBEAT_INTERVAL_FAST_FILL = 2 * 60   # 2 minutes until 100 agents
HEARTBEAT_INTERVAL_NORMAL = 10 * 60    # 10 minutes after 100 agents
HEARTBEAT_INTERVAL_FAST = 60         # 1 minute when new user feedback exists
TOURNAMENT_GAMES_PER_TICK = 20
EVOLUTION_AGENTS_PER_TICK = 1
MAX_TOOL_ROUNDS = 6
ELO_START = 1000.0
ELO_K = 32

# Rotate through Claude models for agent evolution
_EVOLUTION_MODELS = [
    ('claude-haiku-4-5-20251001', 'claude-haiku-4.5'),
    ('claude-sonnet-4-6', 'claude-sonnet-4.6'),
    ('claude-opus-4-6', 'claude-opus-4.6'),
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
_LIVE_BUFFER_SIZE = 4
_live_matches = []
_live_lock = threading.Lock()


# ═══════════════════════════════════════════════════════════════════════════
#   Default Program.md
# ═══════════════════════════════════════════════════════════════════════════

def _load_default_program():
    """Load default_program.md from bundled seeds."""
    path = os.path.join(_SEEDS_DIR, 'default_program.md')
    if os.path.exists(path):
        with open(path) as f:
            return f.read()
    return "Create snake agents with a get_move(state) function."


# ═══════════════════════════════════════════════════════════════════════════
#   Snake Engine
# ═══════════════════════════════════════════════════════════════════════════

try:
    from server.snake_engine import SnakeGame as _SnakeGameBase
    _HAS_SNAKE_ENGINE = True
except ImportError:
    _HAS_SNAKE_ENGINE = False
    _SnakeGameBase = None


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
    Primary: in-memory ring buffer. Fallback: recent DB games with history."""
    with _live_lock:
        if _live_matches:
            return list(_live_matches)

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

def _safe_import(name, *args, **kwargs):
    """Restricted import — only allow safe standard library modules."""
    if name in _ALLOWED_MODULES:
        return __builtins__['__import__'](name, *args, **kwargs) if isinstance(__builtins__, dict) else __import__(name, *args, **kwargs)
    raise ImportError(f"Module '{name}' is not allowed")

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
                'isinstance': isinstance, 'type': type, 'print': lambda *a, **k: None,
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
    """Run one evolution cycle. Rotates Haiku/Sonnet/Opus each generation."""
    generation = arena_increment_generation(game_id)

    model_id, model_label = _EVOLUTION_MODELS[(generation - 1) % len(_EVOLUTION_MODELS)]
    print(f'[evolution] Gen {generation} using {model_label} ({model_id})')

    program_data = arena_get_program(game_id)
    program_md = (program_data.get('content') if program_data else '') or _load_default_program()

    agents = arena_get_leaderboard(game_id, limit=10)
    for a in agents[:1]:
        full = arena_get_agent(game_id, a['id'])
        if full:
            a['code'] = full.get('code', '')

    system_prompt = program_md + """

Call create_agent with name and complete Python code.
The agent must have a get_move(state) function.
Only standard library imports (random, math, collections).
Must return in <100ms.
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

    from server.arena_tool_runner import run_tool_loop

    created = []

    def tool_handler(name, args):
        return _handle_tool(name, args, game_id, agents, created, contributor=model_label)

    try:
        run_tool_loop(
            api_key=api_key,
            system_prompt=system_prompt,
            user_message=user_prompt,
            tools=_EVOLUTION_TOOLS,
            handler=tool_handler,
            model=model_id,
            max_tokens=8192,
            max_rounds=MAX_TOOL_ROUNDS,
        )
    except Exception as e:
        print(f'[heartbeat] Evolution error: {e}')
        traceback.print_exc()

    return created


def _handle_tool(name, args, game_id, agents, created_list, contributor='arena_heartbeat'):
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
        return _tool_create_agent(args, game_id, agents, created_list, contributor=contributor)

    if name == 'edit_current_agent':
        agent_name = args.get('name', '')
        code = args.get('code', '')
        if agent_name not in created_list:
            return json.dumps({'error': f"Can only edit agents created THIS round. '{agent_name}' was not."})
        test_result = _validate_agent_code(code)
        if test_result:
            return json.dumps({'error': test_result})
        agent = arena_get_agent_by_name(game_id, agent_name)
        if not agent:
            return json.dumps({'error': f"Agent '{agent_name}' not found in DB"})
        try:
            with _db() as conn:
                conn.execute('UPDATE arena_agents SET code = ? WHERE id = ?', (code, agent['id']))
            return json.dumps({'success': True, 'message': f"Agent '{agent_name}' updated and passed tests."})
        except Exception as exc:
            return json.dumps({'error': f'DB error: {exc}'})

    if name == 'run_test':
        agent_name = args.get('agent_name', '')
        agent = arena_get_agent_by_name(game_id, agent_name)
        if not agent:
            return json.dumps({'error': f"Agent '{agent_name}' not found"})
        error = _validate_agent_code(agent.get('code', ''))
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
        result = _run_snake_match(a1.get('code', ''), a2.get('code', ''))
        winner_name = a1_name if result['winner'] == 0 else (a2_name if result['winner'] == 1 else 'Draw')
        return json.dumps({'winner': winner_name, 'turns': result['turns'], 'scores': result['scores']})

    return json.dumps({'error': f'Unknown tool: {name}'})


# ═══════════════════════════════════════════════════════════════════════════
#   Agent Validation — 12 scenarios
# ═══════════════════════════════════════════════════════════════════════════

_VALID_MOVES = {'UP', 'DOWN', 'LEFT', 'RIGHT'}

_TEST_STATES = [
    ('center', {'grid_size': (20, 20), 'my_snake': [[10, 10], [9, 10], [8, 10]], 'my_direction': 'RIGHT', 'enemy_snake': [[15, 15], [16, 15], [17, 15]], 'enemy_direction': 'LEFT', 'food': [[5, 5], [12, 8], [18, 2]], 'turn': 50, 'prev_moves': []}),
    ('near_top_wall', {'grid_size': (20, 20), 'my_snake': [[10, 0], [10, 1], [10, 2]], 'my_direction': 'UP', 'enemy_snake': [[15, 15], [16, 15], [17, 15]], 'enemy_direction': 'LEFT', 'food': [[5, 5], [12, 8]], 'turn': 30, 'prev_moves': []}),
    ('near_bottom_wall', {'grid_size': (20, 20), 'my_snake': [[10, 19], [10, 18], [10, 17]], 'my_direction': 'DOWN', 'enemy_snake': [[5, 5], [4, 5], [3, 5]], 'enemy_direction': 'RIGHT', 'food': [[15, 10]], 'turn': 100, 'prev_moves': []}),
    ('near_left_wall', {'grid_size': (20, 20), 'my_snake': [[0, 10], [1, 10], [2, 10]], 'my_direction': 'LEFT', 'enemy_snake': [[19, 10], [18, 10], [17, 10]], 'enemy_direction': 'RIGHT', 'food': [[10, 10]], 'turn': 75, 'prev_moves': []}),
    ('corner_top_left', {'grid_size': (20, 20), 'my_snake': [[0, 0], [1, 0], [2, 0]], 'my_direction': 'LEFT', 'enemy_snake': [[19, 19], [18, 19], [17, 19]], 'enemy_direction': 'LEFT', 'food': [[10, 10]], 'turn': 10, 'prev_moves': []}),
    ('corner_bottom_right', {'grid_size': (20, 20), 'my_snake': [[19, 19], [18, 19], [17, 19]], 'my_direction': 'RIGHT', 'enemy_snake': [[0, 0], [1, 0], [2, 0]], 'enemy_direction': 'RIGHT', 'food': [[10, 10]], 'turn': 10, 'prev_moves': []}),
    ('long_snake', {'grid_size': (20, 20), 'my_snake': [[10, 10], [10, 11], [10, 12], [10, 13], [10, 14], [10, 15], [10, 16], [10, 17], [9, 17], [8, 17], [7, 17], [6, 17], [5, 17], [4, 17], [3, 17]], 'my_direction': 'UP', 'enemy_snake': [[5, 5], [4, 5], [3, 5]], 'enemy_direction': 'RIGHT', 'food': [[15, 5], [2, 2], [18, 18]], 'turn': 200, 'prev_moves': []}),
    ('enemy_adjacent', {'grid_size': (20, 20), 'my_snake': [[10, 10], [9, 10], [8, 10]], 'my_direction': 'RIGHT', 'enemy_snake': [[12, 10], [13, 10], [14, 10]], 'enemy_direction': 'LEFT', 'food': [[10, 5], [10, 15]], 'turn': 80, 'prev_moves': []}),
    ('enemy_dead', {'grid_size': (20, 20), 'my_snake': [[10, 10], [9, 10], [8, 10]], 'my_direction': 'RIGHT', 'enemy_snake': [], 'enemy_direction': None, 'food': [[15, 15], [5, 5]], 'turn': 300, 'prev_moves': []}),
    ('tight_space', {'grid_size': (20, 20), 'my_snake': [[5, 5], [5, 6], [5, 7], [4, 7], [3, 7], [3, 6], [3, 5], [4, 5]], 'my_direction': 'UP', 'enemy_snake': [[15, 15], [16, 15]], 'enemy_direction': 'LEFT', 'food': [[10, 10]], 'turn': 150, 'prev_moves': []}),
    ('start_of_game', {'grid_size': (20, 20), 'my_snake': [[3, 3], [2, 3], [1, 3]], 'my_direction': 'RIGHT', 'enemy_snake': [[16, 16], [17, 16], [18, 16]], 'enemy_direction': 'LEFT', 'food': [[10, 5], [7, 12], [15, 3]], 'turn': 0, 'prev_moves': []}),
    ('late_game', {'grid_size': (20, 20), 'my_snake': [[10, 10], [10, 11], [10, 12], [10, 13], [10, 14], [10, 15]], 'my_direction': 'UP', 'enemy_snake': [[5, 5], [5, 6], [5, 7], [5, 8], [5, 9], [5, 10], [5, 11]], 'enemy_direction': 'UP', 'food': [[18, 18], [1, 1], [15, 3]], 'turn': 450, 'prev_moves': []}),
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


def _tool_create_agent(args, game_id, agents, created_list, contributor='arena_heartbeat'):
    """Handle the create_agent tool call."""
    agent_name = args.get('name', '')
    code = args.get('code', '')

    if not re.match(r'^[a-zA-Z_][a-zA-Z0-9_]*$', agent_name):
        return json.dumps({'error': 'Invalid name. Letters, digits, underscores only.'})

    error = _validate_agent_code(code)
    if error:
        return json.dumps({'error': f'Code validation failed: {error}'})

    try:
        result = arena_submit_agent(game_id, agent_name, code, contributor=contributor)
        if isinstance(result, str):
            return json.dumps({'error': result})
        created_list.append(agent_name)

        test_note = ''
        if agents:
            opp = random.choice(agents[:5])
            match_result = _run_snake_match(code, opp.get('code', ''))
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
    """Run a tournament round. Swiss matchmaking weighted by ELO proximity."""
    agents = arena_get_leaderboard(game_id, limit=200)
    for a in agents:
        full = arena_get_agent(game_id, a['id'])
        if full:
            a['code'] = full.get('code', '')
    if len(agents) < 2:
        return 0

    games_played = 0

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

        if arena_count_pair_games(a1['id'], a2['id']) >= max_games:
            continue

        code1 = a1.get('code', '')
        code2 = a2.get('code', '')
        if not code1 or not code2:
            continue

        result = _run_snake_match(code1, code2)
        if result.get('error'):
            continue

        winner_id = a1['id'] if result['winner'] == 0 else (a2['id'] if result['winner'] == 1 else None)
        winner_name = a1['name'] if result['winner'] == 0 else (a2['name'] if result['winner'] == 1 else 'Draw')

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

            time.sleep(0.2)
        except Exception as e:
            print(f'[heartbeat] Game record error: {e}')

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


MATCH_DELAY = 0.5

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
    print('[tournament] Continuous tournament runner started')
    time.sleep(5)
    _warm_live_buffer('snake')
    _seed_if_empty('snake')

    consecutive_zeros = 0
    while _heartbeat_state['running']:
        try:
            games = _run_tournament(game_id='snake', match_count=1)
            if games > 0:
                _heartbeat_state['games_played'] += games
                consecutive_zeros = 0
                if _heartbeat_state['games_played'] % 10 == 0:
                    print(f'[tournament] {_heartbeat_state["games_played"]} total games played')
            else:
                consecutive_zeros += 1
                if consecutive_zeros == 1:
                    agents = arena_get_leaderboard('snake', limit=10)
                    _heartbeat_state['last_error'] = f'tournament: 0 games, {len(agents)} agents loaded'
                    print(f'[tournament] No games played ({len(agents)} agents). Retrying in 10s...')
                time.sleep(10)
                continue
        except Exception as e:
            _heartbeat_state['last_error'] = f'tournament: {e}'
            print(f'[tournament] Error: {e}')
            traceback.print_exc()
            time.sleep(10)
            continue
        time.sleep(MATCH_DELAY)


def _seed_if_empty(game_id):
    agents = arena_get_leaderboard(game_id, limit=1)
    if agents:
        return
    print(f'[tournament] No agents found for {game_id}, seeding baselines...')
    seeds = {
        'seed_random': os.path.join(_SEEDS_DIR, 'random_agent.py'),
        'seed_greedy': os.path.join(_SEEDS_DIR, 'greedy_agent.py'),
        'seed_wall_avoider': os.path.join(_SEEDS_DIR, 'wall_avoider.py'),
    }
    for name, path in seeds.items():
        if os.path.exists(path):
            with open(path) as f:
                code = f.read()
            result = arena_submit_agent(game_id, name, code, generation=0,
                                       contributor='seed', is_anchor=1)
            if isinstance(result, dict):
                print(f'[tournament] Seeded {name} (id={result["id"]})')
            else:
                print(f'[tournament] Seed {name} failed: {result}')
    print(f'[tournament] Seeding complete')


def _evolution_loop():
    _heartbeat_state['last_comment_check'] = time.time()
    print('[evolution] Evolution heartbeat started (5min normal, 1min on feedback)')
    time.sleep(10)

    while _heartbeat_state['running']:
        api_key = os.environ.get('ARENA_CLAUDE_KEY', '')
        if not api_key:
            time.sleep(HEARTBEAT_INTERVAL_NORMAL)
            continue
        try:
            tick_start = time.time()
            _heartbeat_state['ticks'] += 1
            has_feedback = _has_new_feedback('snake')
            if has_feedback:
                print(f'[evolution] Tick #{_heartbeat_state["ticks"]} (FAST — new user feedback)')
            else:
                print(f'[evolution] Tick #{_heartbeat_state["ticks"]} starting...')
            created = _run_evolution(api_key, game_id='snake')
            _heartbeat_state['agents_created'] += len(created)
            if created:
                print(f'[evolution] Created {len(created)} agent(s): {", ".join(created)}')
            elapsed = time.time() - tick_start
            _heartbeat_state['last_tick'] = time.time()
            _heartbeat_state['last_error'] = None
            print(f'[evolution] Tick #{_heartbeat_state["ticks"]} done in {elapsed:.1f}s')
        except Exception as e:
            _heartbeat_state['last_error'] = str(e)
            print(f'[evolution] Tick error: {e}')
            traceback.print_exc()
        # 2min until 100 agents, then 10min. 1min if new user feedback.
        agent_count = len(arena_get_leaderboard('snake', limit=200))
        if _has_new_feedback('snake'):
            interval = HEARTBEAT_INTERVAL_FAST
        elif agent_count < 100:
            interval = HEARTBEAT_INTERVAL_FAST_FILL
        else:
            interval = HEARTBEAT_INTERVAL_NORMAL
        time.sleep(interval)


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
    }
