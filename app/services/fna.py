"""FNA 五档二分类任务的共享常量与备注解析。"""

from __future__ import annotations

import json
from typing import Any

FNA_TASK_CODE = "fna_binary_5class"
FNA_TASK_NAME = "甲状腺FNA二分类五档判断"

ANSWER_CERTAIN_BENIGN = "确定不是癌"
ANSWER_LIKELY_BENIGN = "倾向不是癌"
ANSWER_UNCERTAIN = "不确定"
ANSWER_LIKELY_MALIGNANT = "倾向是癌"
ANSWER_CERTAIN_MALIGNANT = "确定是癌"

FNA_ANSWER_OPTIONS = [
    ANSWER_CERTAIN_BENIGN,
    ANSWER_LIKELY_BENIGN,
    ANSWER_UNCERTAIN,
    ANSWER_LIKELY_MALIGNANT,
    ANSWER_CERTAIN_MALIGNANT,
]

FNA_GROUND_TRUTH_BY_LABEL = {
    "0": ANSWER_CERTAIN_BENIGN,
    "1": ANSWER_CERTAIN_MALIGNANT,
}

TRUTH_BINARY_BY_GROUND_TRUTH = {
    ANSWER_CERTAIN_BENIGN: 0,
    ANSWER_CERTAIN_MALIGNANT: 1,
}

MALIGNANCY_SCORE_BY_ANSWER = {
    ANSWER_CERTAIN_BENIGN: 1,
    ANSWER_LIKELY_BENIGN: 2,
    ANSWER_UNCERTAIN: 3,
    ANSWER_LIKELY_MALIGNANT: 4,
    ANSWER_CERTAIN_MALIGNANT: 5,
}


def build_source_note(source_center: str, source_file_path: str) -> str:
    """把来源信息写成结构化 JSON，便于导出时解析。"""
    return json.dumps(
        {
            "source_center": source_center,
            "source_file_path": source_file_path.replace("\\", "/"),
        },
        ensure_ascii=False,
        separators=(",", ":"),
    )


def parse_source_note(note: str | None) -> tuple[str, str]:
    """从题目备注中解析来源中心和原始路径；非 FNA 备注返回空字段。"""
    if not note:
        return "", ""
    try:
        data: Any = json.loads(note)
    except (TypeError, ValueError):
        return "", ""
    if not isinstance(data, dict):
        return "", ""
    return str(data.get("source_center") or ""), str(data.get("source_file_path") or "")
