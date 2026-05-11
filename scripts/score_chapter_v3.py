#!/usr/bin/env python3
"""
score_chapter_v3.py — 教材正文 README.md 评分器 v3

A 组（结构铁律，本地 regex）：
- D1 Beat 1-7 结构完整
- D2 Lena 版本推进明示
- D3 代码 + 预期输出（至少一对）
- D4 禁词禁格式

B 组（内容质量，LLM 判官 JSON 注入）：同 podcast v3
- D5 术语讲清率
- D6 事实准确
- D7 逻辑连贯
- D8 信息密度
- D9 可复述性

用法：
    python3 scripts/score_chapter_v3.py --chapter ch14-execution-safety
    python3 scripts/score_chapter_v3.py --chapter ch14 --judges /tmp/ch14-judges.json
"""

import argparse
import json
import math
import re
import sys
from pathlib import Path

CHAPTERS_BASE = Path(__file__).parent.parent / "book" / "chapters"

STRUCT_WEIGHTS = {
    "D1_beat_structure": 0.05,
    "D2_lena_version":   0.05,
    "D3_code_validity":  0.05,
    "D4_no_banned":      0.05,
}
QUALITY_WEIGHTS = {
    "D5_term_clarity": 0.15,
    "D6_factual":      0.25,
    "D7_coherence":    0.15,
    "D8_info_density": 0.15,
    "D9_recall":       0.10,
}
ALL_WEIGHTS = {**STRUCT_WEIGHTS, **QUALITY_WEIGHTS}
assert abs(sum(ALL_WEIGHTS.values()) - 1.0) < 0.001

PASS_GATES = {
    "total_score":  9.1,
    "struct_each": 10.0,
    "quality_each": 7.5,
    "factual_min":  8.5,
}


# ─── A 组 ─────────────────────────────────────────────────────────────

REQUIRED_BEATS = ["Beat 1", "Beat 2", "Beat 3", "Beat 4", "Beat 5", "Beat 6", "Beat 7"]


def score_D1_beat_structure(readme: str) -> tuple[float, str]:
    found = []
    for b in REQUIRED_BEATS:
        if re.search(rf'^##\s+{b}\b', readme, re.M):
            found.append(b)
    coverage = len(found) / len(REQUIRED_BEATS)
    if coverage == 1.0:
        score = 10.0
    elif coverage >= 0.85:
        score = 8.0
    elif coverage >= 0.70:
        score = 5.0
    else:
        score = 0.0
    missing = [b for b in REQUIRED_BEATS if b not in found]
    return score, f"覆盖 {len(found)}/7 Beat；缺失：{missing}"


def score_D2_lena_version(readme: str) -> tuple[float, str]:
    patterns = [
        r'v\d+\.\d+\s*[→to]+\s*v\d+\.\d+',
        r'v\d+\.\d+\s*升到\s*v\d+\.\d+',
        r'从\s*v\d+\.\d+\s*.*?到\s*v\d+\.\d+',
        r'Lena\s*v\d+\.\d+',
    ]
    hits = [p for p in patterns if re.search(p, readme)]
    if not hits:
        return 0.0, "未见 Lena 版本号（v0.X → v0.Y）"
    return 10.0, f"版本号找到 {len(hits)} 处匹配"


def score_D3_code_validity(readme: str) -> tuple[float, str]:
    py_blocks = re.findall(r'```python\n(.*?)```', readme, re.S)
    any_blocks = re.findall(r'```\w*\n(.*?)```', readme, re.S)
    if not py_blocks:
        return 3.0, f"无 ```python 代码块（找到 {len(any_blocks)} 个其他语言块）"
    # 至少一段含 def/class 的代码
    has_def = any(re.search(r'\b(def|class)\s+\w+', b) for b in py_blocks)
    if not has_def:
        return 5.0, f"{len(py_blocks)} 个 python 块但无函数/类定义"
    return 10.0, f"{len(py_blocks)} 段 python 代码（含 def/class）"


