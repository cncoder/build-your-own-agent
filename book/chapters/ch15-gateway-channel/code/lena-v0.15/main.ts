/**
 * Lena v0.15 — 常驻 Gateway + Telegram/Console 双 channel
 *
 * 启动方式：
 *   npm start                         # 纯 Console 模式
 *   TELEGRAM_BOT_TOKEN=<token> npm start   # + Telegram
 *   TELEGRAM_BOT_TOKEN=<token> TELEGRAM_ALLOW_FROM=<user-id> npm start
 *
 * 验证方式：
 *   Console:  直接在 terminal 输入
 *   HTTP:     curl -X POST http://localhost:3000/message -d '{"content":"你好"}'
 *   Status:   curl http://localhost:3000/status
 *   WebSocket: ws://localhost:8765?id=my-client
 */
import { GatewayServer } from "./gateway/server";
import { AgentLoop }      from "./agent/loop";
import { ConsoleChannel } from "./channels/console";
import { TelegramChannel } from "./channels/telegram";

async function main() {
  const agent   = new AgentLoop();
  const gateway = new GatewayServer(agent);

  // Console channel：本地调试，零依赖，始终注册
  gateway.register(new ConsoleChannel());

  // Telegram channel：只在配置了 token 时才注册
  const token     = process.env.TELEGRAM_BOT_TOKEN;
  const allowFrom = (process.env.TELEGRAM_ALLOW_FROM ?? "*").split(",").map(s => s.trim());
  if (token) {
    gateway.register(new TelegramChannel(token, allowFrom));
    console.log(`[Main] Telegram channel 已配置，allowFrom: ${allowFrom.join(", ")}`);
  } else {
    console.log("[Main] 未配置 TELEGRAM_BOT_TOKEN，跳过 Telegram channel");
  }

  await gateway.start();

  console.log("\n✓ Lena v0.15 已启动");
  console.log("  WebSocket: ws://localhost:8765");
  console.log("  HTTP POST: http://localhost:3000/message");
  console.log("  Status:    http://localhost:3000/status\n");

  // 优雅退出
  process.on("SIGINT", async () => {
    console.log("\n[Main] 正在停止...");
    await gateway.stop();
    process.exit(0);
  });
}

main().catch((err) => {
  console.error("启动失败:", err);
  process.exit(1);
});
