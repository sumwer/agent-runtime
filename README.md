# 云侧 Agent Runtime PoC

以 [设计文档](docs/specs/2026-09-09-agent-runtime-poc-design.md) 和
[原始实施计划](docs/plans/2026-09-09-agent-runtime-poc.md) 为目标实现的分析服务。
FastAPI 接收任务，Postgres 队列由独立 Worker 抢占，LangGraph 按 Skill 方法论调度工具，
MCP 数据直接导出至任务工作目录，LLM 生成的 Python 在一次性 Docker 沙箱执行，
结构化结果存 Postgres、图表落盘。

## 启动

需要 Python 3.12+、Docker 和 Docker Compose。以下命令在仓库根目录运行。

```bash
python3 -m venv .venv-runtime
.venv-runtime/bin/pip install -r requirements.lock
docker compose up -d --wait postgres
bash sandbox/build.sh
```

下载缓慢时可为构建单独指定镜像源和网络（不改变执行沙箱禁网设置）：

```bash
SANDBOX_BUILD_NETWORK=host SANDBOX_PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple bash sandbox/build.sh
```

将 `.env.example` 的配置合并到 `.env`，已有文件不要覆盖密钥。
模型配置优先读取 `MODEL`，否则兼容旧 `ANTHROPIC_MODEL`（移除旧 SDK 的 `[1m]` 后缀）。
当前项目沿用现有 DeepSeek 端点与密钥；兼容端点用 `ANTHROPIC_BASE_URL`。
设计原文的 `claude-opus-5` 仅为未配置时的默认值，不代表供应商可用性已验证。

```bash
# 终端一：API
.venv-runtime/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000
# 终端二：默认 2 个并发任务
.venv-runtime/bin/python -m app.executor
# 终端三：提交并轮询，会调用已配置的模型
bash demo.sh
bash demo.sh '查看 exp-001 的分数分布并生成直方图'
```

Postgres 绑定本机 `55432`，使用独立 volume，避开已有 Opik 的数据库端口。
Compose 仅运行数据库；API 和 Worker 在宿主机，确保沙箱挂载路径一致。
首次初始化同时建立 `agent_runtime` 和 `agent_runtime_test`。
已有 volume 若缺测试库，可运行 `docker compose exec postgres createdb -U agent agent_runtime_test`。

## API

| 端点 | 行为 |
|---|---|
| POST /analyses | {task, experiment_id?, created_by?, params?} → 202 + analysis_id |
| GET /analyses?status=&limit= | 列表，limit 1–200 |
| GET /analyses/{id} | queued / running / succeeded / failed、结果与错误 |
| GET /analyses/{id}/events | 步骤、导出、MCP 重试和沙箱事件 |
| GET /analyses/{id}/artifacts/{path} | 受路径包含关系检查保护的文件下载 |
| GET /skills | Skill 注册表，每任务重新扫描 |

图表地址例如 `/analyses/<id>/artifacts/workspace/out/groups.png`，
结果副本 `/analyses/<id>/artifacts/result.json`。API 文档位于 `/docs`。
默认只监听回环地址且无鉴权；设 `API_TOKEN` 后所有端点要求
`Authorization: Bearer <token>`。created_by 仅作记录。

结果字段：skill_id、summary、findings[{title,detail,evidence?}]、
metrics（必含非负整数 sample_count，所有数值有限）、charts、caveats。
提交前检查 Skill 已加载、数据已导出、至少一次沙箱执行成功、图表实际存在。

## Skill 与数据源

- skills/badcase-analysis：低分分组、代表 trace、归因建议、柱状图。
- skills/score-distribution：分位数、低分占比、直方图。
- skills/agent-metrics：多轮决策整体指标（轮次与收敛、工具成功率与循环、延迟与 token 成本、异常会话）。
- skills/dataset-distribution：在评测前检查待测集的标签覆盖、长度、缺失、重复与潜在的类别偏斜。