BANNED_PATTERNS = [
    (r'\bAbel\b', "Abel 人名"),
    (r'/Users/|~/code/|~/\.claude/', "本机路径"),
    (r'\bR[1-9][0-9]?-[A-Z]\b', "R 代号 RX-Y"),
    (r'（来源：R\d', "R 系列内部代号"),
    (r'docs/research/R\d', "内部研究文件路径"),
    (r'本章 arc', "本章 arc（应为 本章脉络）"),
    (r'##\s*revision-log', "修订日志 (内部 QA)"),
    (r'质量自检（\d+项?）', "内部 QA 清单"),
    (r"Let's\s+[一-鿿]|[一-鿿].*?\bLet's", "Let's + 中文"),
]


def score_D4_no_banned(readme: str) -> tuple[float, str]:
    hits = []
    for pat, name in BANNED_PATTERNS:
        if re.search(pat, readme):
            hits.append(name)
    if not hits:
        return 10.0, "无禁词"
    return 0.0, f"触发 {len(hits)} 类禁词：{hits}"


# ─── Veto ─────────────────────────────────────────────────────────────

def check_vetoes(readme: str) -> list[tuple[str, str]]:
    vetoes = []
    if re.search(r'\bAbel\b', readme):
        vetoes.append(("V3", "Abel 人名"))
    if re.search(r'/Users/|~/code/|~/\.claude/', readme):
        vetoes.append(("V4", "本机路径"))
    if re.search(r'\bR[1-9][0-9]?-[A-Z]\b|（来源：R\d', readme):
        vetoes.append(("V8", "R 内部代号/引用"))
    # V5: Beat 1-3 全缺
    b_found = sum(1 for b in ["Beat 1", "Beat 2", "Beat 3"]
                  if re.search(rf'^##\s+{b}\b', readme, re.M))
    if b_found == 0:
        vetoes.append(("V5", "Beat 1-3 全部缺席"))
    return vetoes


# ─── B 组注入 ─────────────────────────────────────────────────────────

def load_judges(p: Path | None) -> dict:
    if not p or not p.exists():
        return {k: {"score": 0.0, "detail": "MISSING"} for k in QUALITY_WEIGHTS}
    data = json.loads(p.read_text(encoding="utf-8"))
    return {k: {"score": float((data.get(k) or {}).get("score", 0)),
                "detail": (data.get(k) or {}).get("detail", "")}
            for k in QUALITY_WEIGHTS}


# ─── 综合 ─────────────────────────────────────────────────────────────

def compute_weighted(scores):
    return sum(scores[k] * ALL_WEIGHTS[k] for k in ALL_WEIGHTS)


def compute_penalized(scores):
    w = compute_weighted(scores)
    m = min(scores.values())
    penalty = 0.15 * (10 - m) ** 2 / 10
    return max(0, w - penalty), penalty


def check_pass(scores, vetoes):
    reasons = []
    if vetoes:
        reasons.append(f"触发 {len(vetoes)} 个 veto")
        return False, reasons
    total, _ = compute_penalized(scores)
    if total < PASS_GATES["total_score"]:
        reasons.append(f"总分 {total:.2f} < {PASS_GATES['total_score']}")
    for k in STRUCT_WEIGHTS:
        if scores[k] < PASS_GATES["struct_each"]:
            reasons.append(f"{k}={scores[k]} < 10（结构铁律）")
    for k in QUALITY_WEIGHTS:
        if scores[k] < PASS_GATES["quality_each"]:
            reasons.append(f"{k}={scores[k]} < 7.5（内容短板）")
    if scores.get("D6_factual", 0) < PASS_GATES["factual_min"]:
        reasons.append(f"D6_factual={scores['D6_factual']} < 8.5（事实门槛）")
    return len(reasons) == 0, reasons


