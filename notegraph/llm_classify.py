"""LLM-based needinfo classifier via OpenAI-compatible chat endpoint.

Fallback for ambiguous cases where heuristics cannot confidently
determine whether the user needs to act on an issue.  Talks directly
to any OpenAI-compatible ``/chat/completions`` endpoint (e.g. a local
litellm proxy, Ollama, vLLM, or the OpenAI API itself).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import requests

logger = logging.getLogger(__name__)

_MAX_COMMENT_CHARS = 500
_MAX_COMMENTS = 5

_SYSTEM_PROMPT = (
    "You are classifying whether a GitHub or Jira issue needs the user's "
    "attention. The user is `{username}`. Given the issue title and recent "
    'comments, answer with a single word: "needinfo" if the user needs to '
    'respond or take action, or "waiting" if the ball is in someone else\'s '
    "court. Ignore bot comments and CI notifications unless they indicate a "
    "failure the user should fix."
)


@dataclass(frozen=True)
class LLMConfig:
    """Configuration for the OpenAI-compatible LLM endpoint."""

    endpoint: str = ""
    token: str = ""
    model: str = "gpt-4o-mini"


def _chat_completion(
    cfg: LLMConfig,
    messages: list[dict[str, str]],
    *,
    max_tokens: int = 10,
    temperature: float = 0,
) -> dict:
    """Call an OpenAI-compatible ``/chat/completions`` endpoint.

    Raises:
        requests.HTTPError: On non-2xx response.
    """
    url = f"{cfg.endpoint.rstrip('/')}/chat/completions"
    headers: dict[str, str] = {"Content-Type": "application/json"}
    if cfg.token:
        headers["Authorization"] = f"Bearer {cfg.token}"
    payload = {
        "model": cfg.model,
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": temperature,
    }
    resp = requests.post(url, json=payload, headers=headers, timeout=30)
    resp.raise_for_status()
    return resp.json()


def classify_needinfo(
    title: str,
    comments: list[str],
    username: str,
    *,
    cfg: LLMConfig | None = None,
) -> bool:
    """Classify whether *username* needs to act on this issue.

    Args:
        title: Issue / PR title.
        comments: Recent comment bodies (newest last).
        username: The authenticated user's handle.
        cfg: LLM endpoint / token / model settings.

    Returns:
        ``True`` if the LLM says needinfo, ``False`` if waiting.
        Defaults to ``True`` (safe fallback) on any failure.
    """
    if cfg is None:
        cfg = LLMConfig()

    if not cfg.endpoint:
        logger.debug("No LLM endpoint configured; defaulting to needinfo=True.")
        return True

    truncated = [c[:_MAX_COMMENT_CHARS] for c in comments[-_MAX_COMMENTS:]]
    comment_block = "\n---\n".join(truncated) if truncated else "(no comments)"

    user_msg = f"Issue title: {title}\n\nRecent comments:\n{comment_block}"
    system_msg = _SYSTEM_PROMPT.format(username=username)

    try:
        data = _chat_completion(
            cfg,
            [
                {"role": "system", "content": system_msg},
                {"role": "user", "content": user_msg},
            ],
        )
    except Exception:  # noqa: BLE001
        logger.warning("LLM classification failed; defaulting to needinfo=True.")
        return True
    else:
        answer = data["choices"][0]["message"]["content"].strip().lower()
        logger.debug("LLM classify %r -> %r", title[:60], answer)
        return answer != "waiting"
