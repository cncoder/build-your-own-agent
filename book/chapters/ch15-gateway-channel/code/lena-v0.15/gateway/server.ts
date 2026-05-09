/**
 * GatewayServer — WebSocket + HTTP 双入口消息枢纽
 *
 * 职责：
 *   1. 维护 WebSocket 连接表
 *   2. 提供 HTTP /message 和 /status 端点
 *   3. 连接所有注册的 channel，注入 AgentLoop handler
 *
 * 不包含：对话历史（属于 AgentLoop）、channel 协议细节（属于各 channel）
 */
import { WebSocketServer, WebSocket } from "ws";
import * as http from "http";
import type { AgentLoop } from "../agent/loop";
import type { BaseChannel } from "../channels/base";

export class GatewayServer {
  private channels: BaseChannel[] = [];
  private wss?: WebSocketServer;
  private httpServer?: http.Server;
  private wsConns = new Map<string, WebSocket>();

  constructor(private readonly agent: AgentLoop) {}

  /** 注册 channel：运行时调用，不修改 GatewayServer 源码 */
  register(ch: BaseChannel) {
    this.channels.push(ch);
  }

  async start(wsPort = 8765, httpPort = 3000) {
    // 1. WebSocket 服务器（给 Web 客户端 / 内部调试用）
    this.wss = new WebSocketServer({ port: wsPort });
    this.wss.on("connection", (ws, req) => this.handleWs(ws, req));
    console.log(`[Gateway] WebSocket :${wsPort}`);

    // 2. HTTP 服务器（给 webhook / curl 测试 / /status 端点）
    this.httpServer = http.createServer((req, res) => this.handleHttp(req, res));
    this.httpServer.listen(httpPort);
    console.log(`[Gateway] HTTP :${httpPort}`);

    // 3. 连接所有已注册的 channel
    for (const ch of this.channels) {
      ch.onMessage(async (userId, content) => {
        return await this.agent.run(content);
      });
      // connect() 带退避重连，不 await 以免阻塞其他 channel 启动
      void ch.connect().catch((err) => {
        console.error(`[Gateway] Channel [${ch.id}] failed: ${String(err)}`);
      });
      console.log(`[Gateway] Channel [${ch.id}] started`);
    }
  }

  private handleWs(ws: WebSocket, req: http.IncomingMessage) {
    const url    = new URL(req.url ?? "/", "http://localhost");
    const connId = url.searchParams.get("id") ?? Math.random().toString(36).slice(2);
    this.wsConns.set(connId, ws);

    ws.on("message", async (data) => {
      try {
        const { content } = JSON.parse(data.toString()) as { content: string };
        const reply = await this.agent.run(content);
        ws.send(JSON.stringify({ type: "response", content: reply }));
      } catch (err) {
        ws.send(JSON.stringify({ type: "error", message: String(err) }));
      }
    });

    ws.on("close", () => this.wsConns.delete(connId));
  }

  private handleHttp(req: http.IncomingMessage, res: http.ServerResponse) {
    if (req.method === "POST" && req.url === "/message") {
      let body = "";
      req.on("data", (chunk) => { body += String(chunk); });
      req.on("end", async () => {
        try {
          const { content } = JSON.parse(body) as { content: string };
          const reply = await this.agent.run(content);
          res.writeHead(200, { "Content-Type": "application/json" });
          res.end(JSON.stringify({ reply }));
        } catch (err) {
          res.writeHead(400, { "Content-Type": "application/json" });
          res.end(JSON.stringify({ error: String(err) }));
        }
      });
      return;
    }

    if (req.method === "GET" && req.url === "/status") {
      const snapshot = {
        channels: this.channels.map((ch) => ch.snapshot()),
        wsConnections: this.wsConns.size,
        uptime: process.uptime(),
      };
      res.writeHead(200, { "Content-Type": "application/json" });
      res.end(JSON.stringify(snapshot, null, 2));
      return;
    }

    res.writeHead(404);
    res.end("Not Found");
  }

  async stop() {
    for (const ch of this.channels) {
      await ch.disconnect().catch(() => {});
    }
    this.wss?.close();
    this.httpServer?.close();
  }
}
