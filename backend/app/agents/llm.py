from typing import Any

from langchain.chat_models import init_chat_model

from app.config import Settings, get_settings


def build_chat_model(settings: Settings | None = None, timeout: float | None = None) -> Any:
    settings = settings or get_settings()
    kwargs = {"timeout": timeout} if timeout is not None else {}
    return init_chat_model(f"{settings.CHAT_PROVIDER}:{settings.CHAT_MODEL}", **kwargs)


def build_verify_model(settings: Settings | None = None, timeout: float | None = None) -> Any:
    settings = settings or get_settings()
    kwargs = {"timeout": timeout} if timeout is not None else {}
    return init_chat_model(f"{settings.CHAT_PROVIDER}:{settings.VERIFY_MODEL}", **kwargs)
