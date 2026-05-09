<template>
  <!-- 固定底部音频迷你播放器 -->
  <Teleport to="body">
    <div
      v-if="audioSrc && isVisible"
      class="mini-player"
      :class="{ 'mini-player--expanded': isExpanded }"
    >
      <button class="mini-player__toggle" @click="isExpanded = !isExpanded" :title="isExpanded ? '收起' : '展开'">
        <span class="mini-player__icon">🎙️</span>
        <span v-if="!isExpanded" class="mini-player__title">{{ chapterTitle }} — 播客</span>
        <span v-if="isExpanded" class="mini-player__chevron">▼</span>
        <span v-else class="mini-player__chevron">▲</span>
      </button>
      <div v-show="isExpanded" class="mini-player__body">
        <div class="mini-player__label">🎙️ 正在收听：{{ chapterTitle }}</div>
        <audio ref="audioEl" :src="audioSrc" controls preload="metadata" class="mini-player__audio" />
      </div>
      <button class="mini-player__close" @click="isVisible = false" title="关闭">✕</button>
    </div>
  </Teleport>
</template>

<script setup lang="ts">
import { ref } from 'vue'

defineProps<{
  audioSrc?: string
  chapterTitle?: string
}>()

const isVisible = ref(true)
const isExpanded = ref(false)
const audioEl = ref<HTMLAudioElement>()
</script>

<style scoped>
.mini-player {
  position: fixed;
  bottom: 20px;
  right: 20px;
  z-index: 1000;
  background: rgba(8, 13, 24, 0.95);
  border: 1px solid rgba(0, 212, 255, 0.3);
  border-radius: 12px;
  backdrop-filter: blur(20px);
  box-shadow: 0 8px 40px rgba(0, 0, 0, 0.5), 0 0 0 1px rgba(0, 212, 255, 0.05);
  transition: all 0.3s ease;
  min-width: 240px;
  max-width: 380px;
}

.mini-player--expanded {
  min-width: 340px;
}

.mini-player__toggle {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 10px 14px;
  width: 100%;
  background: none;
  border: none;
  color: #00d4ff;
  cursor: pointer;
  font-size: 0.85rem;
  font-weight: 600;
  text-align: left;
}

.mini-player__toggle:hover {
  color: #00ffd1;
}

.mini-player__icon { font-size: 1rem; }
.mini-player__title { flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.mini-player__chevron { font-size: 0.7rem; opacity: 0.6; }

.mini-player__body {
  padding: 0 14px 14px;
}

.mini-player__label {
  color: #64748b;
  font-size: 0.75rem;
  margin-bottom: 8px;
}

.mini-player__audio {
  width: 100%;
  border-radius: 6px;
  accent-color: #00d4ff;
  height: 36px;
}

.mini-player__close {
  position: absolute;
  top: -8px;
  right: -8px;
  width: 20px;
  height: 20px;
  background: rgba(8, 13, 24, 0.9);
  border: 1px solid rgba(0, 212, 255, 0.2);
  border-radius: 50%;
  color: #64748b;
  font-size: 0.65rem;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: all 0.2s;
}

.mini-player__close:hover {
  color: #ff4040;
  border-color: #ff4040;
}
</style>
