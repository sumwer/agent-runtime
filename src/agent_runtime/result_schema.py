"""结构化结果契约定义与校验。"""
from __future__ import annotations

from typing import Any

REQUIRED_FIELDS = ("task", "skill", "status", "inputs", "metrics", "findings", "artifacts", "generated_at")
ALLOWED_STATUS = ("success", "no_data", "error")


class ResultSchemaError(ValueError):
    """结果不符合契约。"""


def validate_result(payload: Any) -> dict[str, Any]:
    """校验结果契约；通过则原样返回，否则抛 ResultSchemaError。"""
    if not isinstance(payload, dict):
        raise ResultSchemaError(f"结果必须是 JSON 对象，实际为 {type(payload).__name__}")

    missing = [field for field in REQUIRED_FIELDS if field not in payload]
    if missing:
        raise ResultSchemaError(f"结果缺少必填字段: {missing}")

    if payload["status"] not in ALLOWED_STATUS:
        raise ResultSchemaError(f"status 必须是 {ALLOWED_STATUS} 之一，实际为 {payload['status']!r}")

    if not isinstance(payload["skill"], str) or not payload["skill"]:
        raise ResultSchemaError("skill 必须是非空字符串")

    for field in ("inputs", "metrics"):
        if not isinstance(payload[field], dict):
            raise ResultSchemaError(f"{field} 必须是对象")

    findings = payload["findings"]
    if not isinstance(findings, list):
        raise ResultSchemaError("findings 必须是数组")
    for i, finding in enumerate(findings):
        if not isinstance(finding, dict) or not {"title", "detail"}.issubset(finding):
            raise ResultSchemaError(f"findings[{i}] 必须是含 title/detail 的对象")

    if not isinstance(payload["artifacts"], list):
        raise ResultSchemaError("artifacts 必须是字符串数组")

    if payload["status"] == "success" and not findings:
        raise ResultSchemaError("status=success 时 findings 不能为空（至少给出一条结论）")

    return payload
