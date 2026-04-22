"""Prompt registry for conversation turns."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Prompt:
    name: str
    version: str
    system_instructions: str


_PROMPT_REGISTRY: dict[tuple[str, str], str] = {
    (
        "conversation-tools",
        "v1",
    ): (
        "You are a conversation model running inside a LangGraph workflow. "
        "Use the provided tools when needed. "
        "Call at most one tool per turn. "
        "If no tool is needed, answer the user directly in concise Chinese."
    ),
    (
        "conversation-direct",
        "v1",
    ): (
        "You are a conversation model running inside a workflow. "
        "Do not call any tools. "
        "Answer the user directly in concise Chinese."
    ),
}

_PROMPT_ALIASES: dict[tuple[str, str], tuple[str, str]] = {
    ("tool-agent", "v1"): ("conversation-tools", "v1"),
    ("direct-agent", "v1"): ("conversation-direct", "v1"),
}


def _canonical_prompt_key(name: str, version: str) -> tuple[str, str]:
    return _PROMPT_ALIASES.get((name, version), (name, version))


def resolve_prompt(name: str, version: str) -> Prompt:
    canonical_name, canonical_version = _canonical_prompt_key(name, version)
    system_instructions = _PROMPT_REGISTRY.get((canonical_name, canonical_version))
    if system_instructions is None:
        raise ValueError(f"unknown prompt: {name}@{version}")
    return Prompt(
        name=canonical_name,
        version=canonical_version,
        system_instructions=system_instructions,
    )
