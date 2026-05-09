"""
lena-v2.0 Browser Agent 配置

模型选型说明（来自 Ch 4 LLM 选型原则）：
- us.anthropic.claude-sonnet-4-6：通用任务首选，多步推理质量高
- us.anthropic.claude-haiku-4-5：简单单步任务，速度快成本低
- ChatBrowserUse：browser-use 专用模型，3-5x 速度，适合固定流程

何时用 ChatBrowserUse（来自 browser-use 文档，2026-05）：
  - 任务步骤固定（导航+填表+点击序列）
  - 对速度敏感（批量任务、实时响应需求）
  - 不需要复杂推理或跨步骤判断

何时坚持用 Claude：
  - 任务目标明确但步骤不固定（"找到最便宜的"）
  - 需要理解复杂上下文（"14:00 之后且非停靠超过 2 站的"）
  - 遇到异常状态需要决策（验证码、错误页面、登录失效）
"""

# === 模型配置 ===
MODEL_DEFAULT = "us.anthropic.claude-sonnet-4-6"   # 通用任务，多步推理
MODEL_FAST = "us.anthropic.claude-haiku-4-5"       # 简单单步，成本低
# MODEL_BROWSER_SPECIALIST = "chatbrowseruse"  # 专用浏览器模型（需要 browser-use account）

# === CDP 配置 ===
CDP_HOST = "localhost"
CDP_PORT = 9222
CDP_BASE_URL = f"http://{CDP_HOST}:{CDP_PORT}"
CDP_WS_URL = f"ws://{CDP_HOST}:{CDP_PORT}"

# Chrome profile 路径（通用路径，不含个人用户名）
# 运行时通过 cdp-start.sh 启动，脚本内部处理路径
CDP_PROFILE_NAME = "abel-chrome"

# === 安全配置 ===

# 高风险操作关键词（触发人工审批门控）
HIGH_RISK_KEYWORDS = [
    # 英文
    "submit", "purchase", "buy", "order", "delete", "remove",
    "transfer", "pay", "checkout", "confirm", "book", "reserve",
    # 中文
    "提交", "购买", "支付", "删除", "转账", "预订", "确认",
    "下单", "结算", "付款",
]

# Tab 数量告警阈值（超过此数量发出警告）
TAB_COUNT_WARNING = 20
TAB_COUNT_CRITICAL = 50  # 超过此数量强制清理旧 tab

# === 任务配置 ===

# browser-use agent 的步骤限制
MAX_STEPS_DEFAULT = 25       # 常规任务
MAX_STEPS_COMPLEX = 50       # 复杂任务（订票等）

# 截图验证
MIN_SCREENSHOT_BYTES = 80 * 1024  # 小于此大小视为空白页

# 进程锁文件路径
BROWSER_LOCK_FILE = "/tmp/.lena_browser_v2.lock"

# === Fallback 配置 ===

# 各层超时设置（秒）
RSSHUB_TIMEOUT = 10
OPENCLI_TIMEOUT = 15
BROWSER_TIMEOUT = 120  # browser agent 可能需要更长时间

# RSSHub 公共实例（可替换为自建实例提高稳定性）
RSSHUB_BASE_URL = "https://rsshub.app"
