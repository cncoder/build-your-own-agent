"""
lena-spec CLI 入口

用法：
  python -m spec_kit.cli create trader --role "crypto trader" --template trading
  python -m spec_kit.cli fork --name NewsBot --from ~/.openclaw/agents/main --tools collect_news,send_message
  python -m spec_kit.cli list
  python -m spec_kit.cli test trader
"""

from __future__ import annotations

import json
from pathlib import Path

import click
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.text import Text

from .creator import create_agent, TOOL_PROFILES
from .forker import fork_agent

console = Console()


@click.group()
def cli():
    """Lena-SpecKit：一行命令从通用 Lena 派生专用 agent。"""


@cli.command()
@click.argument("name")
@click.option("--role", "-r", required=True, help='agent 角色描述，如 "crypto trader"')
@click.option(
    "--template",
    "-t",
    default="trading",
    type=click.Choice(["trading", "podcaster", "devops"]),
    show_default=True,
    help="使用哪个模板",
)
@click.option("--output-dir", "-o", default=None, help="输出目录（默认 ./agents/{name}）")
def create(name: str, role: str, template: str, output_dir: str | None):
    """创建新专用 agent（三种派生姿势全部应用）。"""
    out = Path(output_dir) if output_dir else None

    console.print(f"\n[cyan]创建专用 agent：[bold]{name}[/bold][/cyan]")
    console.print(f"  角色：{role}")
    console.print(f"  模板：{template}")

    agent_dir = create_agent(name=name, role=role, template=template, output_dir=out)

    tools = TOOL_PROFILES.get(template, [])
    console.print(f"\n[green]✓[/green] 创建成功：[bold]{agent_dir}[/bold]")
    console.print(f"[green]✓[/green] system prompt: {agent_dir}/system_prompt.md")
    console.print(f"[green]✓[/green] 工具集 ({len(tools)} 个): {agent_dir}/tool_profile.json")
    console.print(f"[green]✓[/green] skills: {agent_dir}/skills/{template}-sop.md")
    console.print(f"[green]✓[/green] config: {agent_dir}/config.json")

    console.print(
        Panel(
            Text.from_markup(
                f"[bold]下一步：[/bold]\n"
                f"  1. 编辑 [cyan]{agent_dir}/config.json[/cyan] 填入 API 密钥\n"
                f"  2. [cyan]python -m spec_kit.cli test {name}[/cyan]\n"
                f"  3. [cyan]python -m spec_kit.cli deploy {name}[/cyan]"
            ),
            title="快速启动",
            border_style="green",
        )
    )


@cli.command("fork")
@click.option("--name", "-n", required=True, help="新 agent 名称")
@click.option("--from", "source", required=True, help="源 agent 目录")
@click.option("--tools", "-t", default=None, help="保留的工具（逗号分隔）")
@click.option("--extra-prompt", "-p", default="", help="追加到 system prompt 的专用内容")
@click.option("--output-dir", "-o", default=None, help="输出目录")
def fork(name: str, source: str, tools: str | None, extra_prompt: str, output_dir: str | None):
    """从现有 agent 派生新专用 agent（继承 system prompt + skills）。"""
    source_path = Path(source).expanduser()
    if not source_path.exists():
        console.print(f"[red]错误：源 agent 目录不存在：{source_path}[/red]")
        raise SystemExit(1)

    tool_list = [t.strip() for t in tools.split(",")] if tools else None
    out = Path(output_dir) if output_dir else None

    console.print(f"\n[cyan]Fork 派生：[bold]{name}[/bold][/cyan]")
    console.print(f"  来源：{source_path}")
    if tool_list:
        console.print(f"  保留工具：{', '.join(tool_list)}")

    agent_dir = fork_agent(
        name=name,
        source_dir=source_path,
        tools=tool_list,
        extra_prompt=extra_prompt,
        output_dir=out,
    )

    console.print(f"\n[green]✓[/green] Fork 成功：[bold]{agent_dir}[/bold]")


@cli.command("list")
def list_agents():
    """列出已创建的专用 agent。"""
    agents_dir = Path("agents")
    if not agents_dir.exists():
        console.print("[yellow]还没有创建任何专用 agent。运行 create 命令开始吧。[/yellow]")
        return

    table = Table(title="已创建的专用 agent", border_style="cyan")
    table.add_column("名称", style="bold white")
    table.add_column("角色")
    table.add_column("模板")
    table.add_column("工具数")
    table.add_column("目录")

    for agent_dir in sorted(agents_dir.iterdir()):
        if not agent_dir.is_dir():
            continue
        config_path = agent_dir / "config.json"
        if not config_path.exists():
            continue
        config = json.loads(config_path.read_text(encoding="utf-8"))
        tools_path = agent_dir / "tool_profile.json"
        tool_count = "?"
        if tools_path.exists():
            tool_config = json.loads(tools_path.read_text(encoding="utf-8"))
            tool_count = str(len(tool_config.get("tools", [])))
        table.add_row(
            config.get("agent_name", agent_dir.name),
            config.get("role", "-"),
            config.get("template", config.get("forked_from", "-")),
            tool_count,
            str(agent_dir),
        )

    console.print(table)


@cli.command("test")
@click.argument("name")
def test(name: str):
    """测试专用 agent（发送一条 ping 消息验证配置）。"""
    agent_dir = Path(f"agents/{name}")
    if not agent_dir.exists():
        console.print(f"[red]错误：agent '{name}' 不存在，先运行 create 命令。[/red]")
        raise SystemExit(1)

    config_path = agent_dir / "config.json"
    config = json.loads(config_path.read_text(encoding="utf-8"))
    system_prompt = (agent_dir / "system_prompt.md").read_text(encoding="utf-8")

    console.print(f"\n[cyan]测试 agent：{name}[/cyan]")
    console.print(f"  模型：{config.get('model', 'unknown')}")
    console.print(f"  system prompt 长度：{len(system_prompt)} 字符")

    import os
    import boto3
    bedrock = boto3.client("bedrock-runtime", region_name=os.getenv("AWS_REGION", "us-west-2"))
    resp = bedrock.converse(
        modelId=config.get("model", "us.anthropic.claude-sonnet-4-6"),
        system=[{"text": system_prompt}],
        messages=[{"role": "user", "content": [{"text": "你是谁？请用一句话介绍自己。"}]}],
        inferenceConfig={"maxTokens": 256},
    )

    reply = resp["output"]["message"]["content"][0]["text"]
    console.print(f"\n[green]✓ 测试成功[/green]")
    console.print(Panel(reply, title=f"{name} 自我介绍", border_style="green"))


@cli.command("deploy")
@click.argument("name")
def deploy(name: str):
    """部署专用 agent（注册为 OpenClaw cron 任务）。"""
    agent_dir = Path(f"agents/{name}")
    if not agent_dir.exists():
        console.print(f"[red]错误：agent '{name}' 不存在。[/red]")
        raise SystemExit(1)

    config = json.loads((agent_dir / "config.json").read_text(encoding="utf-8"))
    console.print(f"\n[cyan]部署 agent：{name}[/cyan]")
    console.print(
        Panel(
            f"[yellow]请手动将以下配置添加到 ~/.openclaw/cron/jobs.json：[/yellow]\n\n"
            f"```json\n"
            f'{{\n  "id": "{name}-agent",\n  "name": "{config.get("agent_name", name)}",\n'
            f'  "schedule": "0 * * * *",\n'
            f'  "command": "python -m examples.{name}_bot",\n'
            f'  "timeout": 3600\n}}\n```',
            title="部署说明",
            border_style="yellow",
        )
    )


def main():
    cli()


if __name__ == "__main__":
    main()
