import re

# Some Groq models (e.g. reasoning-tuned models like qwen/qwen3.6-27b) emit their
# internal chain-of-thought wrapped in <think>...</think> before the actual answer.
# This must never be shown to the user - only the final answer after the tag.
_THINK_BLOCK_RE = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)
# Handles the case where the closing tag is missing/truncated (e.g. hit max_tokens
# mid-thought) - in that case there is no usable final answer, so drop everything
# from the opening tag onward.
_UNCLOSED_THINK_RE = re.compile(r"<think>.*$", re.DOTALL | re.IGNORECASE)


def strip_reasoning(text: str) -> str:
    """Remove <think>...</think> reasoning blocks some models emit, returning
    only the final answer. Safe to call on any text, including text with no
    think tags at all (returned unchanged, just whitespace-trimmed)."""

    if not text:
        return text

    cleaned = _THINK_BLOCK_RE.sub("", text)
    cleaned = _UNCLOSED_THINK_RE.sub("", cleaned)
    return cleaned.strip()
