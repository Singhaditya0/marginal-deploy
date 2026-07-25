"""
llm_service.py  (free-deploy variant)
---------------------------------------
Same interface as the local Ollama version's llm_service.py, but calls
Groq's free, no-credit-card API instead of a local Ollama server.

Set the GROQ_API_KEY environment variable (get one free at
https://console.groq.com/keys — no card required) before running.
Optionally set GROQ_MODEL to override the default model.
"""

import os
import requests
from typing import List, Tuple

GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
GROQ_MODEL = os.environ.get("GROQ_MODEL", "llama-3.1-8b-instant")
REQUEST_TIMEOUT = 60


class LLMServiceError(Exception):
    pass


def _call_groq(prompt: str, max_tokens: int = 600) -> str:
    api_key = os.environ.get("GROQ_API_KEY")
    if not api_key:
        raise LLMServiceError(
            "GROQ_API_KEY is not set. Get a free key at https://console.groq.com/keys "
            "(no credit card required) and set it as an environment variable."
        )

    try:
        response = requests.post(
            GROQ_URL,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": GROQ_MODEL,
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": max_tokens,
                "temperature": 0.3,
            },
            timeout=REQUEST_TIMEOUT,
        )
    except requests.exceptions.ConnectionError as exc:
        raise LLMServiceError("Could not reach Groq's API — check the server's internet connection.") from exc
    except requests.exceptions.Timeout as exc:
        raise LLMServiceError("Groq's API took too long to respond. Try again.") from exc

    if response.status_code == 401:
        raise LLMServiceError("Groq rejected the API key — check GROQ_API_KEY is set correctly.")
    if response.status_code == 429:
        raise LLMServiceError("Groq's free-tier rate limit was hit. Wait a moment and try again.")
    if not response.ok:
        raise LLMServiceError(f"Groq API error: HTTP {response.status_code} — {response.text[:200]}")

    data = response.json()
    choices = data.get("choices", [])
    if not choices:
        raise LLMServiceError("Groq returned an empty response.")
    return choices[0]["message"]["content"].strip()


def summarize(full_text: str, style: str = "concise") -> str:
    max_chars = 12000
    truncated = full_text[:max_chars]
    was_truncated = len(full_text) > max_chars

    instructions = {
        "concise": "Write a concise 3-5 sentence summary of the document below.",
        "detailed": "Write a thorough, well-organized summary of the document below, "
                    "covering all major sections and points, in 3-5 short paragraphs.",
        "bullets": "Summarize the document below as a list of 6-10 key bullet points, "
                   "one per line, starting each with '- '.",
    }
    instruction = instructions.get(style, instructions["concise"])

    prompt = (
        f"{instruction}\n\n"
        "Only use information present in the document. Do not invent facts.\n\n"
        f"DOCUMENT:\n{truncated}\n\nSUMMARY:"
    )

    summary = _call_groq(prompt, max_tokens=700)
    if was_truncated:
        summary += "\n\n(Note: this document was long, so the summary is based on the first portion of it.)"
    return summary


def answer_question(question: str, retrieved_chunks: List[Tuple[str, float, int]]) -> str:
    if not retrieved_chunks:
        return "I couldn't find anything relevant to that question in the document."

    context_blocks = []
    for i, (chunk, _score, _idx) in enumerate(retrieved_chunks, start=1):
        context_blocks.append(f"[{i}] {chunk}")
    context_text = "\n\n".join(context_blocks)

    prompt = (
        "Answer the question using ONLY the numbered excerpts below. "
        "Cite the excerpt number(s) you used in square brackets, like [1] or [1][3], "
        "right after the relevant sentence. "
        "If the excerpts don't contain the answer, say so honestly instead of guessing.\n\n"
        f"EXCERPTS:\n{context_text}\n\n"
        f"QUESTION: {question}\n\nANSWER:"
    )

    return _call_groq(prompt, max_tokens=500)
