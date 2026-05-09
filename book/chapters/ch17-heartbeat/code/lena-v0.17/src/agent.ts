/**
 * lena-v0.17 · 主入口
 *
 * 本章产物：Lena 每天 08:00 主动发 Telegram 早报
 * 在 v0.16（MessageBus + Channel 插拔）基础上增加 Heartbeat
 *
 * 运行方式：
 *   npm run dev                   # 开发模式（tsx 直接运行）
 *   npm run build && npm start    # 生产模式
 *
 * 测试技巧：把 config.json 里 intervalMs 改为 10000，
 *           activeHours.weekdays.start 改为当前小时，
 *           10 秒后即可收到 Telegram 消息验证整个链路。
 */

import { HeartbeatRunner, OutboundPayload } from "./heartbeat/index.js";
import https from "https";
import fs    from "fs";
import path  from "path";
import { fileURLToPath } from "url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));

// ─── 配置加载 ─────────────────────────────────────────────────────────────────

interface LenaConfig {
  agent: {
    id:   string;
    name: string;
  };
  heartbeat: {
    intervalMs:  number;
    activeHours: {
      timezone: string;
      weekdays: { start: number; end: number };
      weekend?: { start: number; end: number };
    };
  };
  telegram: {
    botToken: string;
    chatId:   string;
  };
  alertChannel: {
    botToken: string;
    chatId:   string;
  };
}

function loadConfig(): LenaConfig {
  const configPath = path.join(__dirname, "..", "config.json");
  const raw = fs.readFileSync(configPath, "utf-8");
  return JSON.parse(raw) as LenaConfig;
}

// ─── Telegram 推送 ─────────────────────────────────────────────────────────────

/**
 * 直接调用 Telegram HTTP API，不走 OpenClaw gateway
 * 保证即使 gateway 挂了，推送仍然能发出
 */
async function sendTelegram(
  token:  string,
  chatId: string,
  text:   string,
): Promise<void> {
  const body = JSON.stringify({ chat_id: chatId, text, parse_mode: "Markdown" });

  return new Promise((resolve, reject) => {
    const req = https.request(
      `https://api.telegram.org/bot${token}/sendMessage`,
      {
        method:  "POST",
        headers: {
          "Content-Type":   "application/json",
          "Content-Length": Buffer.byteLength(body),
        },
      },
      res => {
        res.resume();
        res.on("end", () => {
          console.log(`[Telegram] sent (status=${res.statusCode})`);
          resolve();
        });
      }
    );
    req.on("error", reject);
    req.write(body);
    req.end();
  });
}

// ─── 早报生成器 ────────────────────────────────────────────────────────────────

/**
 * 生成早报内容
 *
 * 当前版本：简单的日期问候
 * 生产扩展：在这里接入 Anthropic API，拉取日历/新闻/天气后生成摘要
 */
function buildMorningBriefing(agentName: string): string {
  const now  = new Date();
  const hour = now.getHours();

  let greeting = "你好";
  if (hour >= 5  && hour < 12) greeting = "早上好";
  if (hour >= 12 && hour < 18) greeting = "下午好";
  if (hour >= 18)              greeting = "晚上好";

  const dateStr = now.toLocaleDateString("zh-CN", {
    year: "numeric", month: "long", day: "numeric", weekday: "long",
  });

  return (
    `${greeting}！今天是 ${dateStr}。\n\n` +
    `我是 ${agentName}，有什么需要我帮忙的吗？`
  );
}

// ─── 主程序 ───────────────────────────────────────────────────────────────────

async function main(): Promise<void> {
  const config = loadConfig();

  console.log(`[Lena v0.17] starting — agent=${config.agent.name}`);

  // 创建 HeartbeatRunner，注入早报生成器
  const runner = new HeartbeatRunner(
    {
      intervalMs:  config.heartbeat.intervalMs,
      activeHours: config.heartbeat.activeHours,
      agentId:     config.agent.id,
      channelId:   "telegram",
    },
    async () => buildMorningBriefing(config.agent.name),
  );

  // 监听 outbound 事件 → 推送到 Telegram
  runner.on("outbound", async (payload: OutboundPayload) => {
    try {
      await sendTelegram(
        config.telegram.botToken,
        config.telegram.chatId,
        payload.content,
      );
    } catch (err) {
      // 主通道失败时，尝试通过独立告警通道通知
      console.error("[Lena] Telegram send failed:", err);
      try {
        await sendTelegram(
          config.alertChannel.botToken,
          config.alertChannel.chatId,
          `⚠️ Heartbeat 推送失败: ${String(err)}`,
        );
      } catch {
        // 告警通道也失败了，只记录日志，不抛出（守护进程不能因此崩溃）
        console.error("[Lena] alert channel also failed");
      }
    }
  });

  runner.on("tick", (skipped: boolean) => {
    if (skipped) {
      console.log("[Lena] tick — outside active hours, waiting...");
    }
  });

  // 启动
  runner.start();

  // 优雅退出：Ctrl+C 时停止 timer 再退出
  process.on("SIGINT", () => {
    runner.stop();
    process.exit(0);
  });
}

main().catch(err => {
  console.error("[Lena] fatal error:", err);
  process.exit(1);
});
