# Author: Claude Opus 4.6
# Date: 2026-03-17 23:00
# PURPOSE: CLI tool for offline arena agent generation. Fetches Program.md and leaderboard
#   from the server, runs a local LLM tool-calling loop (any provider via offline_llm.py),
#   validates generated agents locally, and uploads them to the arena server.
#   Supports Anthropic, OpenAI, Gemini, and LM Studio providers.
# SRP/DRY check: Pass — CLI orchestration only, LLM calls in offline_llm.py

import argparse
import json
import os
import re
import sys
import time

import httpx

# ═══════════════════════════════════════════════════════════════════════════
#   Local validation / match imports (optional — graceful degradation)
# ═══════════════════════════════════════════════════════════════════════════

try:
    from server.arena_heartbeat import _validate_code, _load_agent_fn
    HAS_LOCAL_VALIDATION = True
except ImportError:
    HAS_LOCAL_VALIDATION = False

try:
    from server.arena_heartbeat import _run_match
    HAS_LOCAL_MATCH = True
except ImportError:
    HAS_LOCAL_MATCH = False


# ═══════════════════════════════════════════════════════════════════════════
#   Constants
# ═══════════════════════════════════════════════════════════════════════════

VALID_GAMES = ('snake', 'snake_random', 'snake_royale', 'snake_2v2', 'chess960', 'othello')
VALID_PROVIDERS = ('anthropic', 'openai', 'gemini', 'lmstudio', 'ollama')
DEFAULT_SERVER = 'https://arc3.sonpham.net'
DEFAULT_LMSTUDIO_URL = 'http://localhost:1234/v1'
DEFAULT_MAX_ROUNDS = 6
DEFAULT_MAX_TOKENS = 8192
HTTP_TIMEOUT = 30.0

PROVIDER_DEFAULTS = {
    'anthropic': 'claude-sonnet-4-6',
    'openai': 'gpt-4o',
    'gemini': 'gemini-2.5-flash',
    'lmstudio': 'local-model',
    'ollama': 'qwen3:72b',
}


# ═══════════════════════════════════════════════════════════════════════════
#   Tool Definitions (subset of arena_heartbeat tools)
# ═══════════════════════════════════════════════════════════════════════════

