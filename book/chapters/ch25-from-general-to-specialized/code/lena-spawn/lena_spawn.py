"""
lena-spawn — 从通用 Lena 派生专用 agent 的 CLI 工具

用法：
    python3 lena_spawn.py --domain quant --from v0.24
    python3 lena_spawn.py --domain news --output ./my-agents
    python3 lena_spawn.py --list   # 列出所有可用领域

支持领域：quant / news / devops / browser

Python >= 3.10 required
"""

import argparse
import json
import sys
from pathlib import Path

# ─────────────────────────────────────────
# 领域配置注册表
# ─────────────────────────────────────────

DOMAIN_CONFIGS = {
    "quant": {
        "name": "量化 Lena",
        "description": "量化交易分析助手——技术指标计算、策略分析、市场数据查询",
        "tools": [
            "technical_indicators",  # talib 包装：RSI/MACD/布林带
            "exchange_api",          # ccxt 包装：实时行情
            "backtest_runner",       # freqtrade 策略回测
        ],
        "skills": [
            "market-analysis",       # 如何分析策略胜率/最大回撤/夏普比率
            "risk-management",       # 仓位管理和止损原则
        ],
        "prune": [
            "docker_sandbox",        # 削减原因：执行延迟 <50ms，sandbox 200-500ms 不可接受
        ],
        "safety_mode": "moderate",   # 比通用稍宽松（无 sandbox），但保留人类确认
        "topology": "single",        # 单 agent 深推理
    },
    "news": {
        "name": "新闻 Lena",
        "description": "新闻播报助手——RSS 聚合、内容筛选、播客脚本生成",
        "tools": [
            "rss_reader",            # feedparser 包装：批量 RSS 拉取
            "headline_extractor",    # 提取关键信息
            "tts_synthesizer",       # 文本转语音（可接本地 TTS 或云端 API）
        ],
        "skills": [
            "news-broadcast",        # 如何改写新闻为口语化播客脚本
            "editorial-judgment",    # 如何评估新闻重要性和可信度
        ],
        "prune": [],                 # 不削减任何核心模块
        "safety_mode": "standard",
        "topology": "multi",         # 多 agent：编辑子 agent + 主播子 agent
    },
    "devops": {
        "name": "DevOps Lena",
        "description": "云运维助手——AWS/K8s 资源管理，强化执行安全",
        "tools": [
            "aws_cli",               # boto3 包装：EC2/S3/Lambda/CloudWatch
            "kubectl",               # kubernetes 资源操作
            "terraform_plan",        # 查看 Terraform 计划（只读）
        ],
        "skills": [
            "aws-incident-response", # 故障排查 SOP
            "k8s-deployment",        # 标准部署流程和回滚流程
        ],
        "prune": [],
        "safety_mode": "strict",     # 比通用更严格：所有写操作强制二次确认
        "topology": "single",
    },
    "browser": {
        "name": "浏览器 Lena",
        "description": "浏览器自动化助手——CDP 控制、DOM 感知、端到端任务",
        "tools": [
            "cdp_navigate",          # 打开 URL、等待加载
            "dom_extract",           # 提取页面文本（CSS selector）
            "take_screenshot",       # 截图（多模态视觉确认）
            "fill_form",             # 填写表单
            "click_element",         # 点击元素
        ],
        "skills": [
            "web-navigation",        # 如何分解网页任务、处理登录态、反爬对策
        ],
        "prune": [
            "multi_agent",           # 浏览器状态是全局的，并发子 agent 会导致 CDP session 冲突
        ],
        "safety_mode": "standard",
        "topology": "single",        # 单 agent 深推理（浏览器状态需要连续维护）
    },
}

# ─────────────────────────────────────────
# 文件模板生成
# ─────────────────────────────────────────

def agent_py_template(domain: str, cfg: dict, base_version: str) -> str:
    tools_imports = "\n".join(f"from tools.{t} import {t}" for t in cfg["tools"])
    tools_register = "\n".join(f"registry.register({t})" for t in cfg["tools"])
    safety_comment = {
        "strict":   "# 严格模式：所有写操作强制二次确认",
        "moderate": "# 适中模式：读操作无需确认，写操作需确认",
        "standard": "# 标准模式：不可逆操作需确认",
    }[cfg["safety_mode"]]

    return f'''"""
{cfg["name"]} — 派生自 Lena {base_version}
生成工具：lena_spawn.py --domain {domain}

领域：{cfg["description"]}
工具集：{", ".join(cfg["tools"])}
已削减：{", ".join(cfg["prune"]) if cfg["prune"] else "无"}
拓扑：{"单 agent 深推理" if cfg["topology"] == "single" else "多 agent 协作"}
"""

from lena_core import AgentLoop, ToolRegistry

{tools_imports}

registry = ToolRegistry()
{tools_register}

{safety_comment}

SYSTEM_PROMPT = """你是 {cfg["name"]}，{cfg["description"]}。

操作原则：
- 读取/查询类操作：直接执行，不需要询问
- 写入/修改/删除类操作：{"执行前必须列出操作摘要并等待用户明确确认（输入 yes）" if cfg["safety_mode"] == "strict" else "不可逆操作前询问确认"}
- 遇到超出能力范围的请求：直接说明，不要胡乱尝试
"""

agent = AgentLoop(
    system_prompt=SYSTEM_PROMPT,
    tools=registry,
    max_steps={"single": 20, "multi": 30}["{cfg["topology"]}"],
)

if __name__ == "__main__":
    import sys
    task = " ".join(sys.argv[1:]) if len(sys.argv) > 1 else "你好，介绍一下你能做什么"
    result = agent.run(task)
    print(result)
'''


