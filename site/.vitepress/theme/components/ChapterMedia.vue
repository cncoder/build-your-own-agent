<template>
  <div class="chapter-media">
    <!-- Tab 切换导航 -->
    <div class="chapter-tabs">
      <button
        v-for="tab in availableTabs"
        :key="tab.id"
        class="chapter-tab"
        :class="{ 'chapter-tab--active': activeTab === tab.id }"
        @click="activeTab = tab.id"
      >
        <span class="chapter-tab__icon">{{ tab.icon }}</span>
        <span class="chapter-tab__label">{{ tab.label }}</span>
      </button>
    </div>

    <!-- 播客面板 -->
    <div v-if="activeTab === 'audio' && audioSrc" class="panel panel--audio">
      <div class="panel__header">
        <span>🎙️ 播客版 · 边读边听</span>
        <span class="panel__badge">通勤可听</span>
      </div>
      <div class="audio-player-wrap">
        <audio :src="audioSrc" controls preload="metadata" class="audio-full" />
        <p class="audio-tip">💡 建议：用播客版配合文字版一起学习，通勤/散步时收听效果极佳</p>
      </div>
    </div>

    <!-- 视频面板 -->
    <div v-if="activeTab === 'video' && videoSrc" class="panel panel--video">
      <div class="panel__header">
        <span>🎬 视频版 · PPT + 配音</span>
        <span class="panel__badge">可视化讲解</span>
      </div>
      <div class="video-wrap">
        <video :src="videoSrc" controls preload="metadata" class="video-player">
          您的浏览器不支持视频播放
        </video>
      </div>
    </div>

    <!-- Slides/PPT 面板 -->
    <div v-if="activeTab === 'slides' && slidesSrc" class="panel panel--slides">
      <div class="panel__header">
        <span>📊 Slides · 架构图可视化</span>
        <span class="panel__badge">分层动态图</span>
      </div>
      <div class="slides-wrap">
        <div class="slides-stage" ref="slidesStage">
          <iframe
            :src="slidesSrc"
            class="slides-iframe"
            frameborder="0"
            allowfullscreen
            title="章节 Slides"
          />
        </div>
        <a :href="slidesSrc" target="_blank" class="open-new-tab">在新标签页打开 ↗</a>
      </div>
    </div>

    <!-- 交互 Demo 面板 -->
    <div v-if="activeTab === 'demo' && demoSrc" class="panel panel--demo">
      <div class="panel__header">
        <span>🎨 交互 Demo · 无需 API Key</span>
        <button class="panel__badge panel__badge--btn" @click="showQR = true">扫码可玩</button>
      </div>
      <div class="demo-wrap">
        <iframe
          :src="demoSrc"
          class="demo-iframe"
          frameborder="0"
          :title="`${chapterTitle} 交互演示`"
          sandbox="allow-scripts allow-same-origin"
        />
        <a :href="demoSrc" target="_blank" class="open-new-tab">全屏体验 ↗</a>
      </div>
    </div>

    <!-- 二维码弹窗 -->
    <div v-if="showQR" class="qr-overlay" @click.self="showQR = false">
      <div class="qr-modal">
        <button class="qr-close" @click="showQR = false" aria-label="关闭">×</button>
        <div class="qr-title">📱 扫码在手机上打开 Demo</div>
        <img :src="qrImageUrl" class="qr-image" alt="Demo 二维码" />
        <div class="qr-url">{{ absoluteDemoUrl }}</div>
        <div class="qr-tip">无需 API Key · 无需登录 · 即扫即玩</div>
      </div>
    </div>

    <!-- 代码面板 -->
    <div v-if="activeTab === 'code'" class="panel panel--code">
      <div class="panel__header">
        <span>🧩 Lena 演进代码</span>
        <span class="panel__badge">{{ codeVersion }}</span>
      </div>
      <div class="code-links">
        <div v-if="codeFiles && codeFiles.length > 0" class="code-file-list">
          <div v-for="file in codeFiles" :key="file.name" class="code-file-item">
            <span class="code-file__icon">📄</span>
            <a :href="file.url" target="_blank" class="code-file__name">{{ file.name }}</a>
            <span class="code-file__desc">{{ file.desc }}</span>
          </div>
        </div>
        <div v-else class="code-placeholder">
          <p>📦 本章代码已内嵌在正文中</p>
          <p class="text-muted">请向上滚动查看代码片段</p>
        </div>
        <a v-if="githubLink" :href="githubLink" target="_blank" class="github-btn">
          <span>⬛</span> 在 GitHub 上查看完整代码
        </a>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, onBeforeUnmount, watch, nextTick } from 'vue'

interface CodeFile {
  name: string
  url: string
  desc: string
}

const props = defineProps<{
  chapterTitle?: string
  audioSrc?: string
  videoSrc?: string
  slidesSrc?: string
  demoSrc?: string
  codeVersion?: string
  codeFiles?: CodeFile[]
  githubLink?: string
}>()

