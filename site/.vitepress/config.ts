import { defineConfig } from 'vitepress'

export default defineConfig({
  title: 'Build AI Agent from Scratch',
  description: 'Build a general-purpose AI Agent Runtime with Python — 26 chapters, fully runnable',

  base: '/build-your-own-agent/',

  locales: {
    root: {
      label: '中文',
      lang: 'zh-CN',
      title: '从零构建通用 AI Agent',
      description: '用 Python 打造能自主做任何事的 Agent Runtime — 26 章 · 全程 Python · 每章可运行',
    },
    en: {
      label: 'English',
      lang: 'en-US',
      title: 'Build AI Agent from Scratch',
      description: 'Build a general-purpose AI Agent Runtime with Python — 26 chapters, fully runnable',
      themeConfig: {
        nav: [
          { text: 'Home', link: '/en/' },
          { text: 'Start Reading', link: '/en/chapters/ch00-intelligence-map/' },
          { text: 'GitHub', link: 'https://github.com/cncoder/build-your-own-agent' },
        ],
        sidebar: [
          {
            text: 'Prologue',
            items: [
              { text: 'Ch0 · Agent Intelligence Map', link: '/en/chapters/ch00-intelligence-map/' },
            ]
          },
          {
            text: 'Part 1 · Foundations (Ch01–Ch05)',
            collapsed: false,
            items: [
              { text: 'Ch1 · Hello, Agent', link: '/en/chapters/ch01-hello-agent/' },
              { text: 'Ch2 · The ReAct Loop', link: '/en/chapters/ch02-react-loop/' },
              { text: 'Ch3 · Lena is Born', link: '/en/chapters/ch03-lena-is-born/' },
              { text: 'Ch4 · LLM Internals', link: '/en/chapters/ch04-llm-internals/' },
              { text: 'Ch5 · Tech Selection', link: '/en/chapters/ch05-tech-selection/' },
            ]
          },
          {
            text: 'Part 2 · Core Capabilities (Ch06–Ch12)',
            collapsed: false,
            items: [
              { text: 'Ch6 · Tool System', link: '/en/chapters/ch06-tool-system/' },
              { text: 'Ch7 · Streaming & Concurrency', link: '/en/chapters/ch07-streaming-concurrent/' },
              { text: 'Ch8 · Memory', link: '/en/chapters/ch08-memory/' },
              { text: 'Ch9 · RAG & Vector Search', link: '/en/chapters/ch09-rag-vector-search/' },
              { text: 'Ch10 · Context Engineering', link: '/en/chapters/ch10-context-engineering/' },
              { text: 'Ch11 · Planning & Subagent', link: '/en/chapters/ch11-planning-subagent/' },
              { text: 'Ch12 · Skills', link: '/en/chapters/ch12-skills/' },
            ]
          },
          {
            text: 'Part 3 · Safety (Ch13–Ch14)',
            collapsed: true,
            items: [
              { text: 'Ch13 · Input Safety', link: '/en/chapters/ch13-input-safety/' },
              { text: 'Ch14 · Execution Safety', link: '/en/chapters/ch14-execution-safety/' },
            ]
          },
          {
            text: 'Part 4 · Communication (Ch15–Ch19)',
            collapsed: true,
            items: [
              { text: 'Ch15 · Gateway & Channel', link: '/en/chapters/ch15-gateway-channel/' },
              { text: 'Ch16 · MessageBus', link: '/en/chapters/ch16-messagebus/' },
              { text: 'Ch17 · Heartbeat', link: '/en/chapters/ch17-heartbeat/' },
              { text: 'Ch18 · Cron & Long Tasks', link: '/en/chapters/ch18-cron-longtask/' },
              { text: 'Ch19 · MCP Protocol', link: '/en/chapters/ch19-mcp-protocol/' },
            ]
          },
          {
            text: 'Part 5 · Production (Ch20–Ch22)',
            collapsed: true,
            items: [
              { text: 'Ch20 · Docker Sandbox', link: '/en/chapters/ch20-docker-sandbox/' },
              { text: 'Ch21 · Evals', link: '/en/chapters/ch21-evals/' },
              { text: 'Ch22 · Observability & Deploy', link: '/en/chapters/ch22-observability-deploy/' },
            ]
          },
          {
            text: 'Part 6 · Advanced (Ch23–Ch25)',
            collapsed: true,
            items: [
              { text: 'Ch23 · Specialization', link: '/en/chapters/ch23-specialization/' },
              { text: 'Ch24 · Browser Agent', link: '/en/chapters/ch24-browser-agent/' },
              { text: 'Ch25 · From General to Yours', link: '/en/chapters/ch25-from-general-to-specialized/' },
            ]
          },
        ],
      },
    },
  },

  // 强制深色模式
  appearance: 'dark',

  // 章节 README 内的相对链接指向其他章节/README，构建时忽略
  ignoreDeadLinks: true,

  // 排除 slides/code/diagrams 等子目录下的 md（含 HTML 标签会导致 Vue 编译报错）
  srcExclude: [
    '**/slides/**/*.md',
    '**/code/**/*.md',
    '**/diagrams/**/*.md',
    '**/infographic/**/*.md',
    '**/images/**/*.md',
    '**/fact-check.md',
    '**/review.md',
    '**/ppt.md',
    '**/podcast.md',
    '**/README.v1-discarded.md',
  ],

  head: [
    ['meta', { name: 'theme-color', content: '#00d4ff' }],
    ['meta', { name: 'viewport', content: 'width=device-width, initial-scale=1.0' }],
  ],

  themeConfig: {
    logo: { light: '/logo.png', dark: '/logo.png', alt: '从零构建通用 AI Agent' },

    nav: [
      { text: '首页', link: '/' },
      { text: '开始阅读', link: '/chapters/ch00-intelligence-map/' },
      { text: 'GitHub', link: 'https://github.com/cncoder/build-your-own-agent' },
    ],

    // 本地全文搜索
    search: {
      provider: 'local',
      options: {
        locales: {
          root: {
            translations: {
              button: { buttonText: '搜索文档', buttonAriaLabel: '搜索文档' },
              modal: {
                noResultsText: '无法找到相关结果',
                resetButtonTitle: '清除查询条件',
                footer: {
                  selectText: '选择',
                  navigateText: '切换',
                  closeText: '关闭',
                }
              }
            }
          }
        }
      }
    },

    sidebar: [
      {
        text: '序章',
        items: [
          { text: 'Ch0 · Agent 聪明度地图', link: '/chapters/ch00-intelligence-map/' },
        ]
      },
      {
        text: 'Part 1 · 地基（Ch01–Ch05）',
        collapsed: false,
        items: [
          { text: 'Ch1 · 你好，Agent', link: '/chapters/ch01-hello-agent/' },
          { text: 'Ch2 · ReAct 循环原理', link: '/chapters/ch02-react-loop/' },
          { text: 'Ch3 · Lena 诞生', link: '/chapters/ch03-lena-is-born/' },
          { text: 'Ch4 · LLM 底层速查', link: '/chapters/ch04-llm-internals/' },
          { text: 'Ch5 · 技术选型', link: '/chapters/ch05-tech-selection/' },
        ]
      },
      {
        text: 'Part 2 · 核心能力（Ch06–Ch12）',
        collapsed: false,
        items: [
          { text: 'Ch6 · 工具系统', link: '/chapters/ch06-tool-system/' },
          { text: 'Ch7 · 流式与并发', link: '/chapters/ch07-streaming-concurrent/' },
          { text: 'Ch8 · 记忆', link: '/chapters/ch08-memory/' },
          { text: 'Ch9 · RAG 与向量检索', link: '/chapters/ch09-rag-vector-search/' },
          { text: 'Ch10 · Context Engineering', link: '/chapters/ch10-context-engineering/' },
          { text: 'Ch11 · 规划与子 Agent', link: '/chapters/ch11-planning-subagent/' },
          { text: 'Ch12 · Skills', link: '/chapters/ch12-skills/' },
        ]
      },
      {
        text: 'Part 3 · 安全（Ch13–Ch14）',
        collapsed: true,
        items: [
          { text: 'Ch13 · 输入安全', link: '/chapters/ch13-input-safety/' },
          { text: 'Ch14 · 执行安全', link: '/chapters/ch14-execution-safety/' },
        ]
      },
      {
        text: 'Part 4 · 通信（Ch15–Ch19）',
        collapsed: true,
        items: [
          { text: 'Ch15 · 网关与 Channel', link: '/chapters/ch15-gateway-channel/' },
          { text: 'Ch16 · MessageBus', link: '/chapters/ch16-messagebus/' },
          { text: 'Ch17 · Heartbeat 常驻', link: '/chapters/ch17-heartbeat/' },
          { text: 'Ch18 · Cron 长任务', link: '/chapters/ch18-cron-longtask/' },
          { text: 'Ch19 · MCP 协议', link: '/chapters/ch19-mcp-protocol/' },
        ]
      },
      {
        text: 'Part 5 · 生产化（Ch20–Ch22）',
        collapsed: true,
        items: [
          { text: 'Ch20 · Docker Sandbox', link: '/chapters/ch20-docker-sandbox/' },
          { text: 'Ch21 · Evals', link: '/chapters/ch21-evals/' },
          { text: 'Ch22 · 可观测性与部署', link: '/chapters/ch22-observability-deploy/' },
        ]
      },
      {
        text: 'Part 6 · 高级特性（Ch23–Ch25）',
        collapsed: true,
        items: [
          { text: 'Ch23 · 专用化', link: '/chapters/ch23-specialization/' },
          { text: 'Ch24 · Browser Agent', link: '/chapters/ch24-browser-agent/' },
          { text: 'Ch25 · 从通用到你的 Agent', link: '/chapters/ch25-from-general-to-specialized/' },
        ]
      },
    ],

    footer: {
      message: '构建通用 Agent Runtime，从这里开始',
      copyright: '© 2026 · CC BY-NC-ND 4.0'
    },

    editLink: {
      pattern: 'https://github.com/cncoder/build-your-own-agent/edit/main/:path',
      text: '在 GitHub 上编辑此页'
    },

    lastUpdated: {
      text: '最后更新',
    },

    docFooter: {
      prev: '上一章',
      next: '下一章'
    },

    outline: {
      label: '本章目录',
      level: [2, 3]
    },

    darkModeSwitchLabel: '外观',
    sidebarMenuLabel: '菜单',
    returnToTopLabel: '回到顶部',
  },
})
