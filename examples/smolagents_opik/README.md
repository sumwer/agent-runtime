# Smolagents → OpenTelemetry → Opik

这是一个独立、可运行的可观测性示例：一次 `CodeAgent.run()` 创建一条 trace；模型调用、
Web 搜索及每轮 Agent 决策会作为关联 span 导出到 Opik。它不依赖本仓库的 FastAPI 服务或
`opik_adapter`，后者继续只负责读取已有 Opik 数据供分析。

实现遵循 [Opik 的 Smolagents 集成文档](https://www.comet.com/docs/opik/integrations/smolagents)
和 [Smolagents 的 OpenTelemetry 指南](https://huggingface.co/docs/smolagents/tutorials/inspect_runs)。

## 运行

在仓库根目录创建专用环境并安装示例依赖：

```bash
python3 -m venv .venv-smolagents-opik
.venv-smolagents-opik/bin/pip install -r examples/smolagents_opik/requirements.txt
```

复制模板到被 Git 忽略的本地文件后填入真实密钥。Opik Cloud 的 endpoint 和 headers 格式见模板；
自托管 Opik 则使用部署实例的 OTLP endpoint。`projectName` 应使用专门的项目，避免与生产 trace
混杂。

```bash
cp examples/smolagents_opik/opik.env.example .env.smolagents-opik
# 编辑 .env.smolagents-opik，填入真实 OPIK / OpenAI 凭据。
set -a; source .env.smolagents-opik; set +a
.venv-smolagents-opik/bin/python -m examples.smolagents_opik.run
```

也可以传入自定义任务：

```bash
.venv-smolagents-opik/bin/python -m examples.smolagents_opik.run 'Search for a current AI policy update and summarize it.'
```

## 在 Opik 中检查

筛选项目 `smolagents-observability-demo`，从一次根 trace 展开 span 树，重点检查：

- Agent 是否在 `max_steps=6` 内完成；
- LLM span 的延迟、token 用量、错误和成本；
- Web 工具调用是否失败、超时或被重复调用；
- 输入输出是否包含不应采集的敏感信息。

这是追踪示例，不会自动给结果判分。若要比较多组任务或模型，应在 Opik 中建立 dataset/
experiment 并添加质量、安全、工具成功率等 evaluator；本仓库的 `opik_adapter` 可再读取这些
trace、span 和评分做低分案例分析。
