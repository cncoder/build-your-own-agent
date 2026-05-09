"""
Lena-SpecKit: 一行命令从通用 Lena 派生专用 agent 的脚手架。

三种派生姿势：
  ① system prompt 特化
  ② 工具集裁剪
  ③ skills 注入

用法：
  lena-spec create trader --role "crypto trader" --template trading
  lena-spec fork --name NewsBot --from ~/.openclaw/agents/main --tools "collect_news,send_message"
  lena-spec deploy trader
"""
__version__ = "1.9.0"
