# Author: Claude Opus 4.6
# Date: 2026-03-16 04:30
# PURPOSE: Server-side arena heartbeat — runs evolution + tournament every 15 minutes.
#   Uses ARENA_CLAUDE_KEY env var (Anthropic API key or OAuth token) for agent evolution.
#   Reuses snake_game.py engine from snake_autoresearch project for headless matches.
#   Runs in a daemon thread, limited to ~10% CPU (single-threaded, async-friendly).
#   Monitor via /api/arena/heartbeat/status endpoint.
# SRP/DRY check: Pass — reuses existing db_arena functions, snake engine, and LLM client

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

# Also check external snake_autoresearch for LLM client (evolution only)
_SNAKE_AUTORESEARCH_DIR = os.path.join(_SERVER_DIR, '..', '..', 'snake_autoresearch')
if os.path.isdir(_SNAKE_AUTORESEARCH_DIR):
    sys.path.insert(0, os.path.abspath(_SNAKE_AUTORESEARCH_DIR))

from db_arena import (
    arena_submit_agent,
    arena_record_game,
    arena_get_program,
    arena_get_leaderboard,
    arena_get_agent,
    arena_update_elo,
    arena_count_pair_games,
    MAX_STORED_GAMES_PER_PAIR,
    _db,
)


# ═══════════════════════════════════════════════════════════════════════════
#   Config
# ═══════════════════════════════════════════════════════════════════════════

HEARTBEAT_INTERVAL_NORMAL = 15 * 60  # 15 minutes
HEARTBEAT_INTERVAL_FAST = 60         # 1 minute when new user feedback exists
TOURNAMENT_GAMES_PER_TICK = 20
EVOLUTION_AGENTS_PER_TICK = 1
MAX_TOOL_ROUNDS = 6
ELO_START = 1000.0
ELO_K = 32

# Heartbeat state (for monitoring)
_heartbeat_state = {
    'running': False,
    'last_tick': None,
    'last_error': None,
    'ticks': 0,
    'last_comment_check': 0,  # timestamp of last comment we processed
    'agents_created': 0,
    'games_played': 0,
    'thread': None,
}


# ═══════════════════════════════════════════════════════════════════════════
#   Default Program.md (from snake_autoresearch)
# ═══════════════════════════════════════════════════════════════════════════

def _load_default_program():
    """Load default_program.md from bundled seeds (or external snake_autoresearch)."""
    # Try bundled copy first
    path = os.path.join(_SEEDS_DIR, 'default_program.md')
    if os.path.exists(path):
        with open(path) as f:
            return f.read()
    # Fallback to external
    path = os.path.join(_SNAKE_AUTORESEARCH_DIR, 'default_program.md')
    if os.path.exists(path):
        with open(path) as f:
            return f.read()
    # Inline fallback
    return """# Snake Agent Evolution Program

## Objective
Create snake agents that win competitive 2-player snake games on a 20x20 grid.

## Agent Interface
```python
def get_move(state):
    # state: grid_size, my_snake, my_direction, enemy_snake, enemy_direction, food, turn, prev_moves
    return 'UP' | 'DOWN' | 'LEFT' | 'RIGHT'
```

## Rules
- Coordinates are LISTS [x,y]. Only standard library allowed.
- Must return in <100ms. Directions: UP=(0,-1) DOWN=(0,1) LEFT=(-1,0) RIGHT=(1,0)
- Last snake alive wins. Head-on collision = draw. Max 350 turns: longer snake wins.
"""


# ═══════════════════════════════════════════════════════════════════════════
#   Snake Engine (imported from snake_autoresearch or inline fallback)
# ═══════════════════════════════════════════════════════════════════════════

try:
    from server.snake_engine import SnakeGame as _SnakeGameBase
    _HAS_SNAKE_ENGINE = True
except ImportError:
    try:
        from server.snake_engine import SnakeGame as _SnakeGameBase
        _HAS_SNAKE_ENGINE = True
    except ImportError:
        _HAS_SNAKE_ENGINE = False
        _SnakeGameBase = None


