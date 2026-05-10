from __future__ import annotations

import sys
import types

import pytest
from pydantic import SecretStr

from agent_integrations.llm.chat_model_factory import build_chat_model


def test_build_chat_model_constructs_chatdeepseek_directly(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    recorded: dict[str, object] = {}

    class RecordingChatDeepSeek:
        def __init__(self, **kwargs: object) -> None:
            recorded.update(kwargs)

    fake_module = types.ModuleType("langchain_deepseek")
    fake_module.__dict__["ChatDeepSeek"] = RecordingChatDeepSeek
    monkeypatch.setitem(sys.modules, "langchain_deepseek", fake_module)

    client = build_chat_model(
        llm_provider="deepseek",
        llm_model="deepseek-reasoner",
        llm_timeout_seconds=7.5,
        llm_max_retries=3,
        deepseek_api_key="sk-test",
        openai_api_key=None,
    )

    assert client.__class__.__name__ == "RecordingChatDeepSeek"
    api_key = recorded["api_key"]
    assert isinstance(api_key, SecretStr)
    assert recorded == {
        "api_key": api_key,
        "model": "deepseek-reasoner",
        "temperature": 0,
        "streaming": True,
        "timeout": 7.5,
        "max_retries": 3,
    }
    assert api_key.get_secret_value() == "sk-test"


def test_build_chat_model_constructs_chatopenai_directly(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    recorded: dict[str, object] = {}

    class RecordingChatOpenAI:
        def __init__(self, **kwargs: object) -> None:
            recorded.update(kwargs)

    fake_module = types.ModuleType("langchain_openai")
    fake_module.__dict__["ChatOpenAI"] = RecordingChatOpenAI
    monkeypatch.setitem(sys.modules, "langchain_openai", fake_module)

    client = build_chat_model(
        llm_provider="openai",
        llm_model="gpt-4.1-mini",
        llm_timeout_seconds=9.0,
        llm_max_retries=2,
        deepseek_api_key=None,
        openai_api_key="sk-openai",
    )

    assert client.__class__.__name__ == "RecordingChatOpenAI"
    api_key = recorded["api_key"]
    assert isinstance(api_key, SecretStr)
    assert recorded == {
        "api_key": api_key,
        "model": "gpt-4.1-mini",
        "temperature": 0,
        "streaming": True,
        "timeout": 9.0,
        "max_retries": 2,
    }
    assert api_key.get_secret_value() == "sk-openai"


def test_build_chat_model_requires_provider_key() -> None:
    with pytest.raises(ValueError, match="OPENAI_API_KEY"):
        build_chat_model(
            llm_provider="openai",
            llm_model="gpt-4.1-mini",
            llm_timeout_seconds=9.0,
            llm_max_retries=2,
            deepseek_api_key=None,
            openai_api_key=None,
        )
