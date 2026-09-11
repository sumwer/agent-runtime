"""The only provider binding. MODEL and endpoint are deployment configuration."""
from langchain_anthropic import ChatAnthropic

from app.config import settings


def get_chat_model():
    key = settings.ANTHROPIC_API_KEY or settings.ANTHROPIC_AUTH_TOKEN
    if not key:
        raise ValueError('Configure ANTHROPIC_API_KEY before running model tasks')
    kwargs = dict(model=settings.MODEL, api_key=key, max_retries=2,
                  timeout=60, max_tokens=8192)
    if settings.ANTHROPIC_BASE_URL:
        kwargs['base_url'] = settings.ANTHROPIC_BASE_URL
    return ChatAnthropic(**kwargs)
