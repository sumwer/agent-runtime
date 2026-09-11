# Smolagents 本地实测：2026-09-11

环境：Python 3.12、smolagents 1.26.0、openinference-instrumentation-smolagents 0.1.40、
OpenTelemetry 1.44.0；模型 DeepSeek `deepseek-chat`；已有本地 Opik Docker 实例。
实际时间约 12:53（Asia/Shanghai）。通过 Opik REST 读取已持久化 trace/span，未做 UI 截图验证。
项目名：`smolagents-observability-demo`，UI：http://localhost:5173 。

任务：工具返回合成销售数据 January=120、February=180，Agent 计算总额与环比。

| 场景 | 结果 | 耗时 | span 数 | 模型调用 Token 总数 |
|---|---|---:|---:|---:|
| normal | 总额 300，增长 50%；3 轮完成 | 4.226 秒 | 9 | 6833 |
| transient-failure | 首次工具失败后重试成功，但后续解析/导入错误导致耗尽 4 轮；返回未执行代码 | 7.750 秒 | 12 | 11675 |
| transient-failure-allow-json | 首次工具失败，重试后成功；2 轮完成 | 3.027 秒 | 8 | 4673 |

对应 trace ID：

- normal：`01a08ed0-4aa6-7483-90bd-71151fb30dab`
- transient-failure：`01a08ed0-75cc-76ca-8d9b-b950c4002bb5`
- transient-failure-allow-json：`01a08ed0-e068-7025-bd84-6715395ae739`

## 观测得到的证据与缺口

1. 根运行、Step、模型与工具 span 已形成父子链路。模型输入输出、用量、延迟能够读取。
2. 工具抛出的 RuntimeError 即便被 Agent 代码捕获，工具 span 仍保留异常；能够识别随后重试成功。
3. 失败任务额外发生字符串当字典索引、禁止导入 json 两个错误，Step span 都记录了异常。
   但根 trace 的 error_info 为空，进程也返回 0。只按根异常/进程退出码判定任务成功会漏报。
   需结合 RunResult.state、final_answer 调用及结果评测；本例尚未添加评分写回。
4. 当前本地 Opik 将工具归类为 general、Agent 根 span 归类为 llm。
   现有分析器若仅筛选 type=tool 会漏掉工具；仅按 type=llm 统计会混入 Agent 汇总。
5. 正常任务 trace usage.total=13666，但三个真实模型调用之和为 6833；Agent 根 span 也带
   6833，存在重复汇总。上表仅累加本例具有 model 字段的实际模型调用 span。
   失败任务根 span 无 usage，因此未发生同样的翻倍。不能用统一除二方式修复。
6. total_estimated_cost 为空，不能当作零成本，也没有从这些数据得到准确账单。
7. 本例没有创建 thread、dataset 或 experiment。现有 adapter 的项目级 get_spans 可读取，
   依赖 experiment_id 的 get_traces/get_scores 不能直接用于这些普通 trace。

第三次运行允许 JSON 解析后得到正确答案，但单次随机模型运行不足以证明这一修改总能提高成功率。
后续应固定任务集重复运行，并补充任务状态、工具分类、Token 去重和评分映射后再计算成功率/成本。

## 复核

运行 `python -m examples.smolagents_opik.observe` 从 Opik 重新读取项目中的 trace/span。
它打印最多最近 100 条 trace，以及每条最多 100 个 span；本次三条均未达到此上限。
删除 Opik 存储卷会丢失这些 trace；本报告保留本次实测数字和定位 ID。
