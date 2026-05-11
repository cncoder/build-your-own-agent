#!/usr/bin/env python3
"""
score_podcast_v3.py — 播客脚本量化评分器 v3（防作弊 + 防短板）

相比 v2 的核心改动：
- 维度分 A 组（结构硬铁律）+ B 组（内容质量，需要 LLM 判官）
- 双门槛 pass：总分≥9.1 AND A 组全=10 AND B 组全≥7.5 AND 事实准确≥8.5
- 几何平均 + 短板惩罚，避免加权平均稀释低分
- B 组维度从外部 JSON 注入（LLM 判官产物）

用法：
    # 只跑 A 组（本地结构检查）
    python3 scripts/score_podcast_v3.py --chapter ch14-execution-safety

    # 注入 B 组（LLM 判官结果）
    python3 scripts/score_podcast_v3.py --chapter ch14-execution-safety \
        --judges /tmp/ch14-judges.json

--judges JSON 格式：
{
  "D5_term_clarity": {"score": 7.5, "detail": "..."},
  "D6_factual":      {"score": 8.2, "detail": "..."},
  "D7_coherence":    {"score": 8.0, "detail": "..."},
  "D8_info_density": {"score": 7.0, "detail": "..."},
  "D9_recall":       {"score": 8.5, "detail": "..."}
}
"""

import argparse
import json
import re
import sys
from pathlib import Path
from collections import Counter

CHAPTERS_BASE = Path(__file__).parent.parent / "book" / "chapters"

# ─────────────────────────────────────────────────────────────────────────────
# A 组：结构硬铁律（本地 regex 可判定）
# ─────────────────────────────────────────────────────────────────────────────

STRUCT_WEIGHTS = {
    "D1_tao_ratio":   0.05,   # 涛哥字数 ≥95%（周迅<5% 铁律）
    "D2_zhou_length": 0.05,   # 周迅单段 ≤50 字
    "D3_seg_length":  0.05,   # 每段 ≤290 字
    "D4_no_banned":   0.05,   # 无禁词（Let's/R代号/Abel/本机路径）
}

# B 组：内容质量（LLM 判官打分）
QUALITY_WEIGHTS = {
    "D5_term_clarity": 0.15,  # README 核心术语"讲清率"（不是出现率）
    "D6_factual":      0.25,  # 事实准确（对照 README 逐段核）
    "D7_coherence":    0.15,  # 逻辑连贯（段间过渡）
    "D8_info_density": 0.15,  # 信息增量密度（每段是否推进新信息）
    "D9_recall":       0.10,  # 听众可复述（扮学生复述 5 核心命题成功率）
}

ALL_WEIGHTS = {**STRUCT_WEIGHTS, **QUALITY_WEIGHTS}
assert abs(sum(ALL_WEIGHTS.values()) - 1.0) < 0.001, "权重之和必须为 1.0"

# Pass 门槛（多条件与）
PASS_GATES = {
    "total_score":     9.1,   # 总分下限
    "struct_each":     10.0,  # A 组每项必须 =10
    "quality_each":    7.5,   # B 组每项 ≥ 7.5
    "factual_min":     8.5,   # D6 事实准确单独抬高
}

# ─────────────────────────────────────────────────────────────────────────────
# 一票否决（硬规则，违即 0 分）
# ─────────────────────────────────────────────────────────────────────────────