def _run_snake_match(code_a, code_b, max_turns=350):
    """Run a headless snake match between two Python agents. Returns winner/turns/scores."""
    if not _HAS_SNAKE_ENGINE:
        return {'winner': None, 'turns': 0, 'scores': [3, 3], 'error': 'No snake engine'}

    # Load agent functions from code strings
    fn_a = _load_agent_fn(code_a)
    fn_b = _load_agent_fn(code_b)
    if not fn_a or not fn_b:
        return {'winner': None, 'turns': 0, 'scores': [3, 3], 'error': 'Agent load failed'}

    game = _SnakeGameBase(width=20, height=20, max_turns=max_turns, food_count=3)
    try:
        result = game.run(fn_a, fn_b)
        return {
            'winner': result['winner'],  # 0, 1, or None (draw)
            'turns': result['turns'],
            'scores': result['scores'],
        }
    except Exception as e:
        return {'winner': None, 'turns': 0, 'scores': [3, 3], 'error': str(e)}


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
#   Evolution — LLM Tool-Calling Loop
# ═══════════════════════════════════════════════════════════════════════════

def _run_evolution(api_key, game_id='snake'):
    """Run one evolution cycle using Claude. Returns list of created agent names."""
    # Load program.md from DB, fall back to default
    program_data = arena_get_program(game_id)
    program_md = (program_data.get('content') if program_data else '') or _load_default_program()

    # Load current leaderboard
    agents = arena_get_leaderboard(game_id, limit=10)
    # Fetch code for top agent
    for a in agents[:1]:
        full = arena_get_agent(game_id, a['id'])
        if full:
            a['code'] = full.get('code', '')

    # Build prompts
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
        # Include top agent code
        top = agents[0]
        if top.get('code'):
            leaderboard_text += f"\nBest agent code ({top['name']}):\n```python\n{top['code']}\n```\n"

    user_prompt = f"""{leaderboard_text}
Create ONE agent with a unique name. Study the top agents and create a counter-strategy.
Call create_agent with name and full Python code."""

    # Use LLMToolClient from snake_autoresearch if available
    try:
        from llm_client import LLMToolClient
    except ImportError:
        print('[heartbeat] LLMToolClient not available, skipping evolution')
        return []

    # Determine if OAuth token or API key
    is_oauth = api_key.startswith('sk-ant-oat') if api_key else False
    client = LLMToolClient(
        provider='anthropic',
        model='claude-sonnet-4-6',
        api_key=api_key,
        max_tokens=8192,
    )

    created = []

    def tool_handler(name, args):
        return _handle_tool(name, args, game_id, agents, created)

    # Simplified tool definitions
    tools = [
        {
            'name': 'query_leaderboard',
            'description': 'Get current agent rankings with ELO, W/L/D, games played.',
            'parameters': {'type': 'object', 'properties': {}, 'required': []},
        },
        {
            'name': 'read_agent',
            'description': 'Read an agent\'s source code by name.',
            'parameters': {
                'type': 'object',
                'properties': {'agent_name': {'type': 'string'}},
                'required': ['agent_name'],
            },
        },
        {
            'name': 'create_agent',
            'description': 'Create a new agent. Code must define get_move(state). Auto-tested.',
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
            'name': 'test_match',
            'description': 'Run a test match between two agents.',
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

    try:
        client.tool_call_loop(
            system_prompt=system_prompt,
            user_message=user_prompt,
            tools=tools,
            handler=tool_handler,
            max_rounds=MAX_TOOL_ROUNDS,
        )
    except Exception as e:
        print(f'[heartbeat] Evolution error: {e}')
        traceback.print_exc()

    return created


def _handle_tool(name, args, game_id, agents, created_list):
    """Handle tool calls during evolution."""
    if name == 'query_leaderboard':
        if not agents:
            return json.dumps({'agents': [], 'message': 'No agents yet.'})
        return json.dumps([{
            'rank': i + 1, 'name': a['name'], 'elo': round(a['elo']),
            'wins': a['wins'], 'losses': a['losses'], 'draws': a['draws'],
            'games': a['games_played'],
        } for i, a in enumerate(agents[:10])])

    if name == 'read_agent':
        agent_name = args.get('agent_name', '')
        agent = next((a for a in agents if a['name'] == agent_name), None)
        if not agent:
            return json.dumps({'error': f"Agent '{agent_name}' not found"})
        return agent.get('code', '(no code)')

    if name == 'create_agent':
        agent_name = args.get('name', '')
        code = args.get('code', '')

        if not re.match(r'^[a-zA-Z_][a-zA-Z0-9_]*$', agent_name):
            return json.dumps({'error': 'Invalid name. Letters, digits, underscores only.'})

        # Validate code
        fn = _load_agent_fn(code)
        if not fn:
            return json.dumps({'error': 'Code validation failed: get_move function not found or syntax error.'})

        # Safety check
        forbidden = ['import os', 'import subprocess', 'import socket', 'import sys',
                      'open(', '__import__', 'exec(', 'eval(']
        for pat in forbidden:
            if pat in code:
                return json.dumps({'error': f'Forbidden pattern: {pat}'})

        # Quick test run
        try:
            from server.snake_engine import SnakeGame
            game = SnakeGame(width=20, height=20, max_turns=10, food_count=3)
            game.setup()
            state = game.get_state(0)
            start = time.time()
            result = fn(state)
            elapsed = time.time() - start
            if elapsed > 0.1:
                return json.dumps({'error': f'Too slow: {elapsed*1000:.0f}ms (max 100ms)'})
            if result not in ('UP', 'DOWN', 'LEFT', 'RIGHT'):
                return json.dumps({'error': f'Invalid return value: {result}'})
        except Exception as e:
            return json.dumps({'error': f'Test run failed: {e}'})

        # Store in DB
        try:
            result = arena_submit_agent(game_id, agent_name, code, contributor='arena_heartbeat')
            if isinstance(result, str):
                return json.dumps({'error': result})
            created_list.append(agent_name)

            # Quick test match against a random existing agent
            test_note = ''
            if agents:
                opp = random.choice(agents[:5])
                result = _run_snake_match(code, opp.get('code', ''))
                if result.get('winner') == 0:
                    test_note = f" Quick test vs {opp['name']}: WIN in {result['turns']} turns."
                elif result.get('winner') == 1:
                    test_note = f" Quick test vs {opp['name']}: LOSS in {result['turns']} turns."
                else:
                    test_note = f" Quick test vs {opp['name']}: DRAW in {result['turns']} turns."

            return json.dumps({'success': True, 'message': f"Agent '{agent_name}' created (ELO: 1000).{test_note}"})
        except Exception as e:
            return json.dumps({'error': f'DB error: {e}'})

    if name == 'test_match':
        a1_name = args.get('agent1_name', '')
        a2_name = args.get('agent2_name', '')
        a1 = next((a for a in agents if a['name'] == a1_name), None)
        a2 = next((a for a in agents if a['name'] == a2_name), None)
        if not a1:
            return json.dumps({'error': f"Agent '{a1_name}' not found"})
        if not a2:
            return json.dumps({'error': f"Agent '{a2_name}' not found"})
        result = _run_snake_match(a1.get('code', ''), a2.get('code', ''))
        winner_name = a1_name if result['winner'] == 0 else (a2_name if result['winner'] == 1 else 'Draw')
        return json.dumps({'winner': winner_name, 'turns': result['turns'], 'scores': result['scores']})

    return json.dumps({'error': f'Unknown tool: {name}'})


# ═══════════════════════════════════════════════════════════════════════════
#   Tournament — Run Matches + Update ELO
# ═══════════════════════════════════════════════════════════════════════════

def _run_tournament(game_id='snake', match_count=20):
    """Run a tournament round. Swiss matchmaking, ELO updates, results stored in DB.
    arena_record_game handles stats + ELO updates internally."""
    agents = arena_get_leaderboard(game_id, limit=200)
    # Fetch code for all agents
    for a in agents:
        full = arena_get_agent(game_id, a['id'])
        if full:
            a['code'] = full.get('code', '')
    if len(agents) < 2:
        return 0

    games_played = 0

    for _ in range(match_count):
        # Swiss matchmaking: pick from top 10, pair with similar ELO
        idx = random.randint(0, min(len(agents) - 1, 9))
        a1 = agents[idx]

        candidates = [a for a in agents if a['id'] != a1['id']]
        if not candidates:
            break

        # Weight toward similar ELO
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

        if abs(a1['elo'] - a2['elo']) > 400:
            continue

        # Skip pairs that already played 10+ games — enough ELO signal
        if arena_count_pair_games(a1['id'], a2['id']) >= MAX_STORED_GAMES_PER_PAIR:
            continue

        code1 = a1.get('code', '')
        code2 = a2.get('code', '')
        if not code1 or not code2:
            continue

        result = _run_snake_match(code1, code2)
        if result.get('error'):
            continue

        winner_id = a1['id'] if result['winner'] == 0 else (a2['id'] if result['winner'] == 1 else None)

        try:
            # arena_record_game handles stats + ELO updates internally
            arena_record_game(
                game_id=game_id,
                agent1_id=a1['id'],
                agent2_id=a2['id'],
                winner_id=winner_id,
                scores=result['scores'],
                turns=result['turns'],
            )
            games_played += 1
            # Throttle: sleep 200ms between matches to stay under ~10% CPU
            time.sleep(0.2)
        except Exception as e:
            print(f'[heartbeat] Game record error: {e}')

    return games_played


# ═══════════════════════════════════════════════════════════════════════════
#   Heartbeat Thread
# ═══════════════════════════════════════════════════════════════════════════

def _has_new_feedback(game_id='snake'):
    """Check if there are strategy discussion comments newer than our last check."""
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


# ═══════════════════════════════════════════════════════════════════════════
#   Continuous Tournament Runner — always scheduling games
# ═══════════════════════════════════════════════════════════════════════════

MATCH_DELAY = 0.5  # seconds between matches (~2 games/sec, ~5% CPU)

def _tournament_loop():
    """Continuously run matches between existing agents. Separate from evolution."""
    print('[tournament] Continuous tournament runner started')

    # Wait a few seconds for DB to be ready
    time.sleep(5)

    # Seed agents if DB is empty
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
                    # Log why on first zero — helps debug
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
    """Seed the 3 baseline agents if the DB has no agents for this game."""
    agents = arena_get_leaderboard(game_id, limit=1)
    if agents:
        return

    print(f'[tournament] No agents found for {game_id}, seeding baselines...')

    # Use bundled seeds (server/arena_seeds/), fallback to external
    seed_dir = _SEEDS_DIR
    if not os.path.isdir(seed_dir):
        seed_dir = os.path.join(_SNAKE_AUTORESEARCH_DIR, 'agents', 'seed')
    seeds = {
        'seed_random': os.path.join(seed_dir, 'random_agent.py'),
        'seed_greedy': os.path.join(seed_dir, 'greedy_agent.py'),
        'seed_wall_avoider': os.path.join(seed_dir, 'wall_avoider.py'),
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


# ═══════════════════════════════════════════════════════════════════════════
#   Evolution Heartbeat — creates new agents via LLM
# ═══════════════════════════════════════════════════════════════════════════

def _evolution_loop():
    """Evolution heartbeat — calls Claude to create new agents.
    Normal: 15-min interval. Speeds up to 1-min when new user feedback exists."""
    _heartbeat_state['last_comment_check'] = time.time()
    print('[evolution] Evolution heartbeat started (15min normal, 1min on feedback)')

    # Wait for tournament to seed agents first
    time.sleep(10)

    while _heartbeat_state['running']:
        api_key = os.environ.get('ARENA_CLAUDE_KEY', '')
        if not api_key:
            # No key — sleep and check again later
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

        interval = HEARTBEAT_INTERVAL_FAST if _has_new_feedback('snake') else HEARTBEAT_INTERVAL_NORMAL
        time.sleep(interval)


# ═══════════════════════════════════════════════════════════════════════════
#   Start / Stop / Status
# ═══════════════════════════════════════════════════════════════════════════

def start_arena_heartbeat():
    """Start both the tournament runner and evolution heartbeat. Call once at server boot."""
    if _heartbeat_state.get('thread') and _heartbeat_state['thread'].is_alive():
        print('[heartbeat] Already running')
        return

    _heartbeat_state['running'] = True

    # Thread 1: continuous tournament (always running games)
    t1 = threading.Thread(target=_tournament_loop, daemon=True, name='arena-tournament')
    _heartbeat_state['thread'] = t1
    t1.start()

    # Thread 2: evolution heartbeat (creates new agents via LLM)
    t2 = threading.Thread(target=_evolution_loop, daemon=True, name='arena-evolution')
    _heartbeat_state['evo_thread'] = t2
    t2.start()


def stop_arena_heartbeat():
    """Signal both threads to stop."""
    _heartbeat_state['running'] = False


def get_heartbeat_status():
    """Get current heartbeat status for monitoring."""
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
