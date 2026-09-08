"""Agent Runtime 编排入口：基于 Claude Agent SDK 驱动任务闭环。

职责边界：
- Skill 发现与执行细节交给 SDK（setting_sources 加载项目级 .claude/skills）与 SKILL.md；
- 取数统一走 MCP（mcp__opik__*），Runtime 不直连 Opik；
- Runtime 只负责：组装配置 → 驱动 Agent → 提取并校验结构化结果。
"""
from __future__ import annotations

import json
import re
from typing import Any

from claude_agent_sdk import ClaudeAgentOptions, query
from claude_agent_sdk.types import ResultMessage

from agent_runtime import config
from agent_runtime.result_schema import validate_result

SYSTEM_PROMPT = """你是评测平台的云侧分析 Agent（Agent Runtime）。用户会给出自然语言分析任务，\
例如分析指标分布、对比两个版本、挖掘 Bad Case。

工作规则：

1. 优先使用项目内已安装的分析 Skill（.claude/skills/ 目录）：
   - metric-distribution：单个实验的得分分布
   - version-diff：两个实验的版本差异对比
   - badcase-mining：Bad Case 挖掘
   先用 Skill 工具查看并加载与任务最匹配的一个；如果任务不属于任何 Skill 的适用范围，
   直接在结果中说明 status=error 与原因，不要硬套。
2. 严格按所加载 SKILL.md 的工作流程执行：
   - 取数只用 mcp__opik__* 系列工具，禁止绕过 MCP 直连 Opik；
   - 把工具返回的 JSON 原样写入 outputs/cache/ 下 SKILL.md 指定的路径；
   - 用 Bash 按 SKILL.md 的命令行签名运行对应 analyze.py；
   - 读取脚本输出的 JSON，按下方契约组装最终结果。
3. 最终回复必须是一个 JSON 对象，结构如下（所有字段必填）：
   {
     "task": "<用户原始任务>",
     "skill": "<命中的 skill 名称，如 version-diff>",
     "status": "success" | "no_data" | "error",
     "inputs": {<实际使用的入参，如实验名/阈值/维度>},
     "metrics": {<脚本输出的统计结果，原样引用>},
     "findings": [{"title": "...", "detail": "...", "evidence": {...}}, ...],
     "artifacts": ["<产物文件路径>", ...],
     "generated_at": "<ISO8601 时间戳>"
   }
4. 诚实性约束（最高优先级）：
   - 取数为空或无可配对数据时，status 置 no_data 并说明原因；
   - 工具或脚本失败时，status 置 error 并附错误摘要；
   - 禁止编造任何数字或结论，findings 必须来自脚本输出；可以对文字做润色。
5. 最后一步（务必依次执行）：
   a. 用 Write 工具把最终结果 JSON 写入 outputs/cache/final-result.json（直接覆盖旧内容）；
   b. 最终文本回复再输出同一个 JSON 对象本身，不要 markdown 代码块，不要任何额外文字。"""


def _extract_json(text: str) -> dict[str, Any]:
    """从 Agent 最终回复中提取 JSON 对象（容忍 markdown 围栏与前后缀文字）。"""
    stripped = text.strip()
    fence = re.search(r"```(?:json)?\s*(.*?)```", stripped, re.DOTALL)
    if fence:
        stripped = fence.group(1).strip()
    start, end = stripped.find("{"), stripped.rfind("}")
    if start < 0 or end <= start:
        raise ValueError(f"Agent 最终回复中不含 JSON 对象: {stripped[:200]!r}")
    return json.loads(stripped[start : end + 1])


def build_options() -> ClaudeAgentOptions:
    """组装 Agent 配置：项目级 Skills + Opik MCP + DeepSeek 接入。"""
    return ClaudeAgentOptions(
        cwd=str(config.ROOT),
        # 只加载项目级设置，确保 Skills 作用域限于本 PoC，不读用户全局配置
        setting_sources=["project"],
        system_prompt=SYSTEM_PROMPT,
        max_turns=config.MAX_TURNS,
        permission_mode="bypassPermissions",
        allowed_tools=config.ALLOWED_TOOLS,
        mcp_servers={
            "opik": {
                "command": str(config.VENV_PYTHON),
                "args": [str(config.MCP_SERVER_ENTRY)],
            }
        },
        env=config.anthropic_env(),
    )


async def run_task(task: str) -> dict[str, Any]:
    """执行一个分析任务，返回通过契约校验的结构化结果。

    结果优先从 Agent 用 Write 写入的 final-result.json 读取（工具写入不经过模型
    文本序列化，可规避长 JSON 的语法破损），文本解析仅作回退。
    """
    options = build_options()
    final_result_path = config.CACHE_DIR / "final-result.json"
    if final_result_path.exists():
        final_result_path.unlink()  # 清掉上一次任务的残留

    final_text: str | None = None
    error_texts: list[str] = []

    async for message in query(prompt=task, options=options):
        if isinstance(message, ResultMessage):
            if message.is_error:
                error_texts.append(message.result or "(无错误详情)")
            if message.result:
                final_text = message.result

    if final_result_path.exists():
        try:
            payload = json.loads(final_result_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"Agent 写入的结果文件不可解析: {exc}") from exc
    elif final_text is not None:
        payload = _extract_json(final_text)
    else:
        detail = "; ".join(error_texts) or "未产生任何结果消息"
        raise RuntimeError(f"Agent 未返回结果: {detail}")

    payload.setdefault("task", task)
    return validate_result(payload)
