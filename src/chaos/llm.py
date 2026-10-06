"""Talking to the local model. One function: chat()."""

import re
import time

from openai import APIConnectionError, APITimeoutError, InternalServerError, OpenAI

from chaos import config

_client: OpenAI | None = None


def client() -> OpenAI:
    global _client
    if _client is None:
        if not config.API_KEY:
            raise SystemExit("OMLX_API_KEY is not set. Copy .env.example to .env and fill it in.")
        _client = OpenAI(base_url=config.BASE_URL, api_key=config.API_KEY, timeout=config.CALL_TIMEOUT)
    return _client


def server_models(timeout: float = 30) -> list[str]:
    return [m.id for m in client().with_options(timeout=timeout, max_retries=0).models.list().data]


def chat(messages: list[dict], tools: list[dict] | None = None, temperature: float = 0.6) -> tuple[dict, dict]:
    """One model call. Returns (assistant message as a plain dict, usage dict).

    The message dict is ready to append straight back onto `messages`. Reasoning
    text is dropped: the model only needs its conclusions, not its old thoughts.
    Retries a few times if the server is briefly unreachable (e.g. swapping models).
    """
    kwargs = {
        "model": config.MODEL,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": config.MAX_TOKENS,
    }
    if tools:
        kwargs["tools"] = tools

    for attempt in range(4):
        try:
            response = client().chat.completions.create(**kwargs)
            break
        except (APIConnectionError, APITimeoutError, InternalServerError):
            if attempt == 3:
                raise
            time.sleep(15 * (attempt + 1))

    choice = response.choices[0]
    content = strip_thinking(choice.message.content or "")
    message: dict = {"role": "assistant", "content": content}
    if choice.message.tool_calls:
        message["tool_calls"] = [
            {"id": tc.id, "type": "function", "function": {"name": tc.function.name, "arguments": tc.function.arguments}}
            for tc in choice.message.tool_calls
        ]
    usage = {
        "prompt_tokens": getattr(response.usage, "prompt_tokens", 0) or 0,
        "completion_tokens": getattr(response.usage, "completion_tokens", 0) or 0,
        "finish_reason": choice.finish_reason,
    }
    return message, usage


def strip_thinking(text: str) -> str:
    """Some servers leave <think>...</think> inline instead of splitting it out."""
    return re.sub(r"<think>.*?</think>", "", text, flags=re.S).strip()
