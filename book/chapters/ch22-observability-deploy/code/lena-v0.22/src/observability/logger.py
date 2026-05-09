"""结构化日志配置。

Convention：
  - 开发模式：ConsoleRenderer（彩色可读）
  - 生产模式：JSONRenderer（每行一个 JSON，可被 jq / CloudWatch / ELK 直接处理）

用法：
    from lena.observability.logger import setup_logging
    import structlog

    setup_logging(json_output=True)  # 生产模式
    log = structlog.get_logger(__name__)
    log.info("agent_start", session_id="sess_abc", model="claude-sonnet-4-6")
"""
import logging
import os
import sys

import structlog  # pip install structlog>=24.0


def setup_logging(
    level: str | None = None,
    json_output: bool | None = None,
) -> None:
    """初始化结构化日志。调用一次，全局生效。

    Args:
        level: 日志级别，默认从 LOG_LEVEL 环境变量读取，缺省 INFO
        json_output: True = JSON 生产模式，False = Console 开发模式
                     默认从 LOG_FORMAT 环境变量读取（"json" = True）
    """
    if level is None:
        level = os.environ.get("LOG_LEVEL", "INFO").upper()
    if json_output is None:
        json_output = os.environ.get("LOG_FORMAT", "console").lower() == "json"

    shared_processors = [
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
    ]

    if json_output:
        shared_processors.append(structlog.processors.JSONRenderer())
    else:
        shared_processors.append(structlog.dev.ConsoleRenderer())

    structlog.configure(
        processors=shared_processors,
        wrapper_class=structlog.make_filtering_bound_logger(
            logging.getLevelName(level)
        ),
        logger_factory=structlog.PrintLoggerFactory(sys.stdout),
    )