def check_vetoes(podcast_text: str) -> list[tuple[str, str]]:
    vetoes = []
    tao_words = sum(len(re.sub(r'\s+', '', s))
                    for s in re.findall(r'【窦文涛】(.*?)(?=【|$)', podcast_text, re.S))
    zhou_words = sum(len(re.sub(r'\s+', '', s))
                     for s in re.findall(r'【周迅】(.*?)(?=【|$)', podcast_text, re.S))
    total = tao_words + zhou_words

    if total > 0 and tao_words / total < 0.90:
        vetoes.append(("V1", f"涛哥字数占比 {tao_words/total:.1%} < 90%"))

    if total > 0 and zhou_words / total >= 0.05:
        vetoes.append(("V10", f"周迅字数占比 {zhou_words/total:.1%} ≥ 5%（铁律）"))

    for seg in re.findall(r'【周迅】(.*?)(?=【|$)', podcast_text, re.S):
        clean = re.sub(r'\s+', '', seg.strip())
        if len(clean) > 120:
            vetoes.append(("V2", f"周迅单段 {len(clean)} 字 > 120"))
            break

    if re.search(r'\bAbel\b', podcast_text):
        vetoes.append(("V3", "出现 Abel 人名"))
    if re.search(r'/Users/|~/code/|~/\.claude/', podcast_text):
        vetoes.append(("V4", "出现本机路径"))

    if re.search(r"Let's.*[一-鿿]|[一-鿿].*Let's", podcast_text):
        vetoes.append(("V7", "Let's + 中文混用"))

    # R 代号（排除已知术语）
    for m in re.finditer(r'\bR[1-9][0-9]?(?:-[A-Z])?\b(?!\w)', podcast_text):
        token = m.group(0)
        if token not in ('ReAct', 'RAG', 'REST', 'RSS', 'RSI', 'RLHF'):
            vetoes.append(("V8", f"内部代号 {token}"))
            break

    for seg in re.findall(r'【(?:窦文涛|周迅)】(.*?)(?=【|$)', podcast_text, re.S):
        clean = re.sub(r'\s+', '', seg.strip())
        if len(clean) > 320:
            vetoes.append(("V9", f"单段 {len(clean)} 字 > 320（TTS 限制）"))
            break

    return vetoes

# ─────────────────────────────────────────────────────────────────────────────
# A 组评分
# ─────────────────────────────────────────────────────────────────────────────

def score_D1_tao_ratio(podcast: str) -> tuple[float, str]:
    tao = sum(len(re.sub(r'\s+', '', s))
              for s in re.findall(r'【窦文涛】(.*?)(?=【|$)', podcast, re.S))
    zhou = sum(len(re.sub(r'\s+', '', s))
               for s in re.findall(r'【周迅】(.*?)(?=【|$)', podcast, re.S))
    if tao + zhou == 0:
        return 0.0, "无对话"
    r = tao / (tao + zhou)
    score = 10.0 if r >= 0.95 else (7.0 if r >= 0.92 else (4.0 if r >= 0.90 else 0.0))
    return score, f"涛哥占比 {r:.1%}（{tao}/{tao+zhou}）"


def score_D2_zhou_length(podcast: str) -> tuple[float, str]:
    zhou_segs = re.findall(r'【周迅】(.*?)(?=【|$)', podcast, re.S)
    if not zhou_segs:
        return 10.0, "无周迅段"
    over = sum(1 for s in zhou_segs if len(re.sub(r'\s+', '', s.strip())) > 50)
    if over == 0:
        return 10.0, f"{len(zhou_segs)} 段周迅全部 ≤50 字"
    elif over == 1:
        return 7.0, f"{over}/{len(zhou_segs)} 段超 50 字"
    elif over == 2:
        return 4.0, f"{over}/{len(zhou_segs)} 段超 50 字"
    return 0.0, f"{over}/{len(zhou_segs)} 段超 50 字"


def score_D3_seg_length(podcast: str) -> tuple[float, str]:
    segs = re.findall(r'【(?:窦文涛|周迅)】(.*?)(?=【|$)', podcast, re.S)
    over = [len(re.sub(r'\s+', '', s.strip())) for s in segs
            if len(re.sub(r'\s+', '', s.strip())) > 290]
    if not over:
        return 10.0, f"{len(segs)} 段全部 ≤290 字"
    if max(over) > 320:
        return 0.0, f"{len(over)} 段超 290 字，最长 {max(over)}（触发 V9）"
    return 4.0, f"{len(over)} 段在 290-320 区间（警告）"


BANNED_PATTERNS = [
    (r"Let's.*[一-鿿]|[一-鿿].*Let's", "Let's+中文"),
    (r"\bSo here we go\b", "So here we go"),
    (r"\bThat's it\b", "That's it"),
    (r"\bNow it is time\b", "Now it is time"),
    (r"本章 arc", "本章 arc"),
    (r"本节讨论", "本节讨论"),
    (r"接下来我们将", "接下来我们将"),
    (r"\bAbel\b", "Abel 人名"),
    (r"/Users/|~/code/|~/\.claude/", "本机路径"),
    (r"\bR[1-9][0-9]?-[A-Z]\b", "内部代号 RX-Y"),
]

def score_D4_no_banned(podcast: str) -> tuple[float, str]:
    hits = []
    for pat, name in BANNED_PATTERNS:
        if re.search(pat, podcast):
            hits.append(name)
    if not hits:
        return 10.0, "无禁词"
    return 0.0, f"触发 {len(hits)} 类禁词：{hits}"


