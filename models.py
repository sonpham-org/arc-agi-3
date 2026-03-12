"""Model registry and constants for ARC-AGI-3."""

SYSTEM_MSG = (
    "You are an expert puzzle-solving AI agent. Analyse game grids and output "
    "ONLY valid JSON — no markdown, no explanation outside JSON."
)

THINKING_BUDGETS = {
    "off": 0,
    "low": 1024,
    "med": 4096,
    "high": 8192,
    "max": 24576,
}

# ═══════════════════════════════════════════════════════════════════════════
# MODEL REGISTRY — capabilities include image/reasoning/tools support
# ═══════════════════════════════════════════════════════════════════════════

MODEL_REGISTRY: dict[str, dict] = {
    # ── Gemini ────────────────────────────────────────────────────────────
    "gemini-3.1-pro": {
        "provider": "gemini", "api_model": "gemini-3.1-pro-preview",
        "env_key": "GEMINI_API_KEY",
        "price": "$2/$12 per 1M tok",
        "context_window": 1000000,
        "capabilities": {"image": True, "reasoning": True, "tools": True},
        "pricing": [1.25, 10.0, 10.0],
    },
    "gemini-3-pro": {
        "provider": "gemini", "api_model": "gemini-3-pro-preview",
        "env_key": "GEMINI_API_KEY",
        "price": "$2/$12 per 1M tok",
        "context_window": 1000000,
        "capabilities": {"image": True, "reasoning": True, "tools": True},
        "pricing": [1.25, 10.0, 10.0],
    },
    "gemini-3.1-flash-lite": {
        "provider": "gemini", "api_model": "gemini-3.1-flash-lite-preview",
        "env_key": "GEMINI_API_KEY",
        "price": "$0.25/$1.50 per 1M tok",
        "context_window": 1000000,
        "capabilities": {"image": True, "reasoning": True, "tools": True},
        "pricing": [0.075, 0.30, 0.30],
    },
    "gemini-3-flash": {
        "provider": "gemini", "api_model": "gemini-3-flash-preview",
        "env_key": "GEMINI_API_KEY",
        "price": "$0.50/$3 per 1M tok",
        "context_window": 1000000,
        "capabilities": {"image": True, "reasoning": True, "tools": True},
        "pricing": [0.15, 0.60, 0.60],
    },
    "gemini-2.5-pro": {
        "provider": "gemini", "api_model": "gemini-2.5-pro",
        "env_key": "GEMINI_API_KEY",
        "price": "$1.25/$10 per 1M tok",
        "context_window": 1000000,
        "capabilities": {"image": True, "reasoning": True, "tools": True},
        "pricing": [1.25, 10.0, 10.0],
    },
    "gemini-2.5-flash": {
        "provider": "gemini", "api_model": "gemini-2.5-flash",
        "env_key": "GEMINI_API_KEY",
        "price": "$0.30/$2.50 per 1M tok",
        "context_window": 1000000,
        "capabilities": {"image": True, "reasoning": True, "tools": True},
        "pricing": [0.15, 0.60, 0.60],
    },
    "gemini-2.5-flash-lite": {
        "provider": "gemini", "api_model": "gemini-2.5-flash-lite",
        "env_key": "GEMINI_API_KEY",
        "price": "$0.10/$0.40 per 1M tok",
        "context_window": 1000000,
        "capabilities": {"image": True, "reasoning": False, "tools": False},
        "pricing": [0.075, 0.30, 0.30],
    },
    "gemini-2.0-flash": {
        "provider": "gemini", "api_model": "gemini-2.0-flash",
        "env_key": "GEMINI_API_KEY",
        "price": "$0.10/$0.40 per 1M tok",
        "context_window": 1000000,
        "capabilities": {"image": True, "reasoning": False, "tools": True},
        "pricing": [0.10, 0.40, 0.0],
    },
    "gemini-2.0-flash-lite": {
        "provider": "gemini", "api_model": "gemini-2.0-flash-lite",
        "env_key": "GEMINI_API_KEY",
        "price": "$0.075/$0.30 per 1M tok",
        "context_window": 1000000,
        "capabilities": {"image": True, "reasoning": False, "tools": False},
        "pricing": [0.0, 0.0, 0.0],
    },
    # ── Anthropic ─────────────────────────────────────────────────────────
    "claude-sonnet-4-6": {
        "provider": "anthropic", "api_model": "claude-sonnet-4-6",
        "env_key": "ANTHROPIC_API_KEY",
        "price": "$3/$15 per 1M tok",
        "context_window": 200000,
        "capabilities": {"image": True, "reasoning": True, "tools": True},
        "pricing": [3.0, 15.0, 15.0],
    },
    "claude-sonnet-4-5": {
        "provider": "anthropic", "api_model": "claude-sonnet-4-5-20241022",
        "env_key": "ANTHROPIC_API_KEY",
        "price": "$3/$15 per 1M tok",
        "context_window": 200000,
        "capabilities": {"image": True, "reasoning": True, "tools": True},
        "pricing": [3.0, 15.0, 15.0],
    },
    "claude-haiku-4-5": {
        "provider": "anthropic", "api_model": "claude-haiku-4-5-20251001",
        "env_key": "ANTHROPIC_API_KEY",
        "price": "$0.80/$4 per 1M tok",
        "context_window": 200000,
        "capabilities": {"image": True, "reasoning": False, "tools": True},
        "pricing": [0.80, 4.0, 4.0],
    },
    # ── Groq ──────────────────────────────────────────────────
    "groq/llama-3.3-70b-versatile": {
        "provider": "groq", "api_model": "llama-3.3-70b-versatile",
        "env_key": "GROQ_API_KEY",
        "url": "https://api.groq.com/openai/v1/chat/completions",
        "price": "Free tier",
        "context_window": 128000,
        "capabilities": {"image": False, "reasoning": False, "tools": False},
        "pricing": [0.0, 0.0, 0.0],
    },
    "groq/gemma2-9b-it": {
        "provider": "groq", "api_model": "gemma2-9b-it",
        "env_key": "GROQ_API_KEY",
        "url": "https://api.groq.com/openai/v1/chat/completions",
        "price": "Free tier",
        "context_window": 8192,
        "capabilities": {"image": False, "reasoning": False, "tools": False},
        "pricing": [0.0, 0.0, 0.0],
    },
    "groq/mixtral-8x7b-32768": {
        "provider": "groq", "api_model": "mixtral-8x7b-32768",
        "env_key": "GROQ_API_KEY",
        "url": "https://api.groq.com/openai/v1/chat/completions",
        "price": "Free tier",
        "context_window": 32768,
        "capabilities": {"image": False, "reasoning": False, "tools": False},
        "pricing": [0.0, 0.0, 0.0],
    },
    # ── Mistral ───────────────────────────────────────────────
    "mistral/mistral-small-latest": {
        "provider": "mistral", "api_model": "mistral-small-latest",
        "env_key": "MISTRAL_API_KEY",
        "url": "https://api.mistral.ai/v1/chat/completions",
        "price": "Free tier",
        "context_window": 128000,
        "capabilities": {"image": False, "reasoning": False, "tools": False},
        "pricing": [0.0, 0.0, 0.0],
    },
    "mistral/open-mistral-nemo": {
        "provider": "mistral", "api_model": "open-mistral-nemo",
        "env_key": "MISTRAL_API_KEY",
        "url": "https://api.mistral.ai/v1/chat/completions",
        "price": "Free tier",
        "context_window": 128000,
        "capabilities": {"image": False, "reasoning": False, "tools": False},
        "pricing": [0.0, 0.0, 0.0],
    },
    # ── HuggingFace ───────────────────────────────────────────────────────
    "hf/qwen2.5-72b-instruct": {
        "provider": "huggingface", "api_model": "Qwen/Qwen2.5-72B-Instruct",
        "env_key": "HUGGINGFACE_API_KEY",
        "url": "https://router.huggingface.co/v1/chat/completions",
        "price": "Free tier",
        "context_window": 128000,
        "capabilities": {"image": False, "reasoning": False, "tools": False},
        "pricing": [0.0, 0.0, 0.0],
    },
    "hf/llama-3.1-70b-instruct": {
        "provider": "huggingface", "api_model": "meta-llama/Llama-3.1-70B-Instruct",
        "env_key": "HUGGINGFACE_API_KEY",
        "url": "https://router.huggingface.co/v1/chat/completions",
        "price": "Free tier",
        "context_window": 128000,
        "capabilities": {"image": False, "reasoning": False, "tools": False},
        "pricing": [0.0, 0.0, 0.0],
    },
    # ── Cloudflare Workers AI ────────────────────────────────────────────
    "cf/llama-3.3-70b-instruct": {
        "provider": "cloudflare", "api_model": "@cf/meta/llama-3.3-70b-instruct-fp8-fast",
        "env_key": "CLOUDFLARE_API_KEY",
        "price": "Free (10k neurons/day)",
        "context_window": 128000,
        "capabilities": {"image": False, "reasoning": False, "tools": False},
        "pricing": [0.0, 0.0, 0.0],
    },
    "cf/llama-3.1-8b-instruct": {
        "provider": "cloudflare", "api_model": "@cf/meta/llama-3.1-8b-instruct-fast",
        "env_key": "CLOUDFLARE_API_KEY",
        "price": "Free (10k neurons/day)",
        "context_window": 128000,
        "capabilities": {"image": False, "reasoning": False, "tools": False},
        "pricing": [0.0, 0.0, 0.0],
    },
    "cf/llama-4-scout-17b": {
        "provider": "cloudflare", "api_model": "@cf/meta/llama-4-scout-17b-16e-instruct",
        "env_key": "CLOUDFLARE_API_KEY",
        "price": "Free (10k neurons/day)",
        "context_window": 128000,
        "capabilities": {"image": False, "reasoning": False, "tools": False},
        "pricing": [0.0, 0.0, 0.0],
    },
    "cf/qwen3-30b": {
        "provider": "cloudflare", "api_model": "@cf/qwen/qwen3-30b-a3b-fp8",
        "env_key": "CLOUDFLARE_API_KEY",
        "price": "Free (10k neurons/day)",
        "context_window": 32768,
        "capabilities": {"image": False, "reasoning": True, "tools": False},
        "pricing": [0.0, 0.0, 0.0],
    },
    "cf/qwq-32b": {
        "provider": "cloudflare", "api_model": "@cf/qwen/qwq-32b",
        "env_key": "CLOUDFLARE_API_KEY",
        "price": "Free (10k neurons/day)",
        "context_window": 32768,
        "capabilities": {"image": False, "reasoning": True, "tools": False},
        "pricing": [0.0, 0.0, 0.0],
    },
    "cf/deepseek-r1-distill-32b": {
        "provider": "cloudflare", "api_model": "@cf/deepseek-ai/deepseek-r1-distill-qwen-32b",
        "env_key": "CLOUDFLARE_API_KEY",
        "price": "Free (10k neurons/day)",
        "context_window": 32768,
        "capabilities": {"image": False, "reasoning": True, "tools": False},
        "pricing": [0.0, 0.0, 0.0],
    },
    "cf/mistral-small-3.1-24b": {
        "provider": "cloudflare", "api_model": "@cf/mistralai/mistral-small-3.1-24b-instruct",
        "env_key": "CLOUDFLARE_API_KEY",
        "price": "Free (10k neurons/day)",
        "context_window": 128000,
        "capabilities": {"image": False, "reasoning": False, "tools": False},
        "pricing": [0.0, 0.0, 0.0],
    },
    "cf/llama-3.2-11b-vision": {
        "provider": "cloudflare", "api_model": "@cf/meta/llama-3.2-11b-vision-instruct",
        "env_key": "CLOUDFLARE_API_KEY",
        "price": "Free (10k neurons/day)",
        "context_window": 128000,
        "capabilities": {"image": True, "reasoning": False, "tools": False},
        "pricing": [0.0, 0.0, 0.0],
    },
    # ── OpenAI / Codex ────────────────────────────────────────────────────
    "openai/o4-mini": {
        "provider": "openai", "api_model": "o4-mini",
        "env_key": "OPENAI_API_KEY",
        "url": "https://api.openai.com/v1/chat/completions",
        "price": "$1.10/$4.40 per 1M tok",
        "context_window": 200000,
        "capabilities": {"image": True, "reasoning": True, "tools": True},
        "pricing": [0.0, 0.0, 0.0],
    },
    "openai/o3": {
        "provider": "openai", "api_model": "o3",
        "env_key": "OPENAI_API_KEY",
        "url": "https://api.openai.com/v1/chat/completions",
        "price": "$10/$40 per 1M tok",
        "context_window": 200000,
        "capabilities": {"image": True, "reasoning": True, "tools": True},
        "pricing": [0.0, 0.0, 0.0],
    },
    "openai/codex-mini": {
        "provider": "openai", "api_model": "codex-mini-latest",
        "env_key": "OPENAI_API_KEY",
        "url": "https://api.openai.com/v1/chat/completions",
        "price": "$1.50/$6 per 1M tok",
        "context_window": 200000,
        "capabilities": {"image": False, "reasoning": True, "tools": True},
        "pricing": [0.0, 0.0, 0.0],
    },
    # ── GitHub Copilot (local only, requires OAuth) ──────────────────────
    "copilot/gpt-4.1": {
        "provider": "copilot", "api_model": "gpt-4.1",
        "env_key": "",
        "price": "Free (unlimited)",
        "context_window": 1000000,
        "capabilities": {"image": True, "reasoning": False, "tools": True},
        "pricing": [0.0, 0.0, 0.0],
    },
    "copilot/gpt-4o": {
        "provider": "copilot", "api_model": "gpt-4o",
        "env_key": "",
        "price": "Free (unlimited)",
        "context_window": 128000,
        "capabilities": {"image": True, "reasoning": False, "tools": True},
        "pricing": [0.0, 0.0, 0.0],
    },
    "copilot/gpt-5-mini": {
        "provider": "copilot", "api_model": "gpt-5-mini",
        "env_key": "",
        "price": "Free (unlimited)",
        "context_window": 1000000,
        "capabilities": {"image": True, "reasoning": True, "tools": True},
        "pricing": [0.0, 0.0, 0.0],
    },
    "copilot/claude-sonnet-4": {
        "provider": "copilot", "api_model": "claude-sonnet-4",
        "env_key": "",
        "price": "Premium (300/mo)",
        "context_window": 200000,
        "capabilities": {"image": True, "reasoning": True, "tools": True},
        "pricing": [0.0, 0.0, 0.0],
    },
    "copilot/gemini-2.5-pro": {
        "provider": "copilot", "api_model": "gemini-2.5-pro",
        "env_key": "",
        "price": "Premium (300/mo)",
        "context_window": 1000000,
        "capabilities": {"image": True, "reasoning": True, "tools": True},
        "pricing": [0.0, 0.0, 0.0],
    },
}