const allTabs = [
  { id: 'audio', icon: '🎙️', label: '播客' },
  { id: 'video', icon: '🎬', label: '视频' },
  { id: 'slides', icon: '📊', label: 'Slides' },
  { id: 'demo', icon: '🎨', label: 'Demo' },
  { id: 'code', icon: '🧩', label: '代码' },
]

const availableTabs = computed(() => allTabs.filter(tab => {
  if (tab.id === 'audio') return !!props.audioSrc
  if (tab.id === 'video') return !!props.videoSrc
  if (tab.id === 'slides') return !!props.slidesSrc
  if (tab.id === 'demo') return !!props.demoSrc
  if (tab.id === 'code') return true // 代码面板永远显示
  return false
}))

const activeTab = ref(availableTabs.value[0]?.id || 'code')

// QR modal for demo
const showQR = ref(false)
const absoluteDemoUrl = computed(() => {
  if (!props.demoSrc) return ''
  if (typeof window === 'undefined') return props.demoSrc
  return new URL(props.demoSrc, window.location.href).href
})
const qrImageUrl = computed(() =>
  `https://api.qrserver.com/v1/create-qr-code/?size=320x320&margin=8&data=${encodeURIComponent(absoluteDemoUrl.value)}`
)

// Scale 1920×1080 slides to fit the current stage width
const slidesStage = ref<HTMLDivElement | null>(null)
let ro: ResizeObserver | null = null

function applyScale() {
  const el = slidesStage.value
  if (!el) return
  const scale = el.clientWidth / 1920
  el.style.setProperty('--slides-scale', String(scale))
}

onMounted(() => {
  if (typeof ResizeObserver !== 'undefined') {
    ro = new ResizeObserver(applyScale)
  }
})

watch(activeTab, async (tab) => {
  await nextTick()
  const el = slidesStage.value
  if (tab === 'slides' && el) {
    applyScale()
    ro?.observe(el)
  } else if (ro && el) {
    ro.unobserve(el)
  }
}, { immediate: true })

onBeforeUnmount(() => { ro?.disconnect() })
</script>

<style scoped>
.chapter-media {
  margin: 2.5rem 0;
  border-radius: 16px;
  overflow: hidden;
  border: 1px solid rgba(0, 212, 255, 0.15);
  background: rgba(8, 13, 24, 0.6);
  backdrop-filter: blur(10px);
}

/* Tab 导航 */
.chapter-tabs {
  display: flex;
  gap: 0;
  border-bottom: 1px solid rgba(0, 212, 255, 0.12);
  background: rgba(0, 212, 255, 0.04);
  overflow-x: auto;
  scrollbar-width: none;
}

.chapter-tabs::-webkit-scrollbar { display: none; }

.chapter-tab {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 12px 18px;
  background: none;
  border: none;
  border-bottom: 2px solid transparent;
  color: #64748b;
  cursor: pointer;
  font-size: 0.85rem;
  font-weight: 500;
  white-space: nowrap;
  transition: all 0.2s;
}

.chapter-tab:hover {
  color: #94a3b8;
  background: rgba(0, 212, 255, 0.04);
}

.chapter-tab--active {
  color: #00d4ff !important;
  border-bottom-color: #00d4ff;
  background: rgba(0, 212, 255, 0.08) !important;
}

.chapter-tab__icon { font-size: 1rem; }

/* Panel 通用 */
.panel { padding: 0; }

.panel__header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 12px 20px;
  background: rgba(0, 212, 255, 0.06);
  border-bottom: 1px solid rgba(0, 212, 255, 0.08);
  color: #94a3b8;
  font-size: 0.85rem;
}

.panel__badge {
  padding: 3px 10px;
  background: rgba(0, 212, 255, 0.1);
  border: 1px solid rgba(0, 212, 255, 0.2);
  border-radius: 20px;
  color: #00d4ff;
  font-size: 0.75rem;
}

/* 音频面板 */
.audio-player-wrap {
  padding: 24px;
}

.audio-full {
  width: 100%;
  border-radius: 8px;
  accent-color: #00d4ff;
  margin-bottom: 16px;
}

.audio-tip {
  color: #475569;
  font-size: 0.8rem;
  line-height: 1.6;
  margin: 0;
  padding: 12px 16px;
  background: rgba(0, 212, 255, 0.03);
  border-radius: 8px;
  border: 1px solid rgba(0, 212, 255, 0.06);
}

/* 视频面板 */
.video-wrap {
  padding: 20px;
}

.video-player {
  width: 100%;
  border-radius: 10px;
  background: #000;
  max-height: 480px;
}

/* Slides 面板 — 1920×1080 固定画布等比缩放 */
.slides-wrap {
  position: relative;
}

