"""Thin wrapper around the Claude API: one place for models, logging and JSON parsing.

The SDK is imported lazily so the data pipeline runs without it.
Set ANTHROPIC_API_KEY in the environment where the agent runs.
"""
from __future__ import annotations

import json
import re
import time
from pathlib import Path

import yaml

from .config import CONFIG_DIR


def settings() -> dict:
    return yaml.safe_load((CONFIG_DIR / "llm.yaml").read_text(encoding="utf-8"))


class LLM:
    def __init__(self, log_path: Path):
        import anthropic  # noqa: PLC0415  (optional dependency)
        self.client = anthropic.Anthropic()
        self.cfg = settings()
        self.log_path = log_path

    def call(self, role: str, system: str, messages: list[dict], tools: list[dict] | None = None,
             max_tokens: int | None = None, output_schema: dict | None = None) -> tuple[str, list[dict], dict]:
        """Return (final text, raw content blocks as dicts, usage summed over the turn).

        No sampling settings (temperature, top_p, top_k) are sent: current Claude models and SDKs
        do not accept them. A turn the API pauses during a long server-side tool run (web search),
        stop_reason "pause_turn", is resumed until it finishes (at most `max_continuations` times).
        `output_schema` (a JSON schema) makes the API return JSON that matches it (structured outputs);
        do not combine it with web search, whose citations the API does not allow with it.
        usage["stop_reason"] is the final stop reason ("end_turn", "max_tokens", ...).
        """
        model = self.cfg["models"][role]
        kw = dict(model=model, system=system, messages=list(messages),
                  max_tokens=max_tokens or self.cfg["max_tokens"])
        if tools:
            kw["tools"] = tools
        if output_schema:
            kw["output_config"] = {"format": {"type": "json_schema", "schema": output_schema}}
        t0 = time.time()
        blocks: list[dict] = []
        usage: dict = {}
        for _ in range(1 + int(self.cfg.get("max_continuations", 3))):
            resp = self.client.messages.create(**kw)
            got = [b.model_dump() for b in resp.content]
            blocks += got
            for k, v in resp.usage.model_dump().items():
                if isinstance(v, (int, float)) and not isinstance(v, bool):
                    usage[k] = usage.get(k, 0) + v
                elif isinstance(v, dict):                      # e.g. server_tool_use.web_search_requests
                    for k2, v2 in v.items():
                        if isinstance(v2, (int, float)) and not isinstance(v2, bool):
                            usage[f"{k}.{k2}"] = usage.get(f"{k}.{k2}", 0) + v2
            usage["stop_reason"] = getattr(resp, "stop_reason", None)
            if usage["stop_reason"] != "pause_turn":
                break
            kw["messages"] = kw["messages"] + [{"role": "assistant", "content": got}]
        text = "".join(b.get("text", "") for b in blocks if b.get("type") == "text")
        with self.log_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps({"ts": t0, "secs": round(time.time() - t0, 2), "role": role, "model": model,
                                "system": system, "messages": messages, "blocks": blocks, "usage": usage},
                               ensure_ascii=False, default=str) + "\n")
        return text, blocks, usage


def parse_json(text: str):
    """Take the last ```json block, or the outermost JSON value in the text."""
    m = re.findall(r"```(?:json)?\s*(.*?)```", text, flags=re.S)
    cand = m[-1] if m else text
    start = min([i for i in (cand.find("{"), cand.find("[")) if i >= 0], default=-1)
    if start < 0:
        raise ValueError("no JSON found in model output")
    end = max(cand.rfind("}"), cand.rfind("]"))
    return json.loads(cand[start:end + 1])


def search_results(blocks: list[dict]) -> dict[str, dict]:
    """URLs the web search tool actually returned, with title and page age."""
    out = {}
    for b in blocks:
        if b.get("type") == "web_search_tool_result" and isinstance(b.get("content"), list):
            for r in b["content"]:
                if r.get("type") == "web_search_result":
                    out[r["url"]] = {"title": r.get("title"), "page_age": r.get("page_age")}
    return out


def run_cost(log_path: Path, start_line: int = 0) -> dict:
    """Estimated cost of the calls logged from `start_line` on, using `prices` in config/llm.yaml."""
    cfg = settings()
    prices, search_price = cfg.get("prices", {}), float(cfg.get("web_search_per_1000", 10)) / 1000
    out = {"calls": 0, "input_tokens": 0, "output_tokens": 0, "searches": 0, "usd": 0.0}
    if not log_path.exists():
        return out
    for line in log_path.read_text(encoding="utf-8").splitlines()[start_line:]:
        try:
            e = json.loads(line)
        except json.JSONDecodeError:
            continue
        u = e.get("usage") or {}
        tin = sum(u.get(k, 0) for k in ("input_tokens", "cache_creation_input_tokens", "cache_read_input_tokens"))
        tout, srch = u.get("output_tokens", 0), u.get("server_tool_use.web_search_requests", 0)
        p = prices.get(e.get("model"), {})
        tier = p.get("over_100k") if p.get("over_100k") and tin > 100_000 else p
        out["calls"] += 1
        out["input_tokens"] += tin
        out["output_tokens"] += tout
        out["searches"] += srch
        out["usd"] += tin / 1e6 * tier.get("input", 0) + tout / 1e6 * tier.get("output", 0) + srch * search_price
    return out