def score_chapter(name, judges_path):
    chdir = CHAPTERS_BASE / name
    if not chdir.exists():
        matches = [d for d in CHAPTERS_BASE.iterdir()
                   if d.is_dir() and d.name.startswith(name)]
        if not matches:
            raise FileNotFoundError(name)
        chdir = sorted(matches)[0]
    readme = (chdir / "README.md").read_text(encoding="utf-8")
    vetoes = check_vetoes(readme)
    d1, d1d = score_D1_beat_structure(readme)
    d2, d2d = score_D2_lena_version(readme)
    d3, d3d = score_D3_code_validity(readme)
    d4, d4d = score_D4_no_banned(readme)
    judges = load_judges(judges_path)
    scores = {
        "D1_beat_structure": d1, "D2_lena_version": d2,
        "D3_code_validity":  d3, "D4_no_banned":    d4,
        "D5_term_clarity": judges["D5_term_clarity"]["score"],
        "D6_factual":      judges["D6_factual"]["score"],
        "D7_coherence":    judges["D7_coherence"]["score"],
        "D8_info_density": judges["D8_info_density"]["score"],
        "D9_recall":       judges["D9_recall"]["score"],
    }
    details = {
        "D1_beat_structure": d1d, "D2_lena_version": d2d,
        "D3_code_validity":  d3d, "D4_no_banned":    d4d,
        "D5_term_clarity": judges["D5_term_clarity"]["detail"],
        "D6_factual":      judges["D6_factual"]["detail"],
        "D7_coherence":    judges["D7_coherence"]["detail"],
        "D8_info_density": judges["D8_info_density"]["detail"],
        "D9_recall":       judges["D9_recall"]["detail"],
    }
    weighted = 0.0 if vetoes else compute_weighted(scores)
    penalized, penalty = (0.0, 0.0) if vetoes else compute_penalized(scores)
    passed, reasons = check_pass(scores, vetoes)
    return {
        "chapter": chdir.name,
        "pass": passed, "pass_reasons": reasons,
        "total_weighted": round(weighted, 2),
        "total_penalized": round(penalized, 2),
        "short_board_penalty": round(penalty, 2),
        "min_dim": min(scores.values()),
        "vetoes": [{"code": v[0], "reason": v[1]} for v in vetoes],
        "scores": scores, "details": details,
    }


def print_report(r):
    p = "✅ PASS" if r["pass"] else "❌ FAIL"
    print(f"\n{'='*60}\n章节：{r['chapter']}   {p}\n{'='*60}")
    print(f"加权总分：{r['total_weighted']:.2f}    惩罚后：{r['total_penalized']:.2f}")
    print(f"最低维度：{r['min_dim']}（扣 {r['short_board_penalty']}）")
    if r["vetoes"]:
        print("\nVeto:")
        for v in r["vetoes"]:
            print(f"  [{v['code']}] {v['reason']}")
    if r["pass_reasons"]:
        print("\n未通过：")
        for reason in r["pass_reasons"]:
            print(f"  - {reason}")
    print("\nA 组（≥10 铁律）：")
    for k in STRUCT_WEIGHTS:
        s = r["scores"][k]
        m = "✓" if s >= 10 else "✗"
        print(f"  {m} {k:20s} {s:4.1f}  {r['details'][k]}")
    print("\nB 组（≥7.5；D6≥8.5）：")
    for k in QUALITY_WEIGHTS:
        s = r["scores"][k]
        gate = 8.5 if k == "D6_factual" else 7.5
        m = "✓" if s >= gate else "✗"
        d = r['details'][k][:80]
        print(f"  {m} {k:20s} {s:4.1f}  (门槛 {gate}) {d}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--chapter", required=True)
    ap.add_argument("--judges", type=Path, default=None)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()
    r = score_chapter(args.chapter, args.judges)
    if args.json:
        print(json.dumps(r, ensure_ascii=False, indent=2))
    else:
        print_report(r)
    sys.exit(0 if r["pass"] else 1)


if __name__ == "__main__":
    main()
