<script setup>
import { ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { api, login } from '../api'
const route = useRoute(), router = useRouter()
const registration = ref(false), username = ref(''), password = ref(''), nickname = ref('')
const error = ref(''), busy = ref(false)
async function submit() {
  busy.value = true; error.value = ''
  try {
    if (registration.value) await api('/auth/register', { method: 'POST', body: { username: username.value, password: password.value, nickname: nickname.value } })
    await login({ username: username.value, password: password.value })
    const destination = route.query.redirect
    await router.push(typeof destination === 'string' && destination.startsWith('/') && !destination.startsWith('//') ? destination : '/')
  } catch (e) { error.value = e.message } finally { busy.value = false }
}
</script>
<template><div class="auth-layout"><div class="auth-intro"><div class="eyebrow">YOUR NEXT CHAPTER</div><h1>每一步成长，<br>都有自己的方向。</h1><p>保存你的技能与发展意向，让每一次选择都有更多参考。</p><div class="auth-decoration" aria-hidden="true">↗</div></div><form class="panel auth-form" @submit.prevent="submit"><h2>{{ registration ? '创建账户' : '欢迎回来' }}</h2><p class="muted">普通账户注册，不代表学校身份认证。</p><label>用户名<input v-model="username" required minlength="3" maxlength="50" pattern="[a-zA-Z0-9_-]+" autocomplete="username" placeholder="英文、数字或下划线"></label><label v-if="registration">公开昵称<input v-model="nickname" required maxlength="60" autocomplete="nickname"></label><label>密码<input v-model="password" type="password" required minlength="10" maxlength="128" :autocomplete="registration ? 'new-password' : 'current-password'" placeholder="至少 10 位"></label><div v-if="error" class="alert error" role="alert">{{ error }}</div><button class="button" :disabled="busy">{{ busy ? '处理中…' : registration ? '注册并登录' : '登录' }}</button><button type="button" class="ghost" @click="registration = !registration">{{ registration ? '已有账户？去登录' : '还没有账户？创建账户' }}</button></form></div></template>
