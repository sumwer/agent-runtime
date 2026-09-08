"""集中配置：路径、Opik 数据源、模型接入（DeepSeek Anthropic 兼容端点）。"""
from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]

load_dotenv(ROOT / ".env")

# ---- Opik 数据源 ----
OPIK_URL_OVERRIDE = os.environ.setdefault("OPIK_URL_OVERRIDE", "http://localhost:5173/api")
OPIK_WORKSPACE = os.environ.setdefault("OPIK_WORKSPACE", "default")
OPIK_PROJECT_NAME = os.environ.setdefault("OPIK_PROJECT_NAME", "minor-safety-qlora")
# 本地自托管场景不应向 comet 云端发送遥测
os.environ.setdefault("OPIK_TRACK_DISABLE", "true")

# ---- Skill 执行环境 ----
VENV_PYTHON = ROOT / ".venv" / "bin" / "python"
MCP_SERVER_ENTRY = ROOT / "mcp_server" / "opik_mcp.py"
OUTPUTS_DIR = ROOT / "outputs"
CACHE_DIR = OUTPUTS_DIR / "cache"
RESULTS_DIR = OUTPUTS_DIR / "results"

# ---- Agent 行为 ----
MAX_TURNS = 40
SCRIPT_TIMEOUT_SECONDS = 120

# 透传给 Claude Agent SDK 底层 CLI 的环境变量（DeepSeek 官方推荐配置）
ANTHROPIC_ENV_KEYS = [
    "ANTHROPIC_BASE_URL",
    "ANTHROPIC_AUTH_TOKEN",
    "ANTHROPIC_API_KEY",
    "ANTHROPIC_MODEL",
    "ANTHROPIC_DEFAULT_OPUS_MODEL",
    "ANTHROPIC_DEFAULT_SONNET_MODEL",
    "ANTHROPIC_DEFAULT_HAIKU_MODEL",
    "CLAUDE_CODE_SUBAGENT_MODEL",
    "CLAUDE_CODE_EFFORT_LEVEL",
    "CLAUDE_CODE_AUTO_COMPACT_WINDOW",
]

# 允许 Agent 使用的工具：内置工具 + 本 MCP Server 的全部取数工具
ALLOWED_TOOLS = [
    "Skill",
    "Read",
    "Write",
    "Bash",
    "Glob",
    "Grep",
    "mcp__opik__list_experiments",
    "mcp__opik__get_experiment",
    "mcp__opik__get_experiment_items",
    "mcp__opik__search_traces",
    "mcp__opik__get_trace",
    "mcp__opik__get_scores",
    "mcp__opik__list_reports",
    "mcp__opik__get_report",
]


def anthropic_env() -> dict[str, str]:
    """从当前进程环境提取 Anthropic/DeepSeek 接入变量，供 SDK 注入 CLI。"""
    return {key: os.environ[key] for key in ANTHROPIC_ENV_KEYS if os.environ.get(key)}
