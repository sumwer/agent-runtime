# 实施记录

目标来源：docs.rar 中的 2026-09-09 设计和实施计划，原文保存在 specs/ 与 plans/。
实施日期：2026-09-10。旧 CLI 源码、分析脚本与私有 .env 保留。

| 原计划任务 | 落地位置 |
|---|---|
| 1 基础设施 | docker-compose.yml、db/、app/config.py、app/db.py |
| 2 队列 | app/queue.py：SKIP LOCKED、状态、事件、心跳失联处理 |
| 3 输出契约 | app/schemas.py：sample_count、有限数值、图表路径 |
| 4 Skill 加载 | app/skills_loader.py：摘要扫描、完整方法论和参考脚本 |
| 5 沙箱镜像 | sandbox/Dockerfile、sandbox/build.sh |
| 6 执行工具 | app/tools/sandbox.py：限资源、流式日志、取消清理、失败预算 |
| 7 Mock MCP | mock_mcp/：stdio 与 HTTP、确定性分页数据 |
| 7b Opik 适配 | opik_adapter/：Opik REST → 运行时 MCP 契约（list_experiments/get_traces/get_scores） |
| 8 数据导出 | app/tools/export_data.py：有界分页、过滤、JSONL、截断提示 |
| 9 Prompt/模型 | app/prompts.py、app/llm.py：沿用现有 DeepSeek |
| 10 Worker/Agent | app/executor.py：LangGraph ReAct、并发槽位、任务超时、提交终止 |
| 11 REST | app/main.py：提交、查询、产物、Skill、事件 |
| 12 内置 Skill | skills/badcase-analysis、skills/score-distribution |
| 13 验收与部署 | tests/、demo.sh、README.md、deploy/*.service |

## 工程差异

1. Compose 仅运行 Postgres（原计划已确认的决定），主机端口改为55432避免冲突。
2. 使用独立 .venv-runtime 与 requirements.lock，不破坏旧 MCP 2.x/Claude Agent SDK 环境。
3. LangGraph 用显式 StateGraph ReAct 替代已弃用的预置 create_react_agent；
   模型仍通过 langchain-anthropic 接入，仅 app/llm.py 绑定供应商。
4. 配置 MODEL 优先，否则兼容原 ANTHROPIC_MODEL；现有选择为 deepseek-chat。
5. 使用受限 MCP 发现工具和导出器，避免把可无限分页取数的工具直接暴露给模型。
6. 重试、输出校验和提交终止由代码执行；沙箱预算按连续失败序列计算。
7. MCP 无过滤时在宿主机过滤；无分页时明确失败。
8. 数据源接真实 Opik 走 opik_adapter/ 而非官方 opik-mcp：后者只有 read/list/write/schema，
   输出为文本表格且无实验条目接口，无法映射成 {items,total}；适配层复用它自己调用的
   /v1/private REST 端点。stdio 子进程显式传 env（.env 为底、进程环境优先），
   否则 MCP SDK 只给最小环境，拿不到 OPIK_* 凭据。
9. 增加 heartbeat_at 与事件查询；失联任务标失败，避免无限 running。
10. 不默认启用 adaptive thinking，以兼容当前 DeepSeek 接入。

## 验证状态

- 默认全量测试：42 passed、2 skipped（显式启用的真实模型 pytest 与 RUN_REAL_OPIK 联调），
  1 个第三方弃用警告。其中 11 个来自 tests/test_opik_adapter.py：字段映射、分页边界、
  主评分一致性、stdio 工具契约，以及用内置 Opik REST 桩跑通 export_data 的端到端导出。
- 真实 Opik 联调（2026-09-10，本机 opik-local + `--profile opik up -d --no-build`）：
  项目 minor-safety-qlora、实验 baseline / v2-safety-tuned（各 30 条，指标 safety/age_fit/quality），
  list_experiments 与 get_traces/get_scores 均取到数据，export_data 写出 30 行 traces 与 30 行 scores。
- 联调发现并修复：反馈评分在不同条目里的顺序不固定，逐条取第一个会把多个指标混进一列
  （修复：按实验取出现最多的指标，或强制 OPIK_SCORE_NAME，缺失即报错）；
  实验条目的 output 只是 trace 引用，故新增 item_input 铺平数据集输入。
- 测试使用真实 Postgres、真实 MCP stdio/HTTP、真实 Docker 和生产 LangGraph。
  验证 SKIP LOCKED 并发抢占、路径/符号链接防护、数值校验、重试上限、
  初始化超时、提交立即终止、沙箱禁网/CPU/PID/内存限制、超时/取消后容器清理。
- requirements.lock 安装完成，pip check 无依赖冲突；脚本语法与 git diff --check 通过。
- 手动真实模型验收：沿用现有 DeepSeek deepseek-chat，经实际 HTTP API 并发提交两个任务，
  由常驻 Worker 处理，使用 mock MCP 数据；两个任务均 succeeded，PNG 下载验证通过。

| 场景 | 任务 ID | 样本量 | 图表 | 执行耗时 |
|---|---|---|---|---|
| Bad Case | 6aa30176-aefc-41aa-9172-aaea26cfa316 | 75 | out/groups.png | 15.3 秒 |
| 分数分布 | ee913f90-433a-4986-a3a7-5e64eb14eceb | 200 | out/hist.png | 30.2 秒 |

### 真实数据端到端（2026-09-10）

| 场景 | 任务 ID | 数据源 | 样本 | 图表 | 耗时 |
|---|---|---|---|---|---|
| Bad Case（真实 Opik） | c9efedb2-39a1-4215-aff1-c51b66aacd57 | minor-safety-qlora / v2-safety-tuned | 30（≤0.5 共 5） | out/groups.png、out/category_scores.png | 102 秒 |
| 分数分布（真实 Opik） | 836f1cbe-09de-4414-8292-b35566330207 | 同上 | 30 | out/hist.png、out/hist_by_category.png | 75 秒 |
| Agent 多轮指标 | d341f686-7866-426b-8671-0dfb39d81fee | 本地 Opik 桩（agent-metrics-demo） | 4 会话 / 23 span | out/agent_metrics.png | 约 120 秒 |

Agent 多轮指标（skill=agent-metrics，经 API 提交，真实模型 + 真实沙箱）：
turn_mean 5.75 / turn_median 5.5 / turn_p90 8.1、finished_ratio 0.75、tool_success_rate 92.86%（14 次调用 1 次超时）、
error_rate 4.35%、latency_p50 0.7 / p95 1.435、tokens_total 1795、cost_total 0.092、
loop_suspect_count 1（tr-3 连续 3 次 search，对应该会话未完成且 task_success 0.25）、abnormal_session_count 1；
图表 out/agent_metrics.png 可下载（35.5KB）。数值与桩数据构造真值一致。
真实 Opik 三个项目的 threads 均为 0、span 只有单轮 eval_inference，故用桩数据验收；
接入真实 agent 的多轮 trace 后可直接复用同一 skill。

- 真实 Opik（`opik-local --profile opik`）+ 真实模型 + 真实沙箱，API/Worker 常驻提交，status=succeeded，
  两张图均可下载（27.9KB / 27.0KB）。Opik 的 python-backend 已改到 8002，8000 留给本服务 API。
- 结论按 `metadata.category` 分组：substance_use 4/5 低分且 safety/age_fit/quality 三因子同时偏低，
  cyberbullying 1 例为 safety 单维度瓶颈；caveats 如实写明「output 只是 trace 引用、样本量小、不作因果推断」。
- 期间修掉一个真 bug：`GET /analyses` 不带 status 时 psycopg 无法推断 NULL 参数类型导致 500
  （改为按条件拼 WHERE），已补回归测试。

运行产物保存在 artifacts/<任务ID>/，不进入 Git。
验收期间 API 在 127.0.0.1:8000、Worker 在宿主机运行；Postgres 在55432。
本次未将 systemd 示例安装为系统服务，终端进程不代表已完成 VM 常驻部署。

## 仍需外部对齐

字段映射已在 opik_adapter/ 落地并与本机自托管 Opik 联调通过（设计 §8 的传输/分页/字段已对齐）。
仍待确认：平台侧真实实例的鉴权方式（API key / 工作区）与版本差异——
当前验证对象是 opik-local 的 latest；跨版本时 /v1/private 的字段可能变化。
旧 mcp_server/opik_mcp.py 与新规范签名不同，不能直接切换而不做映射。
默认 mock 支持独立开发和演示。
补齐项（2026-09-10）：`API_TOKEN` 可选鉴权（未设置时保持开放）、
`scripts/cleanup_artifacts.py` 按保留期清理产物（可 `--prune-db`）、
提示注入纪律测试（断言安全纪律原文 + 注入文本只作为数据原样落盘）。
仍非生产多租户服务：无磁盘配额、无用户体系、`API_TOKEN` 是单一共享令牌、
未做对抗性红队测试、systemd unit 未实际安装（需 sudo）。