# ─────────────────────────────────────────────────────────────────────────────
# B 组占位（外部 LLM 判官注入）
# ─────────────────────────────────────────────────────────────────────────────

def load_judges(judges_path: Path | None) -> dict[str, dict]:
    """从 JSON 读取 B 组打分。缺失的项目给 0 分 + 标记 MISSING。"""
    if not judges_path or not judges_path.exists():
        return {k: {"score": 0.0, "detail": "MISSING: 未运行 LLM 判官"}
                for k in QUALITY_WEIGHTS}
    data = json.loads(judges_path.read_text(encoding="utf-8"))
    out = {}
    for k in QUALITY_WEIGHTS:
        entry = data.get(k) or {}
        out[k] = {
            "score": float(entry.get("score", 0.0)),
            "detail": entry.get("detail", "MISSING"),
        }
    return out

# ─────────────────────────────────────────────────────────────────────────────
# 综合打分
# ─────────────────────────────────────────────────────────────────────────────

def compute_weighted_sum(scores: dict[str, float]) -> float:
    return sum(scores[k] * ALL_WEIGHTS[k] for k in ALL_WEIGHTS)


def compute_geometric_mean(scores: dict[str, float]) -> float:
    """几何加权平均：对短板更敏感，任一维度=0 → 总分=0。"""
    import math
    if any(s <= 0 for s in scores.values()):
        return 0.0
    log_sum = sum(ALL_WEIGHTS[k] * math.log(scores[k]) for k in ALL_WEIGHTS)
    return math.exp(log_sum)


def compute_penalized(scores: dict[str, float]) -> tuple[float, float]:
    """
    加权平均 − 短板惩罚（平方项）。
    返回 (最终分, 惩罚值)。
    """
    weighted = compute_weighted_sum(scores)
    min_score = min(scores.values())
    penalty = 0.15 * (10.0 - min_score) ** 2 / 10.0  # 归一化到 10 分制
    return max(0.0, weighted - penalty), penalty


def check_pass(scores: dict[str, float], vetoes: list) -> tuple[bool, list[str]]:
    """返回 (pass, 失败原因列表)"""
    reasons = []
    if vetoes:
        reasons.append(f"触发 {len(vetoes)} 个一票否决")
        return False, reasons

    total, _ = compute_penalized(scores)
    if total < PASS_GATES["total_score"]:
        reasons.append(f"总分 {total:.2f} < {PASS_GATES['total_score']}")

    for k in STRUCT_WEIGHTS:
        if scores[k] < PASS_GATES["struct_each"]:
            reasons.append(f"{k} = {scores[k]} < {PASS_GATES['struct_each']}（结构铁律）")

    for k in QUALITY_WEIGHTS:
        if scores[k] < PASS_GATES["quality_each"]:
            reasons.append(f"{k} = {scores[k]} < {PASS_GATES['quality_each']}（内容短板）")

    if scores.get("D6_factual", 0) < PASS_GATES["factual_min"]:
        reasons.append(
            f"D6_factual = {scores['D6_factual']} < {PASS_GATES['factual_min']}"
            f"（事实准确单独门槛）"
        )

    return len(reasons) == 0, reasons


