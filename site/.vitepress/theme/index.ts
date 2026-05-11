import { h } from 'vue'
import DefaultTheme from 'vitepress/theme'
import type { Theme } from 'vitepress'
import ChapterMedia from './components/ChapterMedia.vue'
import ChapterPlayer from './components/ChapterPlayer.vue'
import RoadmapChart from './components/RoadmapChart.vue'
import ReadingProgress from './components/ReadingProgress.vue'
import ProgressTracker from './components/ProgressTracker.vue'
import './custom.css'

export default {
  extends: DefaultTheme,

  Layout() {
    return h(DefaultTheme.Layout, null, {
      'doc-before': () => h(ReadingProgress),
      'layout-bottom': () => h(ProgressTracker),
    })
  },

  enhanceApp({ app }) {
    app.component('ChapterMedia', ChapterMedia)
    app.component('ChapterPlayer', ChapterPlayer)
    app.component('RoadmapChart', RoadmapChart)
    app.component('ReadingProgress', ReadingProgress)
  }
} satisfies Theme
