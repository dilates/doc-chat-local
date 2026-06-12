from __future__ import annotations

import asyncio
import logging
from typing import AsyncIterator

import httpx

log = logging.getLogger(__name__)

DEFAULT_TIMEOUT = 60.0
MAX_CONCURRENT_EMBEDS = 5


class OllamaError(Exception):
    pass


class OllamaNotRunning(OllamaError):
    pass


class ModelNotFound(OllamaError):
    pass


class OllamaClient:
    def __init__(self, host: str = "http://127.0.0.1:11434") -> None:
        self.host = host.rstrip("/")
        self._http = httpx.AsyncClient(base_url=self.host, timeout=DEFAULT_TIMEOUT)

    async def check_connection(self) -> bool:
        try:
            resp = await self._http.get("/api/tags", timeout=5.0)
            return resp.status_code == 200
        except (httpx.ConnectError, httpx.TimeoutException, OSError):
            return False

    async def list_models(self) -> list[str]:
        try:
            resp = await self._http.get("/api/tags")
            resp.raise_for_status()
            data = resp.json()
            return [m["name"] for m in data.get("models", [])]
        except (httpx.ConnectError, httpx.TimeoutException, OSError) as exc:
            raise OllamaNotRunning(
                f"Cannot connect to Ollama at {self.host}. Is it running? "
                "Try: systemctl start ollama or ollama serve"
            ) from exc

    async def embed(self, text: str, model: str = "nomic-embed-text") -> list[float]:
        try:
            resp = await self._http.post(
                "/api/embeddings",
                json={"model": model, "prompt": text},
                timeout=DEFAULT_TIMEOUT,
            )
            if resp.status_code == 404:
                raise ModelNotFound(
                    f"Model '{model}' not found. Run: ollama pull {model}"
                )
            resp.raise_for_status()
            return resp.json()["embedding"]
        except (httpx.ConnectError, httpx.TimeoutException, OSError) as exc:
            raise OllamaNotRunning(
                f"Cannot connect to Ollama at {self.host}. Is it running? "
                "Try: systemctl start ollama or ollama serve"
            ) from exc
        except ModelNotFound:
            raise
        except httpx.HTTPStatusError as exc:
            body = exc.response.text[:200]
            raise OllamaError(f"Ollama embed error ({exc.response.status_code}): {body}") from exc

    async def embed_batch(
        self,
        texts: list[str],
        model: str = "nomic-embed-text",
    ) -> list[list[float]]:
        semaphore = asyncio.Semaphore(MAX_CONCURRENT_EMBEDS)

        async def _embed_one(text: str) -> list[float]:
            async with semaphore:
                return await self.embed(text, model)

        return await asyncio.gather(*[_embed_one(t) for t in texts])

    async def chat_stream(
        self,
        messages: list[dict],
        model: str,
    ) -> AsyncIterator[str]:
        payload = {
            "model": model,
            "messages": messages,
            "stream": True,
        }
        try:
            async with self._http.stream(
                "POST", "/api/chat", json=payload, timeout=DEFAULT_TIMEOUT
            ) as response:
                if response.status_code == 404:
                    raise ModelNotFound(f"Model '{model}' not found. Run: ollama pull {model}")
                response.raise_for_status()
                async for line in response.aiter_lines():
                    if not line.strip():
                        continue
                    import json
                    try:
                        data = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    content = data.get("message", {}).get("content", "")
                    if content:
                        yield content
                    if data.get("done"):
                        break
        except (httpx.ConnectError, httpx.TimeoutException, OSError) as exc:
            raise OllamaNotRunning(
                f"Cannot connect to Ollama at {self.host}. Is it running? "
                "Try: systemctl start ollama or ollama serve"
            ) from exc

    async def close(self) -> None:
        await self._http.aclose()
