<script setup>
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { auth, preferences, setDemo, logout } from './api'
const router = useRouter()
const menuOpen = ref(false)
const error = ref('')
async function signOut() {
  try { await logout(); await router.push('/') } catch (e) { error.value = e.message }
}
</script>

<template>
  <div class="app-shell">
    <aside class="sidebar" :class="{ open: menuOpen }">
      <RouterLink class="brand" to="/" @click="menuOpen = false"><span class="brand-symbol">知</span><span>知途<small>CAREER COMPASS</small></span></RouterLink>
      <div class="nav-caption">你的发展空间</div>
      <nav @click="menuOpen = false">
        <RouterLink to="/"><span>◈</span>发展总览</RouterLink>
        <RouterLink to="/school"><span>▦</span>学校概况</RouterLink>
        <RouterLink to="/profile"><span>◎</span>个人画像</RouterLink>
        <RouterLink to="/interests"><span>✦</span>职业探索</RouterLink>
        <RouterLink to="/decisions"><span>⚖</span>辅助决策</RouterLink>
        <RouterLink to="/analytics"><span>▥</span>数据洞察</RouterLink>
        <RouterLink to="/opportunities"><span>↗</span>发展机会</RouterLink>
        <RouterLink to="/experiences"><span>☷</span>校友经验</RouterLink>
        <RouterLink v-if="auth.user?.role === 'admin'" to="/admin"><span>▤</span>数据工作台</RouterLink>
      </nav>
      <div class="sidebar-note"><span class="tiny-dot"></span> 多一种选择，多一份准备<p>从了解自己开始，探索适合你的发展路径。</p></div>
      <div class="sidebar-footer">湖南交通工程学院<br>学生职业发展辅助决策平台</div>
    </aside>
    <div class="main-shell">
      <header class="topbar">
        <button class="mobile-menu ghost" aria-label="打开导航" @click="menuOpen = !menuOpen">☰</button>
        <span class="topbar-label">成长有迹，未来有途</span>
        <div class="topbar-actions">
          <label class="mode-toggle"><input type="checkbox" :checked="preferences.demo" @change="setDemo($event.target.checked)"><span>演示数据</span></label>
          <template v-if="auth.user"><span class="avatar">{{ auth.user.nickname.slice(0,1) }}</span><span class="user-name">{{ auth.user.nickname }}</span><button class="ghost" @click="signOut">退出</button></template>
          <RouterLink v-else class="button small" to="/login">登录 / 注册</RouterLink>
        </div>
      </header>
      <main><div v-if="error" class="alert error" role="alert">{{ error }}</div><RouterView /></main>
      <footer class="page-footer">知途 · 用有来源的数据，支持你自己的选择<span>当前为毕业设计原型</span></footer>
    </div>
  </div>
</template>
