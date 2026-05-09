<template>
  <div class="roadmap">
    <div v-for="part in parts" :key="part.name" class="part">
      <div class="part-label" :style="{ '--c': part.color }">{{ part.name }}</div>
      <div class="chapters">
        <a
          v-for="ch in part.chapters"
          :key="ch.id"
          :href="ch.link"
          class="ch-node"
          :style="{ '--c': part.color }"
        >
          <span class="ch-num">{{ ch.id }}</span>
          <span class="ch-title">{{ ch.title }}</span>
        </a>
      </div>
    </div>
  </div>
</template>

<script setup>
const parts = [
  {
    name: '地基',
    color: '#00d4ff',
    chapters: [
      { id: '00', title: '聪明度地图', link: '/chapters/ch00-intelligence-map/' },
      { id: '01', title: '你好 Agent', link: '/chapters/ch01-hello-agent/' },
      { id: '02', title: 'ReAct 循环', link: '/chapters/ch02-react-loop/' },
      { id: '03', title: 'Lena 诞生', link: '/chapters/ch03-lena-is-born/' },
      { id: '04', title: 'LLM 内部', link: '/chapters/ch04-llm-internals/' },
      { id: '05', title: '技术选型', link: '/chapters/ch05-tech-selection/' },
    ]
  },
  {
    name: '核心能力',
    color: '#00ff88',
    chapters: [
      { id: '06', title: '工具系统', link: '/chapters/ch06-tool-system/' },
      { id: '07', title: '流式并发', link: '/chapters/ch07-streaming-concurrent/' },
      { id: '08', title: '记忆', link: '/chapters/ch08-memory/' },
      { id: '09', title: 'RAG', link: '/chapters/ch09-rag-vector-search/' },
      { id: '10', title: 'Context', link: '/chapters/ch10-context-engineering/' },
      { id: '11', title: '规划', link: '/chapters/ch11-planning-subagent/' },
      { id: '12', title: 'Skills', link: '/chapters/ch12-skills/' },
    ]
  },
  {
    name: '安全',
    color: '#ff4d6d',
    chapters: [
      { id: '13', title: '输入安全', link: '/chapters/ch13-input-safety/' },
      { id: '14', title: '执行安全', link: '/chapters/ch14-execution-safety/' },
    ]
  },
  {
    name: '通信',
    color: '#4d9fff',
    chapters: [
      { id: '15', title: 'Channel', link: '/chapters/ch15-gateway-channel/' },
      { id: '16', title: 'MessageBus', link: '/chapters/ch16-messagebus/' },
      { id: '17', title: 'Heartbeat', link: '/chapters/ch17-heartbeat/' },
      { id: '18', title: 'Cron', link: '/chapters/ch18-cron-longtask/' },
      { id: '19', title: 'MCP', link: '/chapters/ch19-mcp-protocol/' },
    ]
  },
  {
    name: '生产化',
    color: '#ffaa00',
    chapters: [
      { id: '20', title: 'Sandbox', link: '/chapters/ch20-docker-sandbox/' },
      { id: '21', title: 'Evals', link: '/chapters/ch21-evals/' },
      { id: '22', title: '可观测性', link: '/chapters/ch22-observability-deploy/' },
    ]
  },
  {
    name: '高级',
    color: '#b084ff',
    chapters: [
      { id: '23', title: '专用化', link: '/chapters/ch23-specialization/' },
      { id: '24', title: 'Browser', link: '/chapters/ch24-browser-agent/' },
      { id: '25', title: '从通用到专用', link: '/chapters/ch25-from-general-to-specialized/' },
    ]
  },
]
</script>

<style scoped>
.roadmap {
  display: flex;
  flex-direction: column;
  gap: 2rem;
  max-width: 900px;
  margin: 2rem auto;
}

.part {
  display: flex;
  flex-direction: column;
  gap: 0.75rem;
}

.part-label {
  font-size: 0.8rem;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.1em;
  color: var(--c);
  border-left: 3px solid var(--c);
  padding-left: 0.75rem;
}

.chapters {
  display: flex;
  flex-wrap: wrap;
  gap: 0.5rem;
  padding-left: 1rem;
}

.ch-node {
  display: inline-flex;
  align-items: center;
  gap: 0.4rem;
  padding: 0.4rem 0.8rem;
  border-radius: 6px;
  background: rgba(255,255,255,0.04);
  border: 1px solid rgba(255,255,255,0.08);
  color: var(--vp-c-text-1);
  text-decoration: none;
  font-size: 0.85rem;
  transition: all 0.15s;
}

.ch-node:hover {
  background: rgba(255,255,255,0.08);
  border-color: var(--c);
  transform: translateY(-1px);
}

.ch-num {
  font-size: 0.7rem;
  font-weight: 700;
  color: var(--c);
  opacity: 0.7;
}

.ch-title {
  color: var(--vp-c-text-1);
}

@media (max-width: 640px) {
  .chapters {
    flex-direction: column;
  }
}
</style>