def score_chapter(chapter_name: str, judges_path: Path | None) -> dict:
    chdir = CHAPTERS_BASE / chapter_name
    if not chdir.exists():
        matches = [d for d in CHAPTERS_BASE.iterdir()
                   if d.is_dir() and d.name.startswith(chapter_name)]
        if not matches:
            raise FileNotFoundError(chapter_name)
        chdir = sorted(matches)[0]

    podcast = (chdir / "podcast.md").read_text(encoding="utf-8")
    readme = (chdir / "README.md").read_text(encoding="utf-8")
    vetoes = check_vetoes(podcast)

    # A 组
    d1, d1d = score_D1_tao_ratio(podcast)
    d2, d2d = score_D2_zhou_length(podcast)
    d3, d3d = score_D3_seg_length(podcast)
    d4, d4d = score_D4_no_banned(podcast)

    # B 组
    judges = load_judges(judges_path)

    scores = {
        "D1_tao_ratio":   d1,
        "D2_zhou_length": d2,
        "D3_seg_length":  d3,
        "D4_no_banned":   d4,
        "D5_term_clarity": judges["D5_term_clarity"]["score"],
        "D6_factual":      judges["D6_factual"]["score"],
        "D7_coherence":    judges["D7_coherence"]["score"],
        "D8_info_density": judges["D8_info_density"]["score"],
        "D9_recall":       judges["D9_recall"]["score"],
    }
    details = {
        "D1_tao_ratio":   d1d,
        "D2_zhou_length": d2d,
        "D3_seg_length":  d3d,
        "D4_no_banned":   d4d,
        "D5_term_clarity": judges["D5_term_clarity"]["detail"],
        "D6_factual":      judges["D6_factual"]["detail"],
        "D7_coherence":    judges["D7_coherence"]["detail"],
        "D8_info_density": judges["D8_info_density"]["detail"],
        "D9_recall":       judges["D9_recall"]["detail"],
    }

    weighted_sum = 0.0 if vetoes else compute_weighted_sum(scores)
    penalized, penalty = (0.0, 0.0) if vetoes else compute_penalized(scores)
    geom = 0.0 if vetoes else compute_geometric_mean(scores)

    passed, reasons = check_pass(scores, vetoes)

    return {
        "chapter": chdir.name,
        "pass": passed,
        "pass_reasons": reasons,
        "total_weighted_sum": round(weighted_sum, 2),
        "total_penalized":    round(penalized, 2),
        "total_geometric":    round(geom, 2),
        "short_board_penalty": round(penalty, 2),
        "min_dim_score":      min(scores.values()),
        "vetoes": [{"code": v[0], "reason": v[1]} for v in vetoes],
        "scores": scores,
        "details": details,
        "weights": ALL_WEIGHTS,
        "gates": PASS_GATES,
    }


def print_report(r: dict) -> None:
    p = "✅ PASS" if r["pass"] else "❌ FAIL"
    print(f"\n{'='*62}")
    print(f"章节：{r['chapter']}   {p}")
    print(f"{'='*62}")
    print(f"加权总分：{r['total_weighted_sum']:.2f}")
    print(f"短板惩罚后：{r['total_penalized']:.2f}（扣 {r['short_board_penalty']}）")
    print(f"几何平均：{r['total_geometric']:.2f}")
    print(f"最低维度分：{r['min_dim_score']}")

    if r["vetoes"]:
        print(f"\n一票否决：")
        for v in r["vetoes"]:
            print(f"  [{v['code']}] {v['reason']}")

    if r["pass_reasons"]:
        print(f"\n未通过原因：")
        for reason in r["pass_reasons"]:
            print(f"  - {reason}")

    print(f"\nA 组（结构硬铁律，每项必 =10）：")
    for k in STRUCT_WEIGHTS:
        w = ALL_WEIGHTS[k]
        s = r["scores"][k]
        mark = "✓" if s >= 10 else "✗"
        print(f"  {mark} {k:20s} {s:4.1f}/10  (权重 {w*100:.0f}%)  {r['details'][k]}")

    print(f"\nB 组（内容质量，每项 ≥7.5；事实单独 ≥8.5）：")
    for k in QUALITY_WEIGHTS:
        w = ALL_WEIGHTS[k]
        s = r["scores"][k]
        gate = PASS_GATES["factual_min"] if k == "D6_factual" else PASS_GATES["quality_each"]
        mark = "✓" if s >= gate else "✗"
        print(f"  {mark} {k:20s} {s:4.1f}/10  (权重 {w*100:.0f}%, 门槛 {gate}) {r['details'][k][:80]}")

    print(f"\nPass 条件：")
    print(f"  ① 加权总分 ≥ {PASS_GATES['total_score']}")
    print(f"  ② A 组每项 = {PASS_GATES['struct_each']}")
    print(f"  ③ B 组每项 ≥ {PASS_GATES['quality_each']}")
    print(f"  ④ D6 事实准确 ≥ {PASS_GATES['factual_min']}")
    print(f"  ⑤ 0 个一票否决")
    print(f"{'='*62}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--chapter", required=True)
    ap.add_argument("--judges", type=Path, default=None,
                    help="LLM 判官 JSON 结果（可选）")
    ap.add_argument("--json", action="store_true", help="只输出 JSON")
    args = ap.parse_args()

    r = score_chapter(args.chapter, args.judges)
    if args.json:
        print(json.dumps(r, ensure_ascii=False, indent=2))
    else:
        print_report(r)

    sys.exit(0 if r["pass"] else 1)


if __name__ == "__main__":
    main()
