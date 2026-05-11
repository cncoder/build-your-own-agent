# Chapter Rubric v3

针对 `book/chapters/chXX-*/README.md` 教材正文的评分规则。

实现：`scripts/score_chapter_v3.py`（待创建，骨架见最后）

## A 组 · 结构硬铁律（本地 regex）

每项权重 0.05，必须 = 10。

### D1 Beat 结构完整

必须包含以下标题（按顺序）：
- `## Beat 1` 路线图 / 本章脉络
- `## Beat 2` 动机
- `## Beat 3` 理论铺垫（带 Convention 定义框）
- `## Beat 4` 脚手架（至少一段可运行代码）
- `## Beat 5` 渐进组装
- `## Beat 6` 运行验证（带预期输出）
- `## Beat 7` Design Note（侧栏，至少 1 个）

缺 Beat → 扣 1.5 分/个；完全无 Beat 结构 → V5 否决。

### D2 Lena 版本推进

本章开头必须明示 Lena 版本变化（v0.X → v0.Y），且本章至少新增一个显式能力。

### D3 代码可验证性

- 至少 1 段代码 + 预期输出 blocks
- 所有代码片段有可读出的语义（变量命名合理）
- 不能全章只有伪代码

### D4 禁词禁格式

同 podcast rubric：
- `Abel` 真实姓名（V3）
- `/Users/` / `~/code/` / `~/.claude/` 本机路径（V4）
- R1-R99 内部代号（V8）
- `本章 arc`（应写 `本章脉络`）
- `Let's + 中文` 混接
- 内部 QA 工件（"20 条自查清单" / "修订日志表"）
- 内部研究文件路径 `docs/research/R*.md`

## B 组 · 内容质量（LLM 判官）

### D5 术语讲清率（权重 0.15，门槛 ≥ 7.5）

从本章 Convention 定义框抽所有术语，每个判三档：
- 讲清（1.0）= 有 Convention 定义 + 应用场景 + 示例或反例
- 仅提及（0.3）= 有定义但无示例 / 无对比 / 无落地
- 没讲（0）= 跳过了一个本该定义的术语

### D6 事实准确（权重 0.25，门槛 ≥ 8.5）

核查：
- 代码是否可运行（import 存在、签名一致、返回值类型对）
- 引用的论文 / 产品 / 数字是否准确（有来源链接最好）
- 与前后章节的 Lena 能力是否一致（不能本章写 `AgentLoop.step()` 下章改签名）
- 对第三方库的描述是否准确（boto3 / anthropic / OpenAI 最新 API）

### D7 逻辑连贯（权重 0.15，门槛 ≥ 7.5）

- Beat 1 → Beat 7 论证线索完整
- 每个 Beat 内部段落有过渡
- 名词不倒置出现（先用后定义）
- Design Note 侧栏与主线有明确关联

### D8 信息密度（权重 0.15，门槛 ≥ 7.5）

每节打标签：新信息 / 复述 / 铺垫 / 灌水。
允许 Beat 1-3 做铺垫（占 30% 内）；Beat 4-7 必须是新信息主导。

### D9 可复述性（权重 0.10，门槛 ≥ 7.5）

读者读完本章，不看书的情况下能否：
- 说出 Lena 本章新增了什么能力
- 用自己的话讲出核心 Convention 定义
- 给出一个可自己跑通的最小代码起点

## Pass 门槛（同 podcast）

```
Pass = 加权总分 ≥ 9.1
     AND A 组每项 = 10
     AND B 组每项 ≥ 7.5
     AND D6 ≥ 8.5
     AND 0 个一票否决
```

## score_chapter_v3.py 骨架（待实现）

复用 `score_podcast_v3.py` 的结构，只替换 A 组：

```python
# A 组
def score_D1_beat_structure(readme):
    required = ["Beat 1", "Beat 2", "Beat 3", "Beat 4", "Beat 5", "Beat 6", "Beat 7"]
    found = [b for b in required if re.search(rf'^## {b}', readme, re.M)]
    ...

def score_D2_lena_version(readme):
    # 必须有 v0.X → v0.Y 的明示
    m = re.search(r'v0\.\d+.*→.*v0\.\d+|v\d\.\d+.*升到.*v\d\.\d+', readme)
    ...

def score_D3_code_validity(readme):
    # 必须 ≥ 1 段 ```python 代码 + 预期输出 block
    code_blocks = re.findall(r'```python\n(.*?)```', readme, re.S)
    output_blocks = re.findall(r'```\n(.*?)```', readme, re.S)
    ...

def score_D4_no_banned(readme):
    # 同 podcast 的禁词表，加 README 特有禁项
    ...

# B 组：5 judge prompt 专门为正文设计（见 judges/chapter-*.md）
```
