"""LLM admin service layer — Model registry and provider configuration.

Lists available models, handles BYOK key updates, discovers local models.
Pure business logic — no Flask context.
"""

import logging
import os

import httpx

from models import (
    MODEL_REGISTRY, OLLAMA_VRAM, OLLAMA_VISION_MODELS, _discovered_local_models,
)
import llm_providers
from server.helpers import get_mode, feature_enabled

log = logging.getLogger(__name__)


def get_models(args: dict) -> dict:
    """Return all models with capabilities and availability (mode-aware).
    
    Args:
        args: request.args dict (can be empty)
    
    Returns:
        {"models": [...], "mode": "staging"|"prod", "default": "model-name"}
    """
    models = []
    mode = get_mode()

    for key, info in MODEL_REGISTRY.items():
        provider = info["provider"]
        # Copilot models need OAuth, not env key
        if provider == "copilot":
            if not feature_enabled("copilot"):
                continue
            available = llm_providers.copilot_oauth_token is not None
        elif mode == "prod":
            # In prod mode, all server providers shown but marked unavailable
            # (user provides their own key via BYOK)
            available = False
        else:
            env_key = info.get("env_key", "")
            available = bool(not env_key or os.environ.get(env_key))
        models.append({
            "name": key,
            "api_model": info.get("api_model", key),
            "provider": provider,
            "price": info.get("price", "?"),
            "pricing": info.get("pricing"),
            "context_window": info.get("context_window", 128000),
            "capabilities": info.get("capabilities", {}),
            "available": available,
        })

    # Discover Ollama models (staging only)
    if mode == "staging":
        try:
            import ollama
            ollama_list = ollama.list()
            ollama_names = [m.model for m in ollama_list.models] if hasattr(ollama_list, "models") else []
            for name in ollama_names:
                vram = OLLAMA_VRAM.get(name, "local")
                is_vision = name.split(":")[0] in OLLAMA_VISION_MODELS
                models.append({
                    "name": name,
                    "provider": "ollama",
                    "price": f"Free ({vram})",
                    "capabilities": {"image": is_vision, "reasoning": False, "tools": False},
                    "available": True,
                })
        except Exception:
            pass

    # Discover local OpenAI-compatible servers (LM Studio, llama.cpp, vLLM, etc.)
    if mode == "staging":
        # Build set of api_model values already covered by MODEL_REGISTRY entries
        # so discovered models don't duplicate registry entries with different display names.
        _registry_api_models = {
            info.get("api_model", k)
            for k, info in MODEL_REGISTRY.items()
            if info.get("provider") in ("lmstudio", "local", "ollama")
        }
        LOCAL_PORTS = [
            (1234, "LM Studio"),
            (8080, "Local Server"),
            (8000, "Local Server"),
        ]
        for port, label in LOCAL_PORTS:
            try:
                resp = httpx.get(f"http://localhost:{port}/v1/models", timeout=5.0)
                if resp.status_code == 200:
                    data = resp.json()
                    model_list = data.get("data", [])
                    for m in model_list:
                        mid = m.get("id", "")
                        if not mid:
                            continue
                        # Skip embedding models — not chat models
                        if "embedding" in mid.lower():
                            continue
                        # Skip if already covered by a MODEL_REGISTRY entry
                        if mid in _registry_api_models:
                            continue
                        is_lmstudio = (port == 1234)
                        provider_name = "lmstudio" if is_lmstudio else "local"
                        # Capability overrides for known LM Studio models
                        # Mirrors LMSTUDIO_CAPABILITIES in scaffolding.js — update both together
                        _LMS_CAPS = {
                            'zai-org/glm-4.7-flash':  {'reasoning': True,  'image': False},
                            'zai-org/glm-4.6v-flash': {'reasoning': True,  'image': True},
                            'qwen/qwen3.5-35b-a3b':   {'reasoning': True,  'image': True},
                            'qwen/qwen3.5-9b':        {'reasoning': True,  'image': False},
                        }
                        caps = _LMS_CAPS.get(mid, {}) if is_lmstudio else {}
                        has_reasoning = caps.get("reasoning", False)
                        has_image = caps.get("image", False)
                        entry = {
                            "name": mid,
                            "api_model": mid,
                            "provider": provider_name,
                            "local_port": port,
                            "local_label": label,
                            "price": f"Free ({label}:{port})",
                            # LM Studio context window override — default 3900 silently truncates.
                            "context_window": 8192 if is_lmstudio else None,
                            "capabilities": {"image": has_image, "reasoning": has_reasoning, "tools": False},
                            "available": True,
                        }
                        models.append(entry)
                        _discovered_local_models[mid] = entry
            except Exception:
                pass

    from models import DEFAULT_MODEL
    return {"models": models, "mode": mode, "default": DEFAULT_MODEL}
