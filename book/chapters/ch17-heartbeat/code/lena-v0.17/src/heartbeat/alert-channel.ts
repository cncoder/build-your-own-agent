/**
 * lena-v0.17 · 独立告警通道
 *
 * 设计原则（来自 Ch17 Beat 7）：
 * 告警通道必须独立于主 agent 运行时，否则主线挂了告警也跟着挂了。
 *
 * 实现要求：
 * - 独立进程（这里是独立类，可单独 import 到任何脚本）
 * - 独立 bot token（不与主 Lena bot 共享）
 * - 最小依赖（只需 Node.js 内置 https 模块）
 * - 指数退避（防止单次故障导致 Telegram 刷屏）
 */

import https from "https";

/** 指数退避时间表：1分 → 5分 → 15分 → 30分 → 1小时（此后循环最后一档） */
const BACKOFF_MS = [
  60_000,     //  1 分钟
  300_000,    //  5 分钟
  900_000,    // 15 分钟
  1_800_000,  // 30 分钟
  3_600_000,  //  1 小时
] as const;

interface AlertState {
  count:  number;  // 累计告警次数（决定下次退避档位）
  lastAt: number;  // 上次告警时间戳（ms）
}

/**
 * 独立告警通道
 *
 * 用法：
 *   const alert = new AlertChannel(watchdogBotToken, chatId);
 *
 *   // 监控循环里
 *   if (checkFailed("openclaw")) {
 *     if (alert.shouldAlert("openclaw")) {
 *       await alert.send("OpenClaw gateway 不可达");
 *     }
 *   } else {
 *     alert.resetAlert("openclaw");  // 恢复时重置退避
 *   }
 */
export class AlertChannel {
  private states = new Map<string, AlertState>();

  constructor(
    private readonly botToken: string,
    private readonly chatId:   string,
  ) {}

  /**
   * 判断是否应该发出告警（指数退避）
   * 返回 true 并更新内部计数；返回 false 表示还在退避窗口内
   */
  shouldAlert(checkId: string): boolean {
    const s    = this.states.get(checkId) ?? { count: 0, lastAt: 0 };
    const wait = BACKOFF_MS[Math.min(s.count, BACKOFF_MS.length - 1)];

    if (Date.now() - s.lastAt >= wait) {
      this.states.set(checkId, { count: s.count + 1, lastAt: Date.now() });
      return true;
    }
    return false;
  }

  /**
   * 故障恢复时重置退避状态
   * 下次再出故障会从第一档（1 分钟）重新开始
   */
  resetAlert(checkId: string): void {
    this.states.delete(checkId);
  }

  /**
   * 通过独立 Telegram bot 发送告警
   * 不经过 OpenClaw gateway，不依赖主 agent 任何代码路径
   */
  async send(message: string): Promise<void> {
    const body = JSON.stringify({
      chat_id:    this.chatId,
      text:       `🚨 ${message}`,
      parse_mode: "Markdown",
    });

    return new Promise((resolve, reject) => {
      const req = https.request(
        `https://api.telegram.org/bot${this.botToken}/sendMessage`,
        {
          method:  "POST",
          headers: {
            "Content-Type":   "application/json",
            "Content-Length": Buffer.byteLength(body),
          },
        },
        res => { res.resume(); res.on("end", resolve); }
      );
      req.on("error", reject);
      req.write(body);
      req.end();
    });
  }
}
