import DefaultTheme from 'vitepress/theme'
import type { Theme } from 'vitepress'
import ChapterMedia from './components/ChapterMedia.vue'
import ChapterPlayer from './components/ChapterPlayer.vue'
import RoadmapChart from './components/RoadmapChart.vue'
import './custom.css'

export default {
  extends: DefaultTheme,

  enhanceApp({ app }) {
    app.component('ChapterMedia', ChapterMedia)
    app.component('ChapterPlayer', ChapterPlayer)
    app.component('RoadmapChart', RoadmapChart)
  }
} satisfies Theme