每个 Skill 包含 SKILL.md 和 reference/*.py；运行时加载完整方法论和参考脚本，
模型按数据结构改写代码。新增 Skill 放入目录后，下一个任务即可发现。

数据源是真实的 Opik：自托管的 `opik-local`（REST 为 `http://localhost:5173/api`），
经适配层 `opik_adapter/` 以 MCP 对外提供。

### Smolagents 观测示例

`examples/smolagents_opik/` 是与生产运行时隔离的参考实现：Smolagents 通过
OpenTelemetry 将 agent、LLM 和工具调用的 trace/span 导出到 Opik。运行与检查方法见
[示例说明](examples/smolagents_opik/README.md)；它产生的数据可再由本项目的 `opik_adapter`
读取并交给分析 Skill。

先启动本地 Opik（独立 compose 工程，前端绑定 5173；后端与数据服务在 `opik` profile 下）：

```bash
cd ../opik-local && docker compose --profile opik up -d --no-build
```

再指向适配层（`MCP_STDIO_CMD` 为空时仍是内置 mock）：

```dotenv
MCP_TRANSPORT=stdio
MCP_STDIO_CMD=.venv-runtime/bin/python -m opik_adapter.server
```

适配层的 MCP 子进程以 `.env` 为底、进程环境优先：
`OPIK_API_BASE`、`OPIK_API_KEY`、`OPIK_WORKSPACE`、`OPIK_PROJECT_NAME`、
`OPIK_SCORE_NAME`（主评分类指标）、
`OPIK_TIMEOUT_SECONDS`、`OPIK_MAX_ITEMS`、`OPIK_MAX_EXPERIMENTS`。

主评分必须显式指定：反馈评分在不同条目里的顺序不固定，逐条取第一个会把多个指标混成一列。
未设置时取全实验出现次数最多的指标（同次数取字典序），仅为兜底；
配了但实验里没有该指标会直接报错而不是给出空列。
例如 minor-safety-qlora 的 `safety` / `age_fit` / `quality` 要写成 `OPIK_SCORE_NAME=safety`。

为什么不是官方 `opik-mcp`：它只有 read/list/write/schema 五个工具，
list/read 返回给人看的文本表格，且没有「实验条目」（trace × 评分）接口，
无法稳定映射成导出器需要的 `{items, total}`。
适配层直接调用 opik-mcp 自己使用的 `/v1/private` REST 端点，输出结构化分页数据；
官方 opik-mcp 仍可用于 IDE 侧人工排查（`uvx opik mcp configure`）。

导出器契约（`app/tools/export_data.py`）：list_experiments() 返回列表；
get_traces/get_scores(experiment_id,page,page_size) 返回 {items,total}，每页最多100条。
trace 至少含 id、数值 score；score 行含 trace_id、score。
可选 min_score/max_score 是闭区间过滤，由适配层在服务端过滤。
输出和扫描上限受 MAX_EXPORT_ROWS 控制，truncated 提示可能不完整。

字段映射：

| 工具 | Opik REST | 行字段 |
|---|---|---|
| list_experiments | GET /v1/private/experiments | id、name、dataset_id、dataset_name、trace_count、item_count、avg_score、scores、created_at |
| get_traces | GET /v1/private/datasets/{dataset_id}/items/experiments/items | id、trace_id、dataset_item_id、experiment_id、input、item_input、version、output、expected_output、metadata、score、score_name、scores、duration、created_at |
| get_scores | 同上 | trace_id、score、name |
| get_threads | GET /v1/private/traces/threads | id、number_of_messages、duration、status、usage、total_estimated_cost、scores、created_at |
| get_spans | GET /v1/private/spans | id、trace_id、parent_span_id、name、type（llm/tool）、model、provider、prompt/completion/total_tokens、duration、ttft、total_estimated_cost、error、start_time |
| list_datasets | GET /v1/private/datasets | id、name、item_count、experiment_count、version、tags、created_at |
| get_dataset_items | GET /v1/private/datasets/{id}/items?version=latest | id、input、expected_output、metadata、tags、source |

`traces`/`scores` 属于实验级，必须给 `experiment_id`，支持 min_score/max_score；
`threads`/`spans` 属于项目级（项目由 `OPIK_PROJECT_NAME` 决定），不接 experiment_id 与分数过滤。
`dataset_items` 属于待测数据集级，必须给 `dataset_id`，不接分数过滤；它可以在创建 experiment
之前读取。`export_data` 因此允许 `experiment_id` 省略：`export_data(source="threads")`，
或 `export_data(source="dataset_items", dataset_id="...")`。

### 评测前数据集审查

提交分析任务时，在 task 中给出 Opik dataset 的 id 或名称，并要求使用 `dataset-distribution`。
Agent 会先读取少量样本确认字段，再把全量 dataset items 写入任务工作目录，交由 Docker 沙箱
分析；原始题目和参考答案不会整体放进模型上下文。例如：

```text
使用 dataset-distribution Skill 审查 Opik 数据集 <dataset-id>，判断它是否适合评估
未成年人安全回答 Agent。检查类别与年龄段覆盖、题目重复、参考答案缺失及潜在评测偏差。
```

本地 Opik 的当前版本读取数据项需传 `version=latest`，适配层已处理该差异。若数据超过
`MAX_EXPORT_ROWS`，结果会标记截断，Skill 不能据此作全量结论。

experiment_id 可按 id 或名称解析；只支持有关联数据集的实验（需要 dataset_id）。
适配层按实验缓存条目（上限 OPIK_MAX_ITEMS）后切片分页，page 从 1 开始，page_size ≤ 100。
无分页的源一律明确报错，未实现未经确认的 REST 回退。

条目字段说明：`input` 是原始包裹结构 `{"item": {...}, "version": ...}`，
`item_input` 是其中的问题文本（数据集条目的 input）；`output` 在 Opik 里只是 trace 引用
（`{"output": "<trace_id>"}`），所以分析按评分 + `metadata`（category / age_band 等维度）
进行，要看模型正文需要另取 trace，适配层目前不提供。

离线开发用内置 mock：`MCP_TRANSPORT=stdio` 且 `MCP_STDIO_CMD` 为空即启动 `mock_mcp/`；
exp-001 有200条确定性样本，其中75条低分（30 timeout / 25 wrong_format / 20 refusal）。

多轮 agent 指标（threads/spans）在没有真实多轮数据时可指向本地 Opik 桩，
它提供 4 个会话 / 23 个 span（含 1 次工具超时与 1 处连续重复调用）：

```bash
.venv-runtime/bin/python scripts/dev_opik_stub.py --port 8770   # 前台，另开终端
OPIK_API_BASE=http://127.0.0.1:8770/api OPIK_PROJECT_NAME=agent-metrics-demo OPIK_SCORE_NAME= \
  .venv-runtime/bin/python -m app.executor
```

旧 mcp_server/opik_mcp.py 使用不同工具签名和 MCP 2.x，保留作真实平台适配参考，
不能直接替换此接口。字段与分页映射仍须按设计 §8 对齐。

## 执行边界

每任务独立 artifacts/<uuid>/workspace。MCP 发现最多返回20个实验/3条样例；
批量数据以 JSONL 直接写文件，沙箱 stdout/stderr 各保留末尾8000字节。
Docker 禁网、1CPU、1GiB内存（禁额外 swap）、128 PID、只读根文件系统、无 capabilities，
以宿主机用户运行。镜像预装锁版本科学计算包并移除 pip。
产物按保留期清理（默认只删文件，加 `--prune-db` 连带删除已终止的旧任务行）：

```bash
.venv-runtime/bin/python scripts/cleanup_artifacts.py --days 14          # 先 --dry-run 看影响
```

可挂 systemd timer 每日执行。磁盘配额仍由部署环境管理，PoC 未实现。

脚本最多120秒，连续失败最多初次+3次修复；整个任务默认600秒，包含 Agent 初始化。
超时/取消会移除具名容器，保留部分产物。MCP 每次请求最多2次重试。
submit_result 失败允许修正一次，通过立即终止图执行。
Worker 每10秒心跳，失联90秒任务标失败，不自动重放任务。
WORKER_CONCURRENCY 控制每进程槽位数，多进程总并发为槽位数之和。

## 验证

```bash
# 真实 Postgres + MCP stdio + Docker + 脚本化模型运行生产 LangGraph
.venv-runtime/bin/python -m pytest -q
# 显式启用真实模型调用
RUN_LLM_E2E=1 .venv-runtime/bin/python -m pytest tests/test_pipeline.py -m e2e -v
```

无数据库或沙箱镜像时相关集成测试 skip，真实模型测试默认 skip。
tests/test_opik_adapter.py 用内置 Opik REST 桩验证字段映射、分页与导出链路，
不需要真实 Opik。真实联调（Opik 已启动并配好 OPIK_PROJECT_NAME）：

```bash
OPIK_API_BASE=http://localhost:5173/api OPIK_PROJECT_NAME=minor-safety-qlora \
OPIK_SCORE_NAME=safety RUN_REAL_OPIK=1 .venv-runtime/bin/python -m pytest -q
```
数据库测试仅允许库名以 _test 结尾，测试会清理该库中的任务表。
旧 Opik 测试不在默认收集中，使用旧 .venv、运行中的 Opik 及 RUN_LEGACY_OPIK=1 单独运行。
新环境只安装新服务依赖。

## Ubuntu VM

代码放 /opt/agent-runtime，建立专用 agent-runtime 用户并给予 Docker 使用权限。
执行安装、数据库启动和镜像构建，确保该用户可写 artifacts。
配置 /opt/agent-runtime/.env（权限600），编辑 deploy/*.service 的用户名和路径。
unit 用 `EnvironmentFile=` 读同一份 .env，Opik 凭据（OPIK_*）与 `API_TOKEN` 都写在那里。
数据源是独立的 Opik compose 工程，不在本 unit 内；启动顺序为先 Opik、再 API 与 Worker。
将 unit 安装到 /etc/systemd/system/ 后运行：

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now agent-runtime-api agent-runtime-worker@1
journalctl -u agent-runtime-worker@1 -f
```

默认 @1 已有2个并发槽位，增加实例前计算总资源。数据库应先启动。

## 工程调整与旧原型

- 用 LangGraph StateGraph 显式构造 ReAct 循环，避开已弃用的 create_react_agent，
  严格实现顺序调用、重试上限和提交终止。
  迁移背景见 [LangGraph v1 官方说明](https://docs.langchain.com/oss/python/releases/langgraph-v1)。
- MCP 用 langchain-mcp-adapters 会话接口，避免跨 asyncio 任务管理 AnyIO 取消作用域。
- 导出增加 scanned/truncated；补充有界本地过滤、心跳恢复、UUID/数值校验、
  符号链接防护、流式日志限长和容器取消清理。
- 沙箱失败预算按连续失败序列计算，改变脚本仍消耗同一预算，成功后重置。
- 未默认启用供应商特有的 adaptive thinking；模型配置统一在 app/llm.py。
- 原始计划原文保留，落地状态见 [实施记录](docs/implementation-status.md)。

旧 src/agent_runtime、.claude/skills、scripts/run_task.py 和历史 outputs 保留；
新服务入口为 app.main / app.executor。