OFFLINE_TOOLS = [
    {
        'name': 'create_agent',
        'description': 'Create a new agent. Code must define get_move(state). Auto-tested against scenarios.',
        'parameters': {
            'type': 'object',
            'properties': {
                'name': {'type': 'string', 'description': 'Unique name (letters/digits/underscores). Will be auto-prefixed with offline_ if needed.'},
                'code': {'type': 'string', 'description': 'Full Python source with get_move(state)'},
            },
            'required': ['name', 'code'],
        },
    },
    {
        'name': 'read_agent',
        'description': "Read an agent's full source code by name from the server.",
        'parameters': {
            'type': 'object',
            'properties': {'agent_name': {'type': 'string'}},
            'required': ['agent_name'],
        },
    },
    {
        'name': 'run_test',
        'description': 'Run local validation tests on an agent (syntax, safety, timing, return values).',
        'parameters': {
            'type': 'object',
            'properties': {'agent_name': {'type': 'string'}},
            'required': ['agent_name'],
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
    {
        'name': 'query_db',
        'description': 'Query the arena database. Not supported offline — use read_agent or get_agent_games instead.',
        'parameters': {
            'type': 'object',
            'properties': {'sql': {'type': 'string', 'description': 'SQL SELECT query'}},
            'required': ['sql'],
        },
    },
    {
        'name': 'get_agent_games',
        'description': "Get an agent's recent game results with scores and turns.",
        'parameters': {
            'type': 'object',
            'properties': {
                'agent_name': {'type': 'string'},
                'limit': {'type': 'integer', 'description': 'Number of games (default 5)'},
            },
            'required': ['agent_name'],
        },
    },
]


# ═══════════════════════════════════════════════════════════════════════════
#   Data Fetching
# ═══════════════════════════════════════════════════════════════════════════

def fetch_program(server_url, game_id):
    """GET /api/arena/program/<game_id> -> returns program.md content."""
    url = f'{server_url}/api/arena/program/{game_id}'
    try:
        resp = httpx.get(url, timeout=HTTP_TIMEOUT)
        resp.raise_for_status()
        data = resp.json()
        content = data.get('content', '')
        if content:
            return content
        # Fall back to versions if content is empty
        versions = data.get('versions', [])
        for v in versions:
            if v.get('applied') == 1 and v.get('content'):
                return v['content']
        return ''
    except Exception as exc:
        print(f'[offline] WARNING: Failed to fetch program from server: {exc}')
        return ''


def fetch_leaderboard(server_url, game_id, limit=10):
    """GET /api/arena/agents/<game_id> -> returns list of agents with elo, name, etc."""
    url = f'{server_url}/api/arena/agents/{game_id}'
    try:
        resp = httpx.get(url, timeout=HTTP_TIMEOUT)
        resp.raise_for_status()
        agents = resp.json()
        return agents[:limit]
    except Exception as exc:
        print(f'[offline] WARNING: Failed to fetch leaderboard from server: {exc}')
        return []


def fetch_agent_code(server_url, game_id, agent_id):
    """GET /api/arena/agents/<game_id>/<agent_id> -> returns agent dict with code."""
    url = f'{server_url}/api/arena/agents/{game_id}/{agent_id}'
    try:
        resp = httpx.get(url, timeout=HTTP_TIMEOUT)
        resp.raise_for_status()
        return resp.json()
    except Exception as exc:
        print(f'[offline] WARNING: Failed to fetch agent {agent_id}: {exc}')
        return None


def fetch_agent_games(server_url, game_id, agent_id, limit=5):
    """GET /api/arena/agents/<game_id>/<agent_id>/games -> returns agent + recent games."""
    url = f'{server_url}/api/arena/agents/{game_id}/{agent_id}/games'
    try:
        resp = httpx.get(url, timeout=HTTP_TIMEOUT, params={'limit': limit})
        resp.raise_for_status()
        return resp.json()
    except Exception as exc:
        print(f'[offline] WARNING: Failed to fetch agent games: {exc}')
        return None


def upload_agent(server_url, game_id, name, code, provider, model):
    """POST /api/arena/agents/<game_id>/offline -> uploads the agent."""
    url = f'{server_url}/api/arena/agents/{game_id}/offline'
    payload = {
        'name': name,
        'code': code,
        'provider': provider,
        'model': model,
    }
    try:
        resp = httpx.post(url, json=payload, timeout=HTTP_TIMEOUT)
        data = resp.json()
        if resp.status_code >= 400:
            return {'error': data.get('error', f'HTTP {resp.status_code}')}
        return data
    except httpx.ConnectError:
        return {'error': f'Cannot connect to server at {server_url}. Is it running?'}
    except Exception as exc:
        return {'error': f'Upload failed: {exc}'}


# ═══════════════════════════════════════════════════════════════════════════
#   Name Enforcement
# ═══════════════════════════════════════════════════════════════════════════

def ensure_offline_prefix(name):
    """Ensure agent name starts with 'offline_'. Auto-prepends if missing."""
    if not name.startswith('offline_'):
        name = f'offline_{name}'
    return name


# ═══════════════════════════════════════════════════════════════════════════
#   Tool Handler
# ═══════════════════════════════════════════════════════════════════════════

class ToolHandler:
    """Handles tool calls from the LLM during offline agent generation.

    Tracks created agents locally (name -> code) for validation and upload.
    Server interactions are done via HTTP to the arena API.
    """

    def __init__(self, server_url, game_id, leaderboard, verbose=False):
        self.server_url = server_url
        self.game_id = game_id
        self.leaderboard = leaderboard  # list of agent dicts from server
        self.verbose = verbose
        self.created_agents = {}  # name -> code (locally created this round)
        self._agent_id_cache = {}  # name -> server agent_id

        # Build name -> id mapping from leaderboard
        for agent in leaderboard:
            self._agent_id_cache[agent['name']] = agent.get('id')

    def handle(self, name, args):
        """Dispatch a tool call. Returns a JSON string result."""
        if name == 'create_agent':
            return self._handle_create_agent(args)
        if name == 'read_agent':
            return self._handle_read_agent(args)
        if name == 'run_test':
            return self._handle_run_test(args)
        if name == 'test_match':
            return self._handle_test_match(args)
        if name == 'query_db':
            return self._handle_query_db(args)
        if name == 'get_agent_games':
            return self._handle_get_agent_games(args)
        return json.dumps({'error': f'Unknown tool: {name}'})

    def _handle_create_agent(self, args):
        """Create an agent locally. Validates code, stores for later upload."""
        agent_name = args.get('name', '')
        code = args.get('code', '')

        if not agent_name or not re.match(r'^[a-zA-Z_][a-zA-Z0-9_]*$', agent_name):
            return json.dumps({'error': 'Invalid name. Letters, digits, underscores only.'})

        agent_name = ensure_offline_prefix(agent_name)

        if not code or 'get_move' not in code:
            return json.dumps({'error': 'Code must contain a get_move function.'})

        if len(code) > 50000:
            return json.dumps({'error': 'Code too large (max 50KB).'})

        # Local validation if available
        if HAS_LOCAL_VALIDATION:
            error = _validate_code(self.game_id, code)
            if error:
                return json.dumps({'error': f'Validation failed: {error}'})
            test_note = 'All tests passed locally.'
        else:
            test_note = 'Local validation not available — will validate on server during upload.'

        # Run a quick test match against top agent if possible
        match_note = ''
        if HAS_LOCAL_MATCH and self.leaderboard:
            top_agent = self.leaderboard[0]
            top_code = top_agent.get('code', '')
            if top_code:
                try:
                    result = _run_match(self.game_id, code, top_code)
                    if result.get('winner') == 0:
                        match_note = f" Quick test vs {top_agent['name']}: WIN in {result['turns']} turns."
                    elif result.get('winner') == 1:
                        match_note = f" Quick test vs {top_agent['name']}: LOSS in {result['turns']} turns."
                    else:
                        match_note = f" Quick test vs {top_agent['name']}: DRAW in {result['turns']} turns."
                except Exception:
                    pass

        self.created_agents[agent_name] = code
        return json.dumps({
            'success': True,
            'message': f"Agent '{agent_name}' created locally. {test_note}{match_note}"
        })

    def _handle_read_agent(self, args):
        """Read agent code — check local first, then server."""
        agent_name = args.get('agent_name', '')

        # Check locally created agents
        if agent_name in self.created_agents:
            return self.created_agents[agent_name]

        # Check leaderboard agents (may have code attached)
        for agent in self.leaderboard:
            if agent['name'] == agent_name and agent.get('code'):
                return agent['code']

        # Fetch from server
        agent_id = self._agent_id_cache.get(agent_name)
        if agent_id:
            agent_data = fetch_agent_code(self.server_url, self.game_id, agent_id)
            if agent_data and agent_data.get('code'):
                return agent_data['code']

        return json.dumps({'error': f"Agent '{agent_name}' not found."})

    def _handle_run_test(self, args):
        """Run local validation on a named agent."""
        agent_name = args.get('agent_name', '')

        # Find code
        code = self.created_agents.get(agent_name)
        if not code:
            for agent in self.leaderboard:
                if agent['name'] == agent_name and agent.get('code'):
                    code = agent['code']
                    break
        if not code:
            agent_id = self._agent_id_cache.get(agent_name)
            if agent_id:
                agent_data = fetch_agent_code(self.server_url, self.game_id, agent_id)
                if agent_data:
                    code = agent_data.get('code', '')

        if not code:
            return json.dumps({'error': f"Agent '{agent_name}' not found."})

        if HAS_LOCAL_VALIDATION:
            error = _validate_code(self.game_id, code)
            if error:
                return json.dumps({'passed': False, 'details': error})
            return json.dumps({'passed': True, 'details': 'All tests passed.'})
        else:
            return json.dumps({'passed': None, 'details': 'Local validation not available. Agent will be validated on server during upload.'})

    def _handle_test_match(self, args):
        """Run a test match between two agents."""
        a1_name = args.get('agent1_name', '')
        a2_name = args.get('agent2_name', '')

        # Resolve code for both agents
        code_a = self._resolve_agent_code(a1_name)
        code_b = self._resolve_agent_code(a2_name)

        if not code_a:
            return json.dumps({'error': f"Agent '{a1_name}' not found or has no code."})
        if not code_b:
            return json.dumps({'error': f"Agent '{a2_name}' not found or has no code."})

        if not HAS_LOCAL_MATCH:
            return json.dumps({'error': 'Local match engine not available. Cannot run test_match offline.'})

        try:
            result = _run_match(self.game_id, code_a, code_b)
            if result.get('error'):
                return json.dumps({'error': result['error']})
            winner_name = a1_name if result['winner'] == 0 else (a2_name if result['winner'] == 1 else 'Draw')
            return json.dumps({
                'winner': winner_name,
                'turns': result['turns'],
                'scores': result['scores'],
            })
        except Exception as exc:
            return json.dumps({'error': f'Match error: {exc}'})

    def _handle_query_db(self, args):
        """query_db is not supported offline."""
        return json.dumps({
            'error': 'query_db is not supported in offline mode. Use read_agent to view agent code or get_agent_games to see match history.'
        })

    def _handle_get_agent_games(self, args):
        """Fetch agent game history from server."""
        agent_name = args.get('agent_name', '')
        limit = args.get('limit', 5)

        agent_id = self._agent_id_cache.get(agent_name)
        if not agent_id:
            return json.dumps({'error': f"Agent '{agent_name}' not found on server."})

        data = fetch_agent_games(self.server_url, self.game_id, agent_id, limit=int(limit))
        if not data:
            return json.dumps({'error': f"Failed to fetch games for '{agent_name}' from server."})

        games = data.get('games', [])
        results = []
        for g in games:
            results.append({
                'id': g.get('id'),
                'p1': g.get('agent1_name'),
                'p2': g.get('agent2_name'),
                'winner': g.get('winner_name'),
                'scores': f"{g.get('agent1_score', 0)}-{g.get('agent2_score', 0)}",
                'turns': g.get('turns'),
            })
        return json.dumps(results)

    def _resolve_agent_code(self, name):
        """Resolve agent code from local store, leaderboard, or server."""
        if name in self.created_agents:
            return self.created_agents[name]
        for agent in self.leaderboard:
            if agent['name'] == name and agent.get('code'):
                return agent['code']
        agent_id = self._agent_id_cache.get(name)
        if agent_id:
            agent_data = fetch_agent_code(self.server_url, self.game_id, agent_id)
            if agent_data:
                return agent_data.get('code', '')
        return None


# ═══════════════════════════════════════════════════════════════════════════
#   LLM Provider Dispatch (delegates to offline_llm.py)
# ═══════════════════════════════════════════════════════════════════════════

import offline_llm


# ═══════════════════════════════════════════════════════════════════════════
#   Evolution Cycle
# ═══════════════════════════════════════════════════════════════════════════

def run_one_evolution(args, program_md, leaderboard):
    """Run one evolution cycle: call LLM with tools, get agent code, upload.

    Returns dict with 'created' (list of names), 'uploaded' (list of names),
    'errors' (list of error strings).
    """
    result = {'created': [], 'uploaded': [], 'errors': []}

    # Build system prompt
    system_prompt = program_md + """

Call create_agent with name and complete Python code.
The agent must have a get_move(state) function.
Must return in <100ms.
You may use any available Python library — test-import with try/except first.
All agent names will be auto-prefixed with 'offline_' if not already.
"""

    # Build user prompt with leaderboard + top agent code
    leaderboard_text = ''
    if leaderboard:
        leaderboard_text = 'Current leaderboard:\n'
        for i, agent in enumerate(leaderboard[:5]):
            leaderboard_text += (
                f"  #{i+1} {agent['name']} ELO={agent.get('elo', 1000):.0f} "
                f"W/L/D={agent.get('wins', 0)}/{agent.get('losses', 0)}/{agent.get('draws', 0)}\n"
            )
        top = leaderboard[0]
        if top.get('code'):
            leaderboard_text += f"\nBest agent code ({top['name']}):\n```python\n{top['code']}\n```\n"

    user_prompt = f"""{leaderboard_text}
Create ONE agent. Name it with a descriptive strategy name (e.g. flood_fill, aggro_cutter, wall_hugger).
Study the top agents and create a counter-strategy.
Call create_agent with name and full Python code."""

    # Set up tool handler
    tool_handler = ToolHandler(
        server_url=args.server,
        game_id=args.game,
        leaderboard=leaderboard,
        verbose=args.verbose,
    )

    # Resolve model
    model = args.model or PROVIDER_DEFAULTS.get(args.provider, 'unknown')

    # Run the tool loop via offline_llm (multi-provider support)
    base_url = None
    if args.provider == 'lmstudio':
        base_url = args.lmstudio_url
    elif args.provider == 'ollama':
        base_url = args.ollama_url
    offline_llm.run_tool_loop(
        provider=args.provider,
        api_key=resolve_api_key(args),
        system_prompt=system_prompt,
        user_message=user_prompt,
        tools=OFFLINE_TOOLS,
        handler=tool_handler.handle,
        model=model,
        max_tokens=args.max_tokens,
        max_rounds=args.max_rounds,
        base_url=base_url,
    )

    # Report what was created
    for name, code in tool_handler.created_agents.items():
        result['created'].append(name)
        print(f'[offline] Agent created: {name} ({len(code)} chars)')

    # Upload created agents (unless dry-run)
    if args.dry_run:
        print(f'[offline] DRY RUN — skipping upload of {len(tool_handler.created_agents)} agent(s).')
    else:
        model_label = args.model or PROVIDER_DEFAULTS.get(args.provider, 'unknown')
        for name, code in tool_handler.created_agents.items():
            print(f'[offline] Uploading {name} to {args.server}...')
            upload_result = upload_agent(
                args.server, args.game, name, code,
                provider=args.provider, model=model_label,
            )
            if upload_result.get('error'):
                error_msg = f"Upload of {name} failed: {upload_result['error']}"
                print(f'[offline] ERROR: {error_msg}')
                result['errors'].append(error_msg)
            else:
                agent_id = upload_result.get('id', '?')
                print(f'[offline] Uploaded {name} (id={agent_id}, elo={upload_result.get("elo", 1000)})')
                result['uploaded'].append(name)

    if not tool_handler.created_agents:
        error_msg = 'LLM did not create any agents this round.'
        print(f'[offline] WARNING: {error_msg}')
        result['errors'].append(error_msg)

    return result


# ═══════════════════════════════════════════════════════════════════════════
#   API Key Resolution
# ═══════════════════════════════════════════════════════════════════════════

def resolve_api_key(args):
    """Resolve API key from CLI args or environment variables."""
    if args.provider == 'anthropic':
        key = args.anthropic_key or os.environ.get('ANTHROPIC_API_KEY', '')
        if not key:
            print('[offline] ERROR: Anthropic API key required. Set ANTHROPIC_API_KEY or use --anthropic-key.')
            sys.exit(1)
        return key
    elif args.provider == 'openai':
        key = args.openai_key or os.environ.get('OPENAI_API_KEY', '')
        if not key:
            print('[offline] ERROR: OpenAI API key required. Set OPENAI_API_KEY or use --openai-key.')
            sys.exit(1)
        return key
    elif args.provider == 'gemini':
        key = args.gemini_key or os.environ.get('GEMINI_API_KEY', '')
        if not key:
            print('[offline] ERROR: Gemini API key required. Set GEMINI_API_KEY or use --gemini-key.')
            sys.exit(1)
        return key
    elif args.provider == 'lmstudio':
        return ''  # LM Studio doesn't require API key
    elif args.provider == 'ollama':
        return ''  # Ollama runs locally, no API key needed
    else:
        print(f'[offline] ERROR: Unknown provider: {args.provider}')
        sys.exit(1)


# ═══════════════════════════════════════════════════════════════════════════
#   CLI
# ═══════════════════════════════════════════════════════════════════════════

def parse_args():
    """Parse CLI arguments."""
    parser = argparse.ArgumentParser(
        description='Generate arena agents locally using any LLM provider, then upload to the server.',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python offline_agent_runner.py --game snake --provider anthropic
  python offline_agent_runner.py --game snake --provider ollama --model qwen3:72b
  python offline_agent_runner.py --game snake --provider lmstudio --lmstudio-url http://localhost:1234/v1
  python offline_agent_runner.py --game chess960 --provider gemini --count 3
  python offline_agent_runner.py --game snake --provider openai --model gpt-4o --dry-run
  python offline_agent_runner.py --game snake --provider anthropic --program-file server/arena_seeds/default_program.md
        """,
    )
    parser.add_argument('--game', default='snake', choices=VALID_GAMES,
                        help='Arena game ID (default: snake)')
    parser.add_argument('--provider', required=True, choices=VALID_PROVIDERS,
                        help='LLM provider: anthropic, openai, gemini, lmstudio')
    parser.add_argument('--model', default=None,
                        help='Model ID override (default: provider-specific default)')
    parser.add_argument('--server', default=DEFAULT_SERVER,
                        help=f'Server URL (default: {DEFAULT_SERVER})')
    parser.add_argument('--count', type=int, default=1,
                        help='Number of agents to generate (default: 1)')
    parser.add_argument('--max-rounds', type=int, default=DEFAULT_MAX_ROUNDS,
                        help=f'Max tool-calling iterations per agent (default: {DEFAULT_MAX_ROUNDS})')
    parser.add_argument('--max-tokens', type=int, default=DEFAULT_MAX_TOKENS,
                        help=f'Max tokens per LLM response (default: {DEFAULT_MAX_TOKENS})')
    parser.add_argument('--program-file', default=None,
                        help='Local Program.md path (skips server fetch)')
    parser.add_argument('--lmstudio-url', default=DEFAULT_LMSTUDIO_URL,
                        help=f'LM Studio endpoint (default: {DEFAULT_LMSTUDIO_URL})')
    parser.add_argument('--ollama-url', default='http://localhost:11434/v1',
                        help='Ollama endpoint (default: http://localhost:11434/v1)')
    parser.add_argument('--anthropic-key', default=None,
                        help='Anthropic API key (default: $ANTHROPIC_API_KEY)')
    parser.add_argument('--openai-key', default=None,
                        help='OpenAI API key (default: $OPENAI_API_KEY)')
    parser.add_argument('--gemini-key', default=None,
                        help='Google API key (default: $GEMINI_API_KEY)')
    parser.add_argument('--dry-run', action='store_true',
                        help='Validate locally but don\'t upload')
    parser.add_argument('--verbose', action='store_true',
                        help='Print full LLM conversation')
    return parser.parse_args()


def main():
    args = parse_args()

    print(f'[offline] Arena Offline Agent Runner')
    print(f'[offline] Game: {args.game} | Provider: {args.provider} | Count: {args.count}')
    if args.dry_run:
        print(f'[offline] DRY RUN mode — agents will not be uploaded.')
    print()

    # Resolve API key early to fail fast
    api_key = resolve_api_key(args)
    model = args.model or PROVIDER_DEFAULTS.get(args.provider, 'unknown')
    print(f'[offline] Model: {model}')

    if HAS_LOCAL_VALIDATION:
        print(f'[offline] Local validation: available')
    else:
        print(f'[offline] Local validation: not available (missing server deps)')
    if HAS_LOCAL_MATCH:
        print(f'[offline] Local match engine: available')
    else:
        print(f'[offline] Local match engine: not available')
    print()

    # Fetch Program.md
    if args.program_file:
        print(f'[offline] Reading Program.md from {args.program_file}...')
        try:
            with open(args.program_file) as f:
                program_md = f.read()
        except FileNotFoundError:
            print(f'[offline] ERROR: File not found: {args.program_file}')
            sys.exit(1)
    else:
        print(f'[offline] Fetching Program.md from {args.server}...')
        program_md = fetch_program(args.server, args.game)

    if not program_md:
        print(f'[offline] WARNING: No Program.md content found. Using fallback prompt.')
        fallback = {
            'snake': 'Create snake agents with a get_move(state) function that returns UP, DOWN, LEFT, or RIGHT.',
            'snake_random': 'Create snake agents with a get_move(state) function. state[\'walls\'] contains wall positions.',
            'snake_royale': 'Create 4-player snake agents with a get_move(state) function. state[\'snakes\'] has all 4 snakes.',
            'snake_2v2': 'Create 2v2 team snake agents with a get_move(state) function.',
            'chess960': 'Create chess960 agents with a get_move(state) function that returns a legal move string.',
            'othello': 'Create othello agents with a get_move(state) function that returns [row, col].',
        }
        program_md = fallback.get(args.game, 'Create agents with a get_move(state) function.')
    else:
        print(f'[offline] Program.md loaded ({len(program_md)} chars).')

    # Fetch leaderboard
    print(f'[offline] Fetching leaderboard from {args.server}...')
    leaderboard = fetch_leaderboard(args.server, args.game, limit=10)
    if leaderboard:
        print(f'[offline] Leaderboard: {len(leaderboard)} agents. Top: {leaderboard[0]["name"]} (ELO {leaderboard[0].get("elo", 1000):.0f})')
        # Fetch code for top agent
        top_agent = leaderboard[0]
        if not top_agent.get('code') and top_agent.get('id'):
            full = fetch_agent_code(args.server, args.game, top_agent['id'])
            if full and full.get('code'):
                top_agent['code'] = full['code']
                print(f'[offline] Fetched code for top agent: {top_agent["name"]} ({len(top_agent["code"])} chars)')
    else:
        print(f'[offline] No leaderboard data available. LLM will create from scratch.')
    print()

    # Run evolution cycles
    total_created = 0
    total_uploaded = 0
    total_errors = 0

    for i in range(args.count):
        print(f'[offline] ═══ Generating agent {i + 1}/{args.count} ═══')
        result = run_one_evolution(args, program_md, leaderboard)
        total_created += len(result['created'])
        total_uploaded += len(result['uploaded'])
        total_errors += len(result['errors'])

        if i < args.count - 1:
            print()

    # Summary
    print()
    print(f'[offline] ═══ Summary ═══')
    print(f'[offline] Created: {total_created} | Uploaded: {total_uploaded} | Errors: {total_errors}')
    if total_errors > 0:
        print(f'[offline] Some agents failed. Check output above for details.')
    if total_uploaded > 0:
        print(f'[offline] Agents are now in the {args.game} arena and will play in the next tournament round.')


if __name__ == '__main__':
    main()
