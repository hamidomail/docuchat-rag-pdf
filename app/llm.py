"""Streaming chat clients. Plain HTTP (httpx) so any OpenAI-compatible server
works: OpenAI, Azure gateways, Groq, OpenRouter, Mistral, Ollama, LM Studio, vLLM.
"""
from __future__ import annotations

import json
from collections.abc import Iterator

import httpx

from .config import Settings


class LLMError(RuntimeError):
    pass


def stream_chat(settings: Settings, system: str, messages: list[dict]) -> Iterator[str]:
    if settings.llm_provider == "anthropic":
        yield from _stream_anthropic(settings, system, messages)
    elif settings.llm_provider == "openai":
        yield from _stream_openai(settings, system, messages)
    else:
        raise LLMError("No LLM provider configured")


def _sse_lines(response: httpx.Response) -> Iterator[str]:
    for line in response.iter_lines():
        if line.startswith("data:"):
            yield line[5:].strip()


def _raise_for_status(response: httpx.Response) -> None:
    if response.status_code >= 400:
        body = response.read().decode("utf-8", "replace")[:500]
        raise LLMError(f"LLM API returned {response.status_code}: {body}")


def _stream_openai(settings: Settings, system: str, messages: list[dict]) -> Iterator[str]:
    headers = {"Content-Type": "application/json"}
    if settings.openai_api_key:
        headers["Authorization"] = f"Bearer {settings.openai_api_key}"
    body = {
        "model": settings.openai_model,
        "temperature": settings.temperature,
        "stream": True,
        "messages": [{"role": "system", "content": system}, *messages],
    }
    with httpx.Client(timeout=httpx.Timeout(120, connect=10)) as client:
        with client.stream("POST", f"{settings.openai_base_url}/chat/completions",
                           headers=headers, json=body) as response:
            _raise_for_status(response)
            for data in _sse_lines(response):
                if data == "[DONE]":
                    break
                try:
                    delta = json.loads(data)["choices"][0]["delta"].get("content")
                except (KeyError, IndexError, json.JSONDecodeError):
                    continue
                if delta:
                    yield delta


def _stream_anthropic(settings: Settings, system: str, messages: list[dict]) -> Iterator[str]:
    headers = {
        "x-api-key": settings.anthropic_api_key,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
    }
    body = {
        "model": settings.anthropic_model,
        "max_tokens": 1024,
        "temperature": settings.temperature,
        "system": system,
        "stream": True,
        "messages": messages,
    }
    with httpx.Client(timeout=httpx.Timeout(120, connect=10)) as client:
        with client.stream("POST", "https://api.anthropic.com/v1/messages",
                           headers=headers, json=body) as response:
            _raise_for_status(response)
            for data in _sse_lines(response):
                try:
                    event = json.loads(data)
                except json.JSONDecodeError:
                    continue
                if event.get("type") == "content_block_delta":
                    text = event.get("delta", {}).get("text")
                    if text:
                        yield text
                elif event.get("type") == "error":
                    raise LLMError(event.get("error", {}).get("message", "Anthropic API error"))
