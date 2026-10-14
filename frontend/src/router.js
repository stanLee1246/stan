import { createRouter, createWebHistory } from 'vue-router'
import { auth, restoreAuth } from './api'

const router = createRouter({ history: createWebHistory(), routes: [
  { path: '/', component: () => import('./pages/Dashboard.vue') },
  { path: '/journey', component: () => import('./pages/Journey.vue') },
  { path: '/school', component: () => import('./pages/School.vue') },
  { path: '/profile', component: () => import('./pages/Profile.vue'), meta: { login: true } },
  { path: '/interests', component: () => import('./pages/Interests.vue'), meta: { login: true } },
  { path: '/decisions', component: () => import('./pages/Decisions.vue'), meta: { login: true } },
  { path: '/analytics', component: () => import('./pages/Analytics.vue') },
  { path: '/opportunities', component: () => import('./pages/Opportunities.vue') },
  { path: '/experiences', component: () => import('./pages/Experiences.vue') },
  { path: '/admin', component: () => import('./pages/Admin.vue'), meta: { admin: true } },
  { path: '/admin/surveys', component: () => import('./pages/SurveyImport.vue'), meta: { admin: true } },
  { path: '/data-pipeline', component: () => import('./pages/DataPipeline.vue'), meta: { admin: true } },
  { path: '/login', component: () => import('./pages/Login.vue') },
  { path: '/:pathMatch(.*)*', redirect: '/' },
] })
router.beforeEach(async to => {
  if (!auth.ready) await restoreAuth()
  if ((to.meta.login || to.meta.admin) && !auth.user) return { path: '/login', query: { redirect: to.path } }
  if (to.meta.admin && auth.user?.role !== 'admin') return '/'
})
export default router
