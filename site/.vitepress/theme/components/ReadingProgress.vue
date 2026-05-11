<template>
  <Transition name="banner-fade">
    <div v-if="showBanner" class="resume-banner">
      <div class="resume-banner__inner">
        <span class="resume-banner__icon">📖</span>
        <div class="resume-banner__text">
          <div class="resume-banner__title">继续阅读上次的进度</div>
          <div class="resume-banner__sub">
            {{ saved.title }} · 约 {{ percent }}%
          </div>
        </div>
        <a :href="saved.url + '?resume=1'" class="resume-banner__btn">继续 →</a>
        <button class="resume-banner__close" @click="dismiss" aria-label="关闭">×</button>
      </div>
    </div>
  </Transition>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'

type Saved = { url: string; title: string; scroll: number; max: number; ts: number }
const KEY = 'byoa:lastRead'
const DISMISS_KEY = 'byoa:lastRead:dismissed'

const showBanner = ref(false)
const saved = ref<Saved>({ url: '', title: '', scroll: 0, max: 1, ts: 0 })
const percent = ref(0)

function load(): Saved | null {
  try {
    const raw = localStorage.getItem(KEY)
    if (!raw) return null
    return JSON.parse(raw)
  } catch { return null }
}

function dismiss() {
  showBanner.value = false
  try { sessionStorage.setItem(DISMISS_KEY, '1') } catch {}
}

onMounted(() => {
  if (typeof window === 'undefined') return
  const data = load()
  if (!data || !data.url) return
  // Don't show on the same page the user was reading
  if (data.url === window.location.pathname) return
  try {
    if (sessionStorage.getItem(DISMISS_KEY) === '1') return
  } catch {}
  saved.value = data
  percent.value = Math.min(99, Math.max(1, Math.round((data.scroll / Math.max(1, data.max)) * 100)))
  showBanner.value = true
})
</script>

<style scoped>
.resume-banner {
  position: sticky;
  top: 64px;
  z-index: 50;
  margin: 0 auto 24px;
  max-width: 980px;
  padding: 0 16px;
}

.resume-banner__inner {
  display: flex;
  align-items: center;
  gap: 14px;
  padding: 12px 18px;
  background: linear-gradient(90deg, rgba(0, 212, 255, 0.12), rgba(139, 92, 246, 0.1));
  border: 1px solid rgba(0, 212, 255, 0.25);
  border-radius: 12px;
  backdrop-filter: blur(12px);
  box-shadow: 0 8px 24px rgba(0, 212, 255, 0.08);
}

.resume-banner__icon {
  font-size: 1.5rem;
}

.resume-banner__text {
  flex: 1;
  min-width: 0;
}

.resume-banner__title {
  color: #e2e8f0;
  font-size: 0.92rem;
  font-weight: 600;
}

.resume-banner__sub {
  color: #94a3b8;
  font-size: 0.78rem;
  margin-top: 2px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.resume-banner__btn {
  padding: 8px 16px;
  background: rgba(0, 212, 255, 0.15);
  border: 1px solid rgba(0, 212, 255, 0.3);
  border-radius: 8px;
  color: #00d4ff;
  text-decoration: none;
  font-size: 0.85rem;
  font-weight: 500;
  transition: all 0.2s;
  white-space: nowrap;
}

.resume-banner__btn:hover {
  background: rgba(0, 212, 255, 0.25);
  border-color: rgba(0, 212, 255, 0.5);
}

.resume-banner__close {
  background: none;
  border: none;
  font-size: 1.4rem;
  color: #64748b;
  cursor: pointer;
  padding: 4px 8px;
  line-height: 1;
}
.resume-banner__close:hover { color: #e2e8f0; }

.banner-fade-enter-active, .banner-fade-leave-active {
  transition: all 0.3s ease;
}
.banner-fade-enter-from, .banner-fade-leave-to {
  opacity: 0;
  transform: translateY(-8px);
}

@media (max-width: 640px) {
  .resume-banner__sub { font-size: 0.72rem; }
  .resume-banner__btn { padding: 6px 12px; font-size: 0.78rem; }
}
</style>
