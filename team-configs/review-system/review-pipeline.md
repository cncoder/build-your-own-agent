# Review Pipeline · A/B/C/D/E/F 六角色执行指南

> 单章从 zero 到 pass 的完整流程。本流程适用于 podcast.md 和 README.md 两种 artifact。

## 六角色分工

| 角色 | 身份 | 产出路径 | 执行方 |
|------|------|---------|--------|
| **A · 生成** | 作者，主 agent 出初稿 | `{target_path}` | 主 agent |
| **B · 评测** | 本地规则引擎 | JSON + stdout | `scripts/score_*_v3.py` |
| **C · 对标** | 行业范式审核 | `/tmp/chXX-benchmark-C.md` | 子 agent |
| **D5** 术语讲清 | LLM 判官 | `/tmp/chXX-D5-judge.json` | 子 agent |
| **D6** 事实准确 | LLM 判官 | `/tmp/chXX-D6-judge.json` | 子 agent |
| **D7** 逻辑连贯 | LLM 判官 | `/tmp/chXX-D7-judge.json` | 子 agent |
| **D8** 信息密度 | LLM 判官 | `/tmp/chXX-D8-judge.json` | 子 agent |
| **D9** 可复述 | LLM 判官 | `/tmp/chXX-D9-judge.json` | 子 agent |
| **E · 学生** | 零基础读者视角 | `/tmp/chXX-student-E.md` | 子 agent |
| **F · 讲师** | 资深技术讲师 | `/tmp/chXX-lecturer-F.md` | 子 agent |
| **D · 总编** | 整合重写 | 回落到 `{target_path}` | 主 agent |

## 单章 pipeline

```
┌─ A 生成初稿 ─┐
│              │
│              ▼
│      {target_path}
│              │
│  ┌───────────┴───────────┐
│  │          阶段 2：      │
│  │   C/E/F + D5/D6/D7/D8/D9    │
│  │    8 路子 agent 并发      │
│  └───────────┬───────────┘
│              │
│              ▼
│       合并所有反馈
│              │
│              ▼
│    D 总编重写 artifact
│              │
│              ▼
│       B 评分（含 judge）
│              │
│         ┌────┴────┐
│         │         │
│        Pass     Fail
│         │         │
│     done     ─────┘（回到阶段 2，最多 5 轮）
```

## 阶段详解

### 阶段 1 · A 生成

主 agent 读 README 写初稿。初稿要求：
- 涛哥 ≥ 95% 字数（播客）/ Beat 1-7 完整（正文）
- 2500-4500 字
- 禁词表全部不出现

### 阶段 2 · 8 路并发评审（一个消息块发出）

并发不可让步——TaskList 必须显示 ≥ 5 个同时 in_progress，否则评审系统失效。

**判官 prompt 从 `judges/D*-prompt.md` 复制**，替换 `{target_path}` 和 `{readme_path}` 变量。

每个判官独立读材料、独立打分、独立输出 JSON。**严禁在一次调用里合并多个判官**（prompt 污染）。

### 阶段 3 · 合并反馈

D 总编（主 agent）读：
- B 的本地分数
- C/E/F 的 markdown 审阅
- D5-D9 五份 JSON

按优先级整理修改清单：
1. 一票否决（V1-V11） → 立刻修
2. A 组 < 10 → 修（结构问题）
3. D6 < 8.5 → 修（事实）
4. 其他 B 组 < 7.5 → 修
5. 加权总分 < 9.1 → 综合优化

### 阶段 4 · D 重写

**切忌一刀切改写**。按 C/E/F/D5-D9 的具体引文定位改动点：
- D6 的事实错误 → 按 detail 里的"原句 X → 应为 Y"逐条修
- D7 的硬过渡 → 按 detail 里的段号改过渡句
- D8 的堆砌段 → 合并或拆掉
- D9 的可复述短板 → 补具体例子和细节

每次改动尽量原位替换，不扩写。

### 阶段 5 · B 复评

`scripts/score_*_v3.py --chapter chXX --judges /tmp/chXX-judges.json`

不再跑 LLM 判官（除非 D 大改）。如果只改了 D6/D7/D8/D9 的具体问题，重跑对应判官验证。

### Loop 终止条件

- **通过**：5 项 Pass 条件全满足 → commit
- **5 轮失败**：打印最后一次 score + 失败原因 → 人工介入
- **退化**：重写后总分比上轮低 → 回滚到上轮 artifact

## 批量 24 章并发

### 章节级并行（同时处理 N 章）

资源约束：Agent 工具单会话并发上限 ~10 个 task in_progress。
推荐：同时跑 **3 章** × **8 路子 agent** = **24 并发任务**（接近 session 上限）。

### 执行命令（Bash 编排）

```bash
# 并行跑 3 章一轮 LLM 判官
for ch in ch02 ch03 ch04; do
    for dim in D5 D6 D7 D8 D9; do
        spawn_agent --chapter $ch --dim $dim &
    done
done
wait

# 合并结果
for ch in ch02 ch03 ch04; do
    python3 scripts/merge_judges.py --chapter $ch
    python3 scripts/score_podcast_v3.py --chapter $ch \
        --judges /tmp/${ch}-judges.json
done
```

## 失败处理

**单维度反复卡住**：
- D6 连续 3 轮 < 8.5 → 主 agent 可能读错 README，重新逐行对读
- D7 连续 3 轮 < 7.5 → 节奏问题根深，考虑推倒重构不修补
- D9 连续 3 轮 < 7.5 → 信息抽象过度，补具体例子和数字锚点

**评分脚本异常**：
- 权重和 != 1.0 → 脚本报 AssertionError，检查 `ALL_WEIGHTS`
- 否决项逻辑触发不合理 → 查 `check_vetoes`，更新 `BANNED_PATTERNS`

## 版本

- v1 废弃（自评无第三方）
- v2 部分部署（6 维度加权，D6 覆盖率被刷分作弊）
- **v3 当前**（9 维度 + 双门槛 + LLM 判官 + 短板惩罚）

## 真实案例：ch14 验证

**A 稿**：10/10（v2 满分）  
**v3 评分**：8.03/10（Fail）  
**扣分原因**：
- D6 事实 7.5（chattr 段编造）
- D7 连贯 7.2（开头 Beat1-7 违规）
- D9 可复述 7.3（最小权限三规则细节模糊）

**证明**：v3 抓到了 v2 纯结构评分抓不出的内容质量问题。

详见 `/tmp/ch14-D*-judge.json` 和 `book/chapters/ch14-execution-safety/podcast.md`。