def readme_template(domain: str, cfg: dict, base_version: str) -> str:
    prune_section = ""
    if cfg["prune"]:
        prune_section = f"\n## 已削减模块\n" + "\n".join(
            f"- `{p}`（原因见 agent.py 注释）" for p in cfg["prune"]
        )

    return f"""# {cfg["name"]} — 派生自 Lena {base_version}

{cfg["description"]}

## 新增工具

{chr(10).join(f"- `{t}`" for t in cfg["tools"])}
{prune_section}
## 新增 Skills

{chr(10).join(f"- `{s}`" for s in cfg["skills"])}

## 安全模式

`{cfg["safety_mode"]}` — {"所有写操作强制二次确认" if cfg["safety_mode"] == "strict" else "标准安全层（不可逆操作需确认）"}

## 拓扑

{"单 agent 深推理" if cfg["topology"] == "single" else "多 agent 协作（主 agent + 领域子 agent）"}

## 快速启动

```bash
pip3 install -r requirements.txt
python3 agent.py "你的任务描述"
```

## 派生来源

- 基础版本：Lena {base_version}
- 生成时间：由 lena_spawn.py 自动生成
- 修改指南：参见《从零构建你的 AI Agent》终章（Ch25）
"""


def requirements_template(domain: str) -> str:
    domain_deps = {
        "quant":   ["ta-lib>=0.4.28", "ccxt>=4.3.0", "freqtrade"],
        "news":    ["feedparser>=6.0.10", "requests>=2.31.0"],
        "devops":  ["boto3>=1.34.0", "kubernetes>=28.1.0"],
        "browser": ["websockets>=12.0", "Pillow>=10.0.0"],
    }
    base_deps = ["anthropic>=0.36.0", "pydantic>=2.5.0"]
    all_deps = base_deps + domain_deps.get(domain, [])
    return "\n".join(all_deps) + "\n"


# ─────────────────────────────────────────
# 派生逻辑
# ─────────────────────────────────────────

def spawn(domain: str, base_version: str, output_dir: str) -> None:
    cfg = DOMAIN_CONFIGS[domain]
    out = Path(output_dir) / f"lena-{domain}"

    if out.exists():
        print(f"目录 {out} 已存在。跳过（不覆盖）。")
        print("如需重新生成，先删除该目录。")
        return

    out.mkdir(parents=True)
    (out / "tools").mkdir()
    (out / "skills").mkdir()

    # 主要文件
    (out / "agent.py").write_text(agent_py_template(domain, cfg, base_version))
    (out / "README.md").write_text(readme_template(domain, cfg, base_version))
    (out / "requirements.txt").write_text(requirements_template(domain))

    # 工具骨架
    for tool in cfg["tools"]:
        tool_file = out / "tools" / f"{tool}.py"
        tool_file.write_text(
            f'"""工具骨架：{tool}\n'
            f'TODO: 实现此工具，或替换为真实实现\n"""\n\n'
            f'def {tool}(*args, **kwargs):\n'
            f'    raise NotImplementedError("请实现 {tool} 工具")\n'
        )

    # skill 骨架
    for skill in cfg["skills"]:
        skill_dir = out / "skills" / skill
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text(
            f"---\nname: {skill}\n"
            f"description: {cfg['name']} 的 {skill} 技能。"
            f"用于处理{cfg['description'][:20]}相关任务。\n---\n\n"
            f"# {skill} Skill\n\nTODO: 填写领域 SOP 和工作流程\n"
        )

    # 派生元数据
    meta = {
        "domain": domain,
        "base_version": base_version,
        "name": cfg["name"],
        "topology": cfg["topology"],
        "safety_mode": cfg["safety_mode"],
        "pruned_modules": cfg["prune"],
    }
    (out / ".lena-spawn.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2))

    print(f"\n✓ {cfg['name']} 已创建：{out.resolve()}")
    print(f"\n文件结构：")
    for f in sorted(out.rglob("*")):
        rel = f.relative_to(out)
        indent = "  " * (len(rel.parts) - 1)
        print(f"  {indent}{rel.name}{'/' if f.is_dir() else ''}")
    print(f"\n下一步：")
    print(f"  1. 实现 tools/ 下的骨架函数")
    print(f"  2. 填写 skills/ 下的 SKILL.md 内容")
    print(f"  3. 运行 python3 {out.name}/agent.py \"你的第一个任务\"")


def list_domains() -> None:
    print("\n可用领域：\n")
    for key, cfg in DOMAIN_CONFIGS.items():
        pruned = f"，削减：{', '.join(cfg['prune'])}" if cfg["prune"] else ""
        print(f"  {key:10s}  {cfg['name']}  —  {cfg['description'][:40]}...{pruned}")
    print()


# ─────────────────────────────────────────
# CLI
# ─────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="lena-spawn：从通用 Lena 派生专用 agent",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="示例：\n"
               "  python3 lena_spawn.py --domain quant\n"
               "  python3 lena_spawn.py --domain news --from v0.24 --output ./agents\n"
               "  python3 lena_spawn.py --list",
    )
    parser.add_argument("--domain", choices=list(DOMAIN_CONFIGS), help="目标领域")
    parser.add_argument("--from", dest="base", default="v0.24", help="基础版本（默认 v0.24）")
    parser.add_argument("--output", default=".", help="输出目录（默认当前目录）")
    parser.add_argument("--list", action="store_true", help="列出所有可用领域")

    args = parser.parse_args()

    if args.list:
        list_domains()
        return

    if not args.domain:
        parser.error("请指定 --domain，或使用 --list 查看可用领域")

    spawn(args.domain, args.base, args.output)


if __name__ == "__main__":
    main()