# Ollama models discovered at runtime; all support text only by default.
OLLAMA_VRAM = {
    "qwen3.5:35b-a3b": "~24GB",
    "qwen2.5:32b": "~19GB", "qwen2.5:14b": "~9GB", "qwen3-8b:latest": "~5GB",
    "deepseek-r1:latest": "~5GB", "mistral:7b": "~4.4GB",
    "llama3.1:latest": "~4.9GB", "llama3:latest": "~4.7GB",
    "llava:latest": "~5GB",
}

# Models that support vision via Ollama (llava family)
OLLAMA_VISION_MODELS = {"llava", "llava:latest", "llava:13b", "bakllava"}

# Runtime dict of discovered local OpenAI-compatible models (populated by /api/llm/models)
_discovered_local_models: dict = {}

# ═══════════════════════════════════════════════════════════════════════════
# COST COMPUTATION & CONSTANTS
# ═══════════════════════════════════════════════════════════════════════════

DEFAULT_MODEL = "groq/llama-3.3-70b-versatile"

# Alias for backward compatibility (agent.py and other files use MODELS)
MODELS = MODEL_REGISTRY


def compute_cost(model_key: str, input_tokens: int, output_tokens: int,
                 thinking_tokens: int = 0) -> float:
    """Compute USD cost for an LLM call based on model pricing.
    
    Args:
        model_key: Model identifier (e.g. 'gemini-2.5-flash')
        input_tokens: Number of input tokens consumed
        output_tokens: Number of output tokens generated
        thinking_tokens: Number of thinking tokens (for reasoning models)
    
    Returns:
        USD cost as a float, computed from pricing[input, output, thinking] per 1M tokens
    """
    info = MODELS.get(model_key, {})
    pricing = info.get("pricing", [0.0, 0.0, 0.0])
    cost_in, cost_out = pricing[0], pricing[1]
    cost_think = pricing[2] if len(pricing) > 2 else pricing[1]
    return (input_tokens * cost_in + output_tokens * cost_out + thinking_tokens * cost_think) / 1_000_000
