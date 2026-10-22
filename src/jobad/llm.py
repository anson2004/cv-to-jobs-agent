"""The only module that talks to a language model.

One method matters: `complete_json(schema, ...)`. It asks for JSON, validates
against a Pydantic model, and on failure feeds the validation error back to the
model once. Provider is any OpenAI-compatible endpoint (Groq by default).
"""

from __future__ import annotations

import asyncio
import json
import time
from collections.abc import Sequence
from typing import Any, Required, TypedDict, TypeVar

from openai import AsyncOpenAI, BadRequestError, OpenAI, RateLimitError
from openai.types.chat import (
    ChatCompletion,
    ChatCompletionMessage,
    ChatCompletionMessageParam,
    ChatCompletionToolChoiceOptionParam,
    ChatCompletionToolUnionParam,
)
from openai.types.shared_params import ResponseFormatJSONObject
from pydantic import BaseModel, ValidationError

from .config import Settings
from .trace import Tracer

T = TypeVar("T", bound=BaseModel)
Messages = list[ChatCompletionMessageParam]


class _CreateParams(TypedDict, total=False):
    """Keyword arguments for chat.completions.create, as built by `LLM._params`."""

    model: Required[str]
    messages: Required[Messages]
    max_tokens: Required[int]
    temperature: Required[float]
    extra_body: Required[dict[str, str]]
    response_format: ResponseFormatJSONObject


def _schema_hint(schema: type[BaseModel]) -> str:
    """JSON schema with descriptions stripped. The prompts explain the fields;
    repeating descriptions here costs ~300 tokens per call on the N-times path."""

    def strip(node: Any) -> Any:
        if isinstance(node, dict):
            return {k: strip(v) for k, v in node.items() if k not in ("description", "title")}
        if isinstance(node, list):
            return [strip(x) for x in node]
        return node

    return json.dumps(strip(schema.model_json_schema()), separators=(",", ":"))


def _extract_json(text: str) -> str:
    """Models occasionally wrap JSON in prose or fences. Pull out the outermost object."""
    text = text.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.lower().startswith("json"):
            text = text[4:]
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1:
        raise ValueError("no JSON object in response")
    return text[start : end + 1]


