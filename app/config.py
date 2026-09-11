import os
import shlex
import sys
from pathlib import Path

from dotenv import dotenv_values
from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parent.parent


def _dotenv() -> dict[str, str]:
    return {k: v for k, v in dotenv_values(ROOT / '.env').items() if v is not None}


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=ROOT / '.env', extra='ignore')

    DATABASE_URL: str = 'postgresql+psycopg://agent:agent@localhost:55432/agent_runtime'
    TEST_DATABASE_URL: str = 'postgresql+psycopg://agent:agent@localhost:55432/agent_runtime_test'
    MODEL: str = 'claude-opus-5'
    ANTHROPIC_MODEL: str = ''
    ANTHROPIC_API_KEY: str = ''
    ANTHROPIC_AUTH_TOKEN: str = ''
    ANTHROPIC_BASE_URL: str = ''
    WORKER_CONCURRENCY: int = Field(default=2, ge=1, le=32)
    # Empty disables authentication; set it to require Authorization: Bearer <token>.
    API_TOKEN: str = ''
    ARTIFACTS_DIR: Path = ROOT / 'artifacts'
    SKILLS_DIR: Path = ROOT / 'skills'
    SANDBOX_IMAGE: str = 'agent-runtime-sandbox:latest'
    SANDBOX_TIMEOUT_SECONDS: int = Field(default=120, ge=1, le=120)
    TASK_TIMEOUT_SECONDS: int = Field(default=600, ge=1, le=600)
    RECURSION_LIMIT: int = Field(default=40, ge=2, le=100)
    MCP_TRANSPORT: str = 'stdio'
    MCP_STDIO_CMD: str = ''
    MCP_HTTP_URL: str = ''
    MCP_HTTP_TOKEN: str = ''
    MAX_EXPORT_ROWS: int = Field(default=5000, ge=1, le=100000)

    @model_validator(mode='after')
    def legacy_model(self):
        if 'MODEL' not in self.model_fields_set and self.ANTHROPIC_MODEL:
            self.MODEL = self.ANTHROPIC_MODEL.removesuffix('[1m]')
        return self

    def mcp_config(self) -> dict:
        if self.MCP_TRANSPORT in {'http', 'streamable_http'}:
            if not self.MCP_HTTP_URL:
                raise ValueError('MCP_HTTP_URL is required')
            cfg = {'transport': 'streamable_http', 'url': self.MCP_HTTP_URL}
            if self.MCP_HTTP_TOKEN:
                cfg['headers'] = {'Authorization': f'Bearer {self.MCP_HTTP_TOKEN}'}
            return cfg
        if self.MCP_TRANSPORT != 'stdio':
            raise ValueError('MCP_TRANSPORT must be stdio or http')
        parts = shlex.split(self.MCP_STDIO_CMD) if self.MCP_STDIO_CMD else [
            sys.executable, '-m', 'mock_mcp.server']
        # MCP stdio client only passes a minimal env when env is omitted; the data
        # source needs the Opik credentials, project and proxy settings. .env is the
        # base so OPIK_* can be kept there, the real process environment wins.
        return {'transport': 'stdio', 'command': parts[0], 'args': parts[1:],
                'cwd': str(ROOT), 'env': {**_dotenv(), **os.environ}}


settings = Settings()
