"""Async Ollama client via OpenAI-compatible endpoint.

Uses a global semaphore to limit concurrent Ollama calls.
Max 2 concurrent calls to prevent server overload.
"""

import asyncio
import logging

import httpx

from ..config import settings

logger = logging.getLogger("leadgen.ai.ollama")

# Global semaphore — max 2 concurrent Ollama calls across entire application
# This prevents NRD + Tender + Daemon from overloading the server
_ollama_semaphore = asyncio.Semaphore(2)
_queue_depth = 0


async def generate(
    prompt: str,
    system_prompt: str = "",
    temperature: float = 0.7,
    max_tokens: int = 1024,
) -> str:
    """Generate text using Ollama's OpenAI-compatible API.

    Rate-limited to max 2 concurrent calls globally.
    """
    global _queue_depth
    _queue_depth += 1

    if _queue_depth > 2:
        logger.debug("Ollama queue depth: %d (waiting for slot)", _queue_depth)

    async with _ollama_semaphore:
        _queue_depth -= 1
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        try:
            async with httpx.AsyncClient(timeout=600.0) as client:
                resp = await client.post(
                    f"{settings.ollama_base_url}/v1/chat/completions",
                    json={
                        "model": settings.ollama_model,
                        "messages": messages,
                        "temperature": temperature,
                        "max_tokens": max_tokens,
                    },
                )
                resp.raise_for_status()
                data = resp.json()
                return data["choices"][0]["message"]["content"]
        except httpx.ReadTimeout:
            logger.warning("Ollama timeout (600s) — model may be overloaded")
            raise
        except Exception as e:
            logger.error("Ollama error: %s", e)
            raise


async def check_health() -> dict:
    """Check if Ollama is running and the model is available."""
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(f"{settings.ollama_base_url}/api/tags")
            resp.raise_for_status()
            data = resp.json()

            models = [m["name"] for m in data.get("models", [])]
            model_available = any(settings.ollama_model in m for m in models)

            return {
                "ollama_running": True,
                "model": settings.ollama_model,
                "model_available": model_available,
                "available_models": models,
            }
    except Exception as e:
        return {
            "ollama_running": False,
            "error": str(e),
            "hint": "Make sure Ollama is running: 'ollama serve' and model is pulled: "
                    f"'ollama pull {settings.ollama_model}'",
        }