class LLM:
    def __init__(self, settings: Settings, tracer: Tracer):
        self.s = settings
        self.tracer = tracer
        self.client = OpenAI(base_url=settings.llm_base_url, api_key=settings.llm_api_key, max_retries=4, timeout=90)
        self.aclient = AsyncOpenAI(base_url=settings.llm_base_url, api_key=settings.llm_api_key, max_retries=4, timeout=90)
        self._pause_until = 0.0  # shared across concurrent scoring workers

    # ---- sync -----------------------------------------------------------
    def complete_json(
        self,
        schema: type[T],
        *,
        step: str,
        model: str,
        system: str,
        user: str,
        reasoning_effort: str = "low",
        max_tokens: int = 1500,
        fix_attempts: int = 1,
        meta: dict[str, Any] | None = None,
    ) -> T:
        messages = self._messages(schema, system, user)
        last_err: Exception | None = None
        for attempt in range(1, fix_attempts + 2):
            t0 = time.time()
            try:
                resp = self.client.chat.completions.create(**self._params(model, messages, max_tokens, reasoning_effort, json_mode=True))
            except BadRequestError as e:
                if "json_validate_failed" not in str(e):
                    raise
                # Groq returns this when the model ran out of tokens before emitting JSON
                # (reasoning eats the budget). Retry once: plain text, bigger budget, less reasoning.
                self.tracer.record(step=step, model=model, prompt_tokens=0, completion_tokens=0, latency_s=time.time() - t0, ok=False, attempt=attempt, error="json_validate_failed; retrying without json mode", meta=meta)
                t0 = time.time()
                resp = self.client.chat.completions.create(**self._params(model, messages, max_tokens * 2, "low", json_mode=False))
            text = resp.choices[0].message.content or ""
            try:
                obj = schema.model_validate_json(_extract_json(text))
                self._trace(step, model, resp, t0, True, attempt, obj.model_dump(), None, meta)
                return obj
            except (ValidationError, ValueError, json.JSONDecodeError) as e:
                last_err = e
                self._trace(step, model, resp, t0, False, attempt, text[:2000], str(e)[:500], meta)
                messages = messages + self._fix_request(text, e)
        raise RuntimeError(f"{step}: no valid output after {fix_attempts + 1} attempts: {last_err}")

    # ---- async (used for scoring under a semaphore) --------------------
    async def acomplete_json(
        self,
        schema: type[T],
        *,
        step: str,
        model: str,
        system: str,
        user: str,
        reasoning_effort: str = "low",
        max_tokens: int = 800,
        fix_attempts: int = 1,
        meta: dict[str, Any] | None = None,
        sem: asyncio.Semaphore | None = None,
    ) -> T:
        messages = self._messages(schema, system, user)
        last_err: Exception | None = None
        for attempt in range(1, fix_attempts + 2):
            async with (sem or asyncio.Semaphore(1)):
                t0 = time.time()  # measure the call, not the queue wait
                resp = await self._acreate_with_backoff(model, messages, max_tokens, reasoning_effort)
            text = resp.choices[0].message.content or ""
            try:
                obj = schema.model_validate_json(_extract_json(text))
                self._trace(step, model, resp, t0, True, attempt, obj.model_dump(), None, meta)
                return obj
            except (ValidationError, ValueError, json.JSONDecodeError) as e:
                last_err = e
                self._trace(step, model, resp, t0, False, attempt, text[:2000], str(e)[:500], meta)
                messages = messages + self._fix_request(text, e)
        raise RuntimeError(f"{step}: no valid output after {fix_attempts + 1} attempts: {last_err}")

    async def _acreate_with_backoff(self, model: str, messages: Messages, max_tokens: int, reasoning_effort: str, give_up_after_s: float = 900.0) -> ChatCompletion:
        """Groq free tier is 8K tokens/min per model. On 429 every worker must
        pause together, for as long as the `retry-after` header says, otherwise
        each worker burns its own retries during the same burst and the batch
        fails wholesale. We give up only after `give_up_after_s` of waiting."""
        deadline = time.time() + give_up_after_s
        delay = 5.0
        while True:
            wait = self._pause_until - time.time()
            if wait > 0:
                await asyncio.sleep(wait)
            try:
                return await self.aclient.chat.completions.create(**self._params(model, messages, max_tokens, reasoning_effort, json_mode=True))
            except RateLimitError as e:
                ra = None
                try:
                    ra = float(e.response.headers.get("retry-after", ""))
                except (TypeError, ValueError, AttributeError):
                    pass
                delay = min(max(ra + 0.5 if ra else delay * 1.5, 2.0), 90.0)
                if time.time() + delay > deadline:
                    raise
                self._pause_until = max(self._pause_until, time.time() + delay)
            except BadRequestError as e:
                if "json_validate_failed" not in str(e):
                    raise
                return await self.aclient.chat.completions.create(**self._params(model, messages, max_tokens * 2, "low", json_mode=False))

    @staticmethod
    def _params(model: str, messages: Messages, max_tokens: int, reasoning_effort: str, *, json_mode: bool) -> _CreateParams:
        """Provider quirks live here and nowhere else.

        Groq: gpt-oss takes reasoning_effort low/medium/high; Qwen3 takes "none" or
        "default" and would otherwise stream its chain of thought into `content`.
        reasoning_format="hidden" keeps reasoning out of the content on both.
        """
        extra: dict[str, str] = {"reasoning_format": "hidden"}
        if "qwen" in model.lower():
            extra["reasoning_effort"] = "none" if reasoning_effort == "low" else "default"
        else:
            extra["reasoning_effort"] = reasoning_effort
        p: _CreateParams = {"model": model, "messages": messages, "max_tokens": max_tokens, "temperature": 0.2, "extra_body": extra}
        if json_mode:
            p["response_format"] = {"type": "json_object"}
        return p

    # ---- tool use (agentic planning) -----------------------------------
    def chat_with_tools(
        self,
        *,
        step: str,
        model: str,
        messages: Messages,
        tools: Sequence[ChatCompletionToolUnionParam],
        tool_choice: ChatCompletionToolChoiceOptionParam = "auto",
        reasoning_effort: str = "medium",
        max_tokens: int = 1500,
        meta: dict[str, Any] | None = None,
    ) -> ChatCompletionMessage:
        """One assistant turn that may contain tool calls. Returns the message
        object; the caller executes tools and appends results. Traced like any call."""
        t0 = time.time()
        resp = self.client.chat.completions.create(
            model=model,
            messages=messages,
            tools=tools,
            tool_choice=tool_choice,
            max_tokens=max_tokens,
            temperature=0.2,
            extra_body={"reasoning_effort": reasoning_effort, "reasoning_format": "hidden"},
        )
        msg = resp.choices[0].message
        calls = [{"name": tc.function.name, "arguments": tc.function.arguments[:300]} for tc in (msg.tool_calls or []) if tc.type == "function"]
        self._trace(step, model, resp, t0, True, 1, {"tool_calls": calls, "content": (msg.content or "")[:500]}, None, meta)
        return msg

    # ---- helpers --------------------------------------------------------
    @staticmethod
    def _messages(schema: type[BaseModel], system: str, user: str) -> Messages:
        sys_full = (
            f"{system.strip()}\n\n"
            "Respond with a single JSON object and nothing else. It must validate against this JSON Schema:\n"
            f"{_schema_hint(schema)}"
        )
        return [{"role": "system", "content": sys_full}, {"role": "user", "content": user}]

    @staticmethod
    def _fix_request(text: str, err: Exception) -> Messages:
        return [
            {"role": "assistant", "content": text},
            {"role": "user", "content": f"That JSON failed validation:\n{err}\nReturn corrected JSON only."},
        ]

    def _trace(self, step: str, model: str, resp: ChatCompletion, t0: float, ok: bool, attempt: int, output: Any, error: str | None, meta: dict[str, Any] | None) -> None:
        usage = resp.usage
        self.tracer.record(
            step=step,
            model=model,
            prompt_tokens=usage.prompt_tokens if usage else 0,
            completion_tokens=usage.completion_tokens if usage else 0,
            latency_s=time.time() - t0,
            ok=ok,
            attempt=attempt,
            output=output,
            error=error,
            meta=meta,
        )
