#!/usr/bin/env python3
"""合并单章的 D5-D9 判官 JSON 到一个 /tmp/chXX-judges.json。"""
import argparse
import json
from pathlib import Path

DIMS = ["D5_term_clarity", "D6_factual", "D7_coherence",
        "D8_info_density", "D9_recall"]
DIM_TO_FILE = {
    "D5_term_clarity": "D5",
    "D6_factual":      "D6",
    "D7_coherence":    "D7",
    "D8_info_density": "D8",
    "D9_recall":       "D9",
}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--chapter", required=True,
                    help="短前缀如 ch14；用于拼 /tmp/chXX-DN-judge.json")
    ap.add_argument("--out", required=True)
    ap.add_argument("--tmpdir", default="/tmp")
    args = ap.parse_args()

    tmpdir = Path(args.tmpdir)
    out = {}
    missing = []
    for dim, tag in DIM_TO_FILE.items():
        f = tmpdir / f"{args.chapter}-{tag}-judge.json"
        if not f.exists():
            missing.append(tag)
            out[dim] = {"score": 0.0, "detail": f"MISSING: {f}"}
            continue
        data = json.loads(f.read_text(encoding="utf-8"))
        out[dim] = {
            "score": float(data.get("score", 0.0)),
            "detail": data.get("detail", ""),
        }
    Path(args.out).write_text(
        json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    if missing:
        print(f"⚠️ 缺失判官结果: {missing}")
    print(f"✓ 合并 → {args.out}")


if __name__ == "__main__":
    main()
