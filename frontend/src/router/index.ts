import { createRouter, createWebHistory } from 'vue-router'

import Overview from '@/views/Overview.vue'
import WorkbenchView from '@/views/WorkbenchView.vue'
import AttributionView from '@/views/AttributionView.vue'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/', name: 'overview', component: Overview },
    // 来源归属含撤回、确认、现场补发、归属交付等专属操作，使用独立工作台
    { path: '/source_attribution', name: 'source-attribution', component: AttributionView },
    { path: '/:moduleKey', name: 'module', component: WorkbenchView, props: true },
  ],
})

export default router