.slides-stage {
  position: relative;
  width: 100%;
  aspect-ratio: 16 / 9;
  overflow: hidden;
  background: #0d1117;
}

.slides-iframe {
  position: absolute;
  top: 0;
  left: 0;
  width: 1920px;
  height: 1080px;
  transform-origin: top left;
  transform: scale(var(--slides-scale, 1));
  border: none;
  display: block;
}

/* Demo 面板 */
.demo-wrap {
  position: relative;
}

.demo-iframe {
  width: 100%;
  height: 600px;
  display: block;
  background: #fff;
}

/* 通用辅助 */
.open-new-tab {
  display: block;
  text-align: right;
  padding: 8px 16px;
  color: #00d4ff;
  font-size: 0.78rem;
  text-decoration: none;
  background: rgba(0, 212, 255, 0.04);
  border-top: 1px solid rgba(0, 212, 255, 0.08);
  transition: color 0.2s;
}

.open-new-tab:hover { color: #00ffd1; }

/* 代码面板 */
.code-links {
  padding: 20px;
}

.code-file-list {
  margin-bottom: 16px;
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.code-file-item {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 10px 14px;
  background: rgba(0, 212, 255, 0.04);
  border: 1px solid rgba(0, 212, 255, 0.08);
  border-radius: 8px;
  transition: all 0.2s;
}

.code-file-item:hover {
  background: rgba(0, 212, 255, 0.08);
  border-color: rgba(0, 212, 255, 0.2);
}

.code-file__icon { font-size: 0.9rem; }

.code-file__name {
  color: #00d4ff;
  font-family: monospace;
  font-size: 0.9rem;
  text-decoration: none;
  flex: 1;
}

.code-file__name:hover { color: #00ffd1; }

.code-file__desc {
  color: #475569;
  font-size: 0.78rem;
}

.code-placeholder {
  padding: 24px;
  text-align: center;
  color: #475569;
}

.text-muted { color: #334155; font-size: 0.85rem; }

.github-btn {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  padding: 10px 20px;
  background: rgba(255, 255, 255, 0.05);
  border: 1px solid rgba(255, 255, 255, 0.1);
  border-radius: 8px;
  color: #e2e8f0;
  text-decoration: none;
  font-size: 0.85rem;
  transition: all 0.2s;
}

.github-btn:hover {
  background: rgba(255, 255, 255, 0.1);
  border-color: rgba(255, 255, 255, 0.2);
}

/* 可点击的徽章 */
.panel__badge--btn {
  cursor: pointer;
  border: 1px solid rgba(0, 212, 255, 0.2);
  font: inherit;
  transition: all 0.2s;
}
.panel__badge--btn:hover {
  background: rgba(0, 212, 255, 0.18);
  border-color: rgba(0, 212, 255, 0.4);
  transform: translateY(-1px);
}

/* QR 弹窗 */
.qr-overlay {
  position: fixed;
  inset: 0;
  background: rgba(3, 6, 14, 0.82);
  backdrop-filter: blur(6px);
  z-index: 9999;
  display: flex;
  align-items: center;
  justify-content: center;
  animation: qr-fade 0.2s ease;
}
@keyframes qr-fade { from { opacity: 0 } to { opacity: 1 } }

.qr-modal {
  position: relative;
  background: linear-gradient(145deg, #0e1626, #081022);
  border: 1px solid rgba(0, 212, 255, 0.25);
  border-radius: 16px;
  padding: 28px 32px 24px;
  text-align: center;
  box-shadow: 0 20px 60px rgba(0, 212, 255, 0.15);
  max-width: 92vw;
}

.qr-close {
  position: absolute;
  top: 8px;
  right: 12px;
  background: none;
  border: none;
  font-size: 1.6rem;
  color: #64748b;
  cursor: pointer;
  line-height: 1;
  padding: 4px 8px;
}
.qr-close:hover { color: #00d4ff; }

.qr-title {
  color: #00d4ff;
  font-size: 1rem;
  font-weight: 600;
  margin-bottom: 14px;
}

.qr-image {
  width: 260px;
  height: 260px;
  border-radius: 12px;
  background: #fff;
  padding: 8px;
  display: block;
  margin: 0 auto;
}

.qr-url {
  margin-top: 14px;
  font-family: monospace;
  font-size: 0.72rem;
  color: #94a3b8;
  max-width: 280px;
  word-break: break-all;
  line-height: 1.5;
}

.qr-tip {
  margin-top: 10px;
  color: #64748b;
  font-size: 0.78rem;
}

/* 响应式 */
@media (max-width: 640px) {
  .chapter-tab__label { display: none; }
  .chapter-tab { padding: 12px 14px; }
  .demo-iframe { height: 350px; }
  .qr-image { width: 220px; height: 220px; }
  .qr-modal { padding: 20px 22px 18px; }
}
</style>
