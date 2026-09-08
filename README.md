# Agent Runtime PoC —— 云侧评测分析智能体

基于 Claude Agent SDK 的云侧 Agent Runtime 原型：接收自然语言分析任务，自动发现并加载
项目级分析 Skill，通过 MCP 从本地自托管 Opik 拉取评测数据（Experiment / Trace / Score /
Report），在本地运行环境执行 Python 分析，输出符合契约的结构化结果。

## 架构

```
run_task.py (CLI) ──> Agent Runtime (Claude Agent SDK)
                        ├── Skills 自动发现:  .claude/skills/*/SKILL.md
                        ├── MCP stdio:       mcp_server/opik_mcp.py
                        │                      └── opik SDK/REST ──> 自托管 Opik :5173
                        └── Bash 执行:        .claude/skills/*/analyze.py (本地子进程)
结果: outputs/results/*.json (契约化) + outputs/*.csv (明细制品)
```

三层职责，可独立替换：**取数收敛到 MCP**（换数据源只改 `mcp_server/`）、**分析外置到
Skill**（加能力只加目录）、**编排交给 SDK**（换沙箱只改执行层）。

## 环境要求

- Python 3.12（本仓库自带 `.venv`：claude-agent-sdk / mcp 2.x / opik / python-dotenv）
- 本地自托管 Opik 运行中（`opik-local/docker-compose.yaml --profile opik`）
- DeepSeek API key（通过其 **Anthropic 兼容端点** 接入 Claude Agent SDK，
  见 https://api-docs.deepseek.com/zh-cn/guides/anthropic_api/ ）

## 快速开始

```bash
cd /home/sumwer/myprogram/agent-runtime

# 1. 配置接入：复制 .env.example 为 .env，填入 DeepSeek key
cp .env.example .env
#   ANTHROPIC_AUTH_TOKEN=sk-xxxx
#   ANTHROPIC_API_KEY=sk-xxxx   （两处都填，兼容不同版本 SDK 的取值优先级）

# 2.（可选）重建评测数据：dataset + baseline/v2 两个实验 + 自定义报告
.venv/bin/python scripts/seed_opik_data.py

# 3. 离线自检 MCP 取数（不需要 key）
.venv/bin/python -m pytest tests/test_mcp_server.py -v

# 4. 提交分析任务（端到端）
.venv/bin/python scripts/run_task.py "分析 baseline 实验的指标分布"
.venv/bin/python scripts/run_task.py "对比 baseline 和 v2-safety-tuned 两个版本的差异，找出回退项"
.venv/bin/python scripts/run_task.py "挖一下 baseline 实验的 bad case，阈值 0.4"
```

结果落盘于 `outputs/results/<时间戳>.json`，结构：

```json
{
  "task": "…", "skill": "version-diff", "status": "success",
  "inputs": {…}, "metrics": {…},
  "findings": [{"title": "…", "detail": "…", "evidence": {…}}],
  "artifacts": ["outputs/version-diff-details.csv"],
  "generated_at": "…"
}
```

## 目录说明

| 路径 | 说明 |
| --- | --- |
| `src/agent_runtime/runtime.py` | 编排入口：组装 ClaudeAgentOptions（Skills / MCP / 权限 / DeepSeek env），驱动任务，提取并校验结果 |
| `src/agent_runtime/config.py` | 集中配置与 `.env` 加载 |
| `src/agent_runtime/result_schema.py` | 结果契约校验（字段完整性 / status 枚举 / findings 非空约束） |
| `mcp_server/opik_mcp.py` | MCP Server（stdio），只做取数；纯逻辑函数与工具分离便于单测 |
| `.claude/skills/metric-distribution/` | 单实验得分分布（总体 + 分类 + 年龄段） |
| `.claude/skills/version-diff/` | 两实验配对差异（TopN 提升/回退 + 分类级回退 + 明细 CSV） |
| `.claude/skills/badcase-mining/` | 低分样本挖掘（阈值筛选 + 明细 CSV） |
| `scripts/seed_opik_data.py` | 造数：30 条 dataset、baseline/v2 两实验、三指标评分、报告 JSON（幂等可重跑） |
| `scripts/run_task.py` | CLI 入口，原子写结果 |
| `data/reports/` | 自定义 Report JSON（Opik 无原生 Report 概念） |

## 设计要点

- **两段式取数**：MCP 拉数据落 `outputs/cache/*.json` → analyze.py 纯数据处理。Skill 脚本
  只用标准库，不依赖 opik SDK，便于单测与跨数据源复用。
- **诚实性约束**：MCP 取数失败抛明确错误；取数为空返回 `status=no_data`；system prompt
  明令禁止编造数字，`findings` 必须来自脚本输出。
- **Skill 作用域**：`setting_sources=["project"]`，只加载本目录 `.claude/skills/`，不污染
  用户全局 `~/.claude`。
- **数据叙事**：seed 数据刻意构造「v2 整体提升 + substance_use 单项回退 + baseline 含
  4 个 bad case」，保证三个 Skill 都有真实信号可发现。
- **模型接入**：DeepSeek 官方 Anthropic 兼容端点（`ANTHROPIC_BASE_URL=
  https://api.deepseek.com/anthropic`），Claude Agent SDK 原生可用，无需协议转换网关。

## 已验证（PoC 验收口径）

- [x] MCP 取数：7/7 冒烟测试（实验清单/条目/评分/报告/trace/span，两版本分数差异断言）
- [x] 三个 analyze.py 用真实 Opik 数据跑通，信号符合设计
- [x] Runtime 配置组装（Skills 作用域 / MCP 挂载 / env 注入）
- [ ] 端到端三场景（依赖 DeepSeek key）

## 后续方向（超出 PoC 范围）

1. **服务化**：`run_task` 已模块化，套一层 FastAPI 即可变成 HTTP Runtime（提交任务 →
   返回结果 id）；结果契约可直接作为平台 API 的响应体。
2. **沙箱升级**：analyze.py 执行从本地子进程迁到 Docker（资源限额 + 网络隔离）。
3. **Skill 生命周期**：平台侧提供 Skill 注册/审核/版本管理，Runtime 按 manifest 拉取。
4. **结果回写**：把结构化结果作为 Opik Experiment 级注释或独立资源回传平台。
