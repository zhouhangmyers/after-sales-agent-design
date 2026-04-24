from __future__ import annotations

from langchain_core.language_models.chat_models import BaseChatModel
from pydantic import SecretStr


def build_chat_model(
    *,
    llm_provider: str,
    llm_model: str,
    llm_timeout_seconds: float,
    llm_max_retries: int,
    deepseek_api_key: str | None,
    openai_api_key: str | None,
) -> BaseChatModel:
    if llm_provider == "deepseek":
        if deepseek_api_key is None:
            raise ValueError("DEEPSEEK_API_KEY is required when llm_provider=deepseek")
        try:
            from langchain_deepseek import ChatDeepSeek
        except ImportError as exc:
            raise RuntimeError(
                "DeepSeek support requires the `langchain-deepseek` package."
            ) from exc
        return ChatDeepSeek(
            api_key=SecretStr(deepseek_api_key),
            model=llm_model,
            temperature=0,
            streaming=True,
            timeout=llm_timeout_seconds,
            max_retries=llm_max_retries,
        )

    if llm_provider == "openai":
        if openai_api_key is None:
            raise ValueError("OPENAI_API_KEY is required when llm_provider=openai")
        try:
            from langchain_openai import ChatOpenAI
        except ImportError as exc:
            raise RuntimeError(
                "OpenAI support requires the `langchain-openai` package."
            ) from exc
        return ChatOpenAI(
            api_key=SecretStr(openai_api_key),
            model=llm_model,
            temperature=0,
            streaming=True,
            timeout=llm_timeout_seconds,
            max_retries=llm_max_retries,
        )

    raise ValueError(f"unsupported llm provider: {llm_provider}")
