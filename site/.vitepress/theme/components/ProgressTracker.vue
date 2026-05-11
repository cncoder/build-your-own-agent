<template><span style="display:none"></span></template>

<script setup lang="ts">
import { onMounted, onBeforeUnmount, watch } from 'vue'
import { useRoute } from 'vitepress'

const KEY = 'byoa:lastRead'
const route = useRoute()

let rafId: number | null = null
let lastScroll = 0

function isChapter(path: string) {
  return /\/chapters\/[^/]+\/$/.test(path) || /\/chapters\/[^/]+\/index\.html$/.test(path)
}

function normalizePath(path: string) {
  return path.replace(/index\.html$/, '')
}

function save() {
  if (typeof window === 'undefined') return
  const path = normalizePath(window.location.pathname)
  if (!isChapter(path)) return
  const max = Math.max(1, document.documentElement.scrollHeight - window.innerHeight)
  const scroll = window.scrollY
  if (scroll < 50) return // don't save top-of-page opens
  const title = document.title.replace(/\s*\|\s*.*$/, '').trim()
  try {
    localStorage.setItem(KEY, JSON.stringify({ url: path, title, scroll, max, ts: Date.now() }))
  } catch {}
}

function onScroll() {
  if (rafId != null) return
  rafId = requestAnimationFrame(() => {
    rafId = null
    // throttle: only save every ~300px of scroll
    if (Math.abs(window.scrollY - lastScroll) < 200) return
    lastScroll = window.scrollY
    save()
  })
}

function restore() {
  if (typeof window === 'undefined') return
  const path = normalizePath(window.location.pathname)
  if (!isChapter(path)) return
  try {
    const raw = localStorage.getItem(KEY)
    if (!raw) return
    const data = JSON.parse(raw)
    if (data.url !== path) return
    // Only auto-restore if user arrived via the "continue" banner
    if (!/[?&]resume=1/.test(window.location.search)) return
    requestAnimationFrame(() => {
      window.scrollTo({ top: data.scroll, behavior: 'instant' as ScrollBehavior })
    })
  } catch {}
}

onMounted(() => {
  window.addEventListener('scroll', onScroll, { passive: true })
  window.addEventListener('beforeunload', save)
  restore()
})

onBeforeUnmount(() => {
  window.removeEventListener('scroll', onScroll)
  window.removeEventListener('beforeunload', save)
  save()
})

watch(() => route.path, () => {
  save()
  lastScroll = 0
  setTimeout(restore, 100)
})
</script>
