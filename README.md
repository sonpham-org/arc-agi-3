# ARC-AGI-3 Agent

An LLM-powered system for playing [ARC-AGI-3](https://arcprize.org/) — an interactive reasoning benchmark where each game is a 64×64 pixel grid with 16 colours.  There are no instructions; the agent must discover the rules, controls, and goals by experimenting.

---

## Quick start

```bash
python -m venv venv
source venv/bin/activate
pip install flask python-dotenv arc-agi arcengine httpx google-genai ollama pyyaml anthropic

cp .env.example .env          # fill in your API keys
python agent.py --game ls20   # play one game with default settings
```

---

## Architecture

The agent has **three independently configurable blocks** in `config.yaml`:

### 1  Context block — *what information the agent sees*

| Setting | Default | Effect |
|---------|---------|--------|
| `full_grid` | `true` | Full RLE-compressed 64×64 grid at every step |
| `change_map` | `true` | Cells that changed since the last action (X/. overlay) |
| `color_histogram` | `false` | Count of each colour in the current grid |
| `region_map` | `false` | Connected-component regions per colour (BFS flood-fill) |
| `history_length` | `10` | How many recent moves to show in the prompt |
| `memory_injection` | `true` | Inject relevant facts from `memory/MEMORY.md` |
| `memory_injection_max_chars` | `1500` | Caps the injected memory to stay within token budget |

Turn sources on/off to experiment with the trade-off between prompt size and agent performance.

### 2  Reasoning block — *which model(s) think*

| Setting | Default | Effect |
|---------|---------|--------|
| `executor_model` | `gemini-2.5-flash` | Main model used at every action step |
| `condenser_model` | `null` | Model used to condense old history (null = reuse executor) |
| `reflector_model` | `null` | Model used for post-game reflection (null = reuse executor) |
| `temperature` | `0.3` | Sampling temperature for action decisions |
| `max_tokens` | `2048` | Max output tokens for action decisions |
| `reflection_max_tokens` | `1024` | Max tokens for condensation / reflection passes |

Setting a separate (cheaper) model for condensation and reflection lets you use a more capable model only where it matters most.

### 3  Memory management block — *what the agent remembers*

| Setting | Default | Effect |
|---------|---------|--------|
| `hard_memory_file` | `memory/MEMORY.md` | Cross-session persistent facts (markdown) |
| `session_log_file` | `memory/sessions.json` | Structured log of every game result |
| `allow_inline_memory_writes` | `true` | Agent can write a new fact mid-game |
| `reflect_after_game` | `true` | Run a reflection pass after each game ends |
| `condense_every` | `25` | Summarise old history every N steps (0 = off) |
| `condense_threshold` | `50` | Force condensation when history exceeds N entries |

---

## Hard memory

Two files persist knowledge between sessions:

**`memory/MEMORY.md`** — free-form markdown that the agent reads and writes.  Sections:
- `## General` — universal ARC-AGI-3 facts
- `## Strategies` — general solving approaches
- `## <game_id>` — game-specific rules and discoveries

After each game the reflector LLM extracts 2-5 novel facts and appends them under the game's section.  During a game the agent can also write a `"memory_update"` field in its JSON response to save a rule the moment it discovers it.

**`memory/sessions.json`** — structured JSON array logging every game run (timestamp, result, steps, levels completed, model used).

---

## Supported models

| Key | Provider | Requires |
|-----|----------|---------|
| `groq/llama-3.3-70b-versatile` | Groq | `GROQ_API_KEY` |
| `groq/gemma2-9b-it` | Groq | `GROQ_API_KEY` |
| `mistral/mistral-small-latest` | Mistral | `MISTRAL_API_KEY` |
| `gemini-2.0-flash-lite` | Gemini | `GEMINI_API_KEY` |
| `gemini-2.0-flash` | Gemini | `GEMINI_API_KEY` |
| `gemini-2.5-flash` | Gemini | `GEMINI_API_KEY` |
| `gemini-2.5-pro` | Gemini | `GEMINI_API_KEY` |
| `claude-haiku-4-5` | Anthropic | `ANTHROPIC_API_KEY` |
| `claude-sonnet-4-5` | Anthropic | `ANTHROPIC_API_KEY` |
| `claude-sonnet-4-6` | Anthropic | `ANTHROPIC_API_KEY` |
| `cloudflare/llama-3.3-70b` | Cloudflare Workers AI | `CLOUDFLARE_API_KEY` + `CLOUDFLARE_ACCOUNT_ID` |
| `hf/meta-llama-3.3-70b` | HuggingFace | `HUGGINGFACE_API_KEY` |
| `ollama/llama3.3` | Ollama (local) | Ollama running on port 11434 |

---

## CLI reference

```bash
# Play all games with config defaults
python agent.py

# Play one game
python agent.py --game ls20

# Override the model for this run only
python agent.py --model gemini-2.5-pro --game ft09

# Set a custom step limit
python agent.py --max-steps 400

# Use a different config file
python agent.py --config experiments/config_no_grid.yaml

# Print the resolved config and exit
python agent.py --show-config

# List all available models and check API keys
python agent.py --list-models
```

---

## Experiment recipes

### Minimal context (fastest, cheapest)
```yaml
context:
  full_grid: false
  change_map: true
  color_histogram: true
  region_map: false
  history_length: 5
  memory_injection: true
```

### Maximum context (best reasoning, most tokens)
```yaml
context:
  full_grid: true
  change_map: true
  color_histogram: true
  region_map: true
  history_length: 20
  memory_injection: true
```

### Tiered models (quality where it counts, cheap elsewhere)
```yaml
reasoning:
  executor_model: "gemini-2.5-flash"
  condenser_model: "groq/llama-3.3-70b-versatile"
  reflector_model: "groq/llama-3.3-70b-versatile"
```

### No memory (clean baseline)
```yaml
context:
  memory_injection: false
memory:
  allow_inline_memory_writes: false
  reflect_after_game: false
  condense_every: 0
```

---

## Project structure

```
arc-agi-3/
├── agent.py               # Autonomous CLI agent (main file)
├── config.yaml            # Three-block agent configuration
├── server.py              # Flask web server + visual player
├── play.py                # Minimal starter exploration script
├── memory/
│   ├── MEMORY.md          # Cross-session hard memory (human-readable)
│   └── sessions.json      # Structured session history
├── templates/
│   └── index.html         # Web player UI
├── environment_files/     # Game environment definitions
│   ├── ls20/
│   ├── ft09/
│   └── vc33/
├── .env                   # API keys (not committed)
└── .env.example           # Key template
```

---

## Developer Tools

### pi01 Level Selector

**pi01** is the pirate ship game with 9 levels.

While playing pi01 in the web UI, press **Shift+D** to open the dev level selector panel (bottom-right corner). Click any button to jump directly to that level:

| Button | Level Name |
|--------|-----------|
| L1 | Caribbean Cove |
| L2 | Skull Shoals |
| L3 | Dragon's Lair |
| L4 | Stormy Waters |
| L5 | Kraken's Hunt |
| L6 | Sentinel Straits |
| L7 | Hunter's Web |
| L8 | Fog of War |
| L9 | Key & Switch |

The panel uses the server endpoint `POST /api/dev/jump-level` with the secret header `X-Dev-Secret: arc-dev-2026`.

---

## License

Uses [arc-agi](https://pypi.org/project/arc-agi/) and [arcengine](https://pypi.org/project/arcengine/) from ARC Prize.
