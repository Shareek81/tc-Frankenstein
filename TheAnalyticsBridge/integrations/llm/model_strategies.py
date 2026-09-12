from collections.abc import Mapping
from typing import Protocol

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_ollama import ChatOllama

from .llm_scorer import DangerScoreResponse


class ModelStrategy(Protocol):
    def create_model(self, configuration: Mapping[str, str]) -> BaseChatModel: ...


class GeminiModelStrategy:
    def create_model(self, configuration: Mapping[str, str]) -> BaseChatModel:
        return ChatGoogleGenerativeAI(
            model=configuration["LLM_MODEL"],
            temperature=0,
            timeout=None,
            max_retries=0,
        )


class LocalModelStrategy:
    def create_model(self, configuration: Mapping[str, str]) -> BaseChatModel:
        return ChatOllama(
            model=configuration["LLM_MODEL"],
            temperature=0,
            format=DangerScoreResponse.model_json_schema(),
        )


MODEL_STRATEGIES: dict[str, ModelStrategy] = {
    "gemini": GeminiModelStrategy(),
    "local": LocalModelStrategy(),
}


def create_chat_model(configuration: Mapping[str, str]) -> BaseChatModel:
    model_type = configuration["LLM_MODEL_TYPE"].strip().lower()
    if model_type not in MODEL_STRATEGIES:
        raise ValueError("LLM_MODEL_TYPE must be gemini or local")
    return MODEL_STRATEGIES[model_type].create_model(configuration)