"""Opik 适配层：把自托管 Opik 的数据映射为运行时 MCP 契约。

对外只暴露 list_experiments / get_traces / get_scores 三个工具，
供 app/tools/export_data.py 与 app/executor.py 的发现工具使用。
"""
