"""Async Ollama client via OpenAI-compatible endpoint."""

import httpx

from ..config import settings


async def generate(
    prompt: str,
    system_prompt: str = "",
    temperature: float = 0.7,
    max_tokens: int = 1024,
) -> str:
    """Generate text using Ollama's OpenAI-compatible API."""
    messages = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    messages.append({"role": "user", "content": prompt})

    async with httpx.AsyncClient(timeout=300.0) as client:
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
