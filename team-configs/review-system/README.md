# 完整评审系统 · Review System v3

> 本系统是本书所有 artifact 的**统一质量守门**，覆盖播客脚本 + 教材正文。
> 设计原则：防作弊 · 防短板 · LLM 判官 + 本地 regex 铁律双层兜底。

## 系统构成

```
             artifact (podcast.md / README.md)
                         │
                         ▼
           ┌─────────────────────────────┐
           │ A/B/C/D/E/F 六角色评审 pipeline │
           └──────────────┬──────────────┘
                          │
       ┌──────────────────┼──────────────────┐
       │                  │                  │
       ▼                  ▼                  ▼
    A (生成)       B (本地 regex)      C/E/F (LLM 判官)
 主 agent 写稿   score_*.py          对标/学生/讲师
                 scripts/score_*_v3                各 1 judge
                                                   │
                                                   ▼
                                     D5-D9 (LLM 判官 x5)
                                     术语/事实/连贯/密度/可复述
                                                   │
                          所有子 agent 产物合并 → D 总编
                                       │
                                       ▼
                              重写 artifact → 再评
                              (≥ 9.1 才算过)
```

## 两种 artifact

| Artifact       | 评分脚本                     | 通用性    |
|----------------|------------------------------|-----------|
| podcast.md     | `scripts/score_podcast_v3.py` | 音频友好，涛哥/周迅铁律 |
| README.md 正文 | `scripts/score_chapter_v3.py` | 书面友好，Beat 结构铁律 |

两份脚本复用同一套 **9 维度 + 双门槛** 评分骨架，只是：
- **A 组铁律**不同（播客管涛哥比、段长；正文管 Beat 结构、术语定义框）
- **B 组内容质量维度相同**（术语讲清、事实准确、逻辑连贯、信息密度、可复述）

## 文件组织

```
team-configs/review-system/
├── README.md                        本文件，系统总览
├── rubric-podcast-v3.md             播客脚本评分规则（本文档）
├── rubric-chapter-v3.md             教材正文评分规则
├── judges/
│   ├── D5-term-clarity-prompt.md    术语讲清判官 prompt
│   ├── D6-factual-prompt.md         事实准确判官 prompt
│   ├── D7-coherence-prompt.md       逻辑连贯判官 prompt
│   ├── D8-info-density-prompt.md    信息密度判官 prompt
│   └── D9-recall-prompt.md          可复述判官 prompt
├── review-pipeline.md               A/B/C/D/E/F pipeline 执行指南
└── reviewer-agents/
    ├── C-benchmark.md               对标 agent 角色
    ├── E-student.md                 学生 agent 角色
    └── F-lecturer.md                讲师 agent 角色
```

## 9 维度（podcast + chapter 通用）

| 维度 | 名称 | 权重 | 组 | 谁评 | 门槛 |
|------|------|------|-----|------|------|
| D1 | 结构铁律 A | 0.05 | A | 本地 regex | = 10 |
| D2 | 结构铁律 B | 0.05 | A | 本地 regex | = 10 |
| D3 | 结构铁律 C | 0.05 | A | 本地 regex | = 10 |
| D4 | 禁词禁格式 | 0.05 | A | 本地 regex | = 10 |
| D5 | 术语讲清率 | 0.15 | B | LLM 判官 | ≥ 7.5 |
| **D6** | **事实准确** | **0.25** | B | LLM 判官 | **≥ 8.5** |
| D7 | 逻辑连贯 | 0.15 | B | LLM 判官 | ≥ 7.5 |
| D8 | 信息密度 | 0.15 | B | LLM 判官 | ≥ 7.5 |
| D9 | 可复述性 | 0.10 | B | LLM 判官 | ≥ 7.5 |

## Pass 门槛（同时满足）

- ① 加权总分 ≥ **9.1**
- ② A 组每项 = **10**（结构铁律必须满分）
- ③ B 组每项 ≥ **7.5**（内容质量短板门槛）
- ④ D6 事实准确 ≥ **8.5**（事实单独提高门槛）
- ⑤ 0 个一票否决（V1-V11）

**短板惩罚**：总分 = 加权和 − 0.15 × (10 − min_score)² / 10。最低维度越低，惩罚平方级增长。

## 一票否决（V1-V11）

| 编号 | 触发条件 | 适用 |
|------|---------|------|
| V1  | 主讲人字数占比 < 90%（播客）/ 跑题段落 ≥ 30%（正文） | 两者 |
| V2  | 副讲人单段 > 120 字 | 播客 |
| V3  | 出现真实人名 Abel | 两者 |
| V4  | 出现本机路径 `/Users/` `~/code/` `~/.claude/` | 两者 |
| V5  | Beat 1-3 全部缺席 | 两者 |
| V6  | ≥ 2 个 200+ 字故事段 | 两者 |
| V7  | `Let's + 中文` 混接 | 两者 |
| V8  | R 代号（R5, R7-G 等内部编号）| 两者 |
| V9  | 单段 > 320 字（TTS chunk 限制） | 播客 |
| V10 | 副讲人字数占比 ≥ 5% | 播客 |
| V11 | README 核心术语覆盖 < 60% | 两者 |

## 反作弊机制

**v2 的漏洞**：D6 (覆盖率) 权重 0.55，判据 = "术语字符串出现"。
→ 可以通过**塞关键词**刷分，总分满分但内容堆砌。

**v3 的防御**：
1. **判官三档判定**：不只看术语出现，要看有没有**定义 / 作用 / 例子**三要素
2. **事实准确单独门槛**（0.25 权重 + ≥ 8.5 硬门槛）
3. **短板惩罚**（二次方）：任一维度低分，总分扣 (10-min)² × 0.015
4. **分组铁律**：结构必须 =10，内容必须 ≥7.5，否则无论总分多高都不过
5. **多判官独立打分**：5 个 LLM 判官 prompt 完全隔离，避免互相污染
6. **审计采样**：每批 5 章随机取 1 章让不同模型重评，分差 > 1 触发讨论

## 执行方式

**单章评审**（ch14 为例）：

```bash
# 1. 本地跑 A 组
python3 scripts/score_podcast_v3.py --chapter ch14-execution-safety

# 2. 并发启动 5 个 LLM 判官（D5-D9）
#    每个判官输出 /tmp/ch14-D{N}-judge.json

# 3. 合并 judge 结果
python3 scripts/merge_judges.py --chapter ch14 --out /tmp/ch14-judges.json

# 4. 注入 judge 分数，跑正式评分
python3 scripts/score_podcast_v3.py \
    --chapter ch14-execution-safety \
    --judges /tmp/ch14-judges.json

# 5. 未通过 → D 总编按 pass_reasons 回炉改稿 → 回到步骤 2
# 6. 通过 → commit podcast.md
```

**批量评审**（24 章）：

```bash
# 并发跑 24 × 5 = 120 个判官调用
# 单章每轮 loop 约 3-5 分钟，全书约 1.5-2 小时
```

## 版本历史

- v1（废弃）：作者 agent 自评，无独立监督
- v2（已部署）：6 维度加权平均，本地 regex 打分 → 抓到 ~3 处结构问题但 **D6 覆盖率维度被堆砌作弊刷满分**
- **v3（当前）**：9 维度 + 双门槛 + LLM 判官 + 短板惩罚
