"""Reproducible synthetic evaluation; does not measure real conversion or manual time saved."""
import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

from engine import VERSION, run_rules
from fixtures import CASES


def evaluate(split="holdout"):
    rows, correct_fields, supported, total_evidence = [], 0, 0, 0
    matrix = {p: {q: 0 for q in "ABCD"} for p in "ABCD"}
    total_ms = 0
    for case in CASES:
        if case["split"] != split:
            continue
        result = run_rules(case["text"])
        actual = {"priority": result["decision"]["priority"], **{k: result["profile"][k] for k in ("city", "budget_max", "timeline")}}
        comparisons = {k: actual[k] == value for k, value in case["expected"].items()}
        correct_fields += sum(comparisons.values())
        matrix[case["expected"]["priority"]][actual["priority"]] += 1
        for ev in result["profile"]["evidence"]:
            total_evidence += 1
            supported += int(case["text"][ev["start"]:ev["end"]] == ev["quote"])
        total_ms += result["elapsed_ms"]
        rows.append({"id": case["id"], "text": case["text"], "expected": case["expected"], "actual": actual, "checks": comparisons, "pass": all(comparisons.values())})
    count = len(rows)
    return {"at": datetime.now(timezone.utc).isoformat(), "version": VERSION, "mode": "rules", "split": split, "sample_count": count, "passed_cases": sum(x["pass"] for x in rows), "correct_fields": correct_fields, "total_fields": count * 4, "supported_evidence": supported, "total_evidence": total_evidence, "elapsed_ms": round(total_ms, 2), "confusion_matrix": matrix, "cases": rows, "limitations": ["小规模人工编写的合成案例；开发过程可能影响规则，不是外部盲测。", "仅评估分级、城市、预算上限、时间及引文定位；不能代表任意自然语言泛化。", "未调用真实模型；不代表LLM质量。", "未测量人工处理耗时、客户响应、到店或成交提升。"]}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--split", choices=["demo", "holdout"], default="holdout")
    args = parser.parse_args()
    report = evaluate(args.split)
    output = Path(__file__).parent / "output" / f"evaluation-{args.split}.json"
    output.parent.mkdir(exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"{report['passed_cases']}/{report['sample_count']} cases; {report['correct_fields']}/{report['total_fields']} fields; {output}")
    raise SystemExit(0 if report["passed_cases"] == report["sample_count"] else 1)
