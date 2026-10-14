<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import { api, auth, preferences, setDemo, paths, displayDate } from '../api'
import Chart from '../components/Chart.vue'
import '../styles/analytics.css'
const data = ref(null), sources = ref([]), opportunities = ref([]), profile = ref(null)
const source = ref(''), major = ref(''), year = ref(''), error = ref(''), loading = ref(false)
let requestId = 0, initializationId = 0
const palette = ['#246c5a', '#73a891', '#e0ba76', '#9baabe', '#bdcfc3', '#e5ded1']
const pie = computed(() => ({ color: palette, tooltip: { trigger: 'item', formatter: '{b}: {c} 人（{d}%）' },
  legend: { bottom: 0, icon: 'circle' }, series: [{ type: 'pie', radius: ['46%', '70%'], center: ['50%', '43%'],
  label: { show: false }, data: data.value?.paths.map(x => ({ name: x.label, value: x.count })) || [] }] }))
const bar = computed(() => ({ color: ['#5d937d'], tooltip: { trigger: 'axis' }, grid: { left: 55, right: 25, top: 18, bottom: 35 },
  xAxis: { type: 'value', minInterval: 1, splitLine: { lineStyle: { color: '#edf0ea' } } },
  yAxis: { type: 'category', inverse: true, data: data.value?.cities.map(x => x.label) || [] },
  series: [{ type: 'bar', barMaxWidth: 24, itemStyle: { borderRadius: [0, 5, 5, 0] }, data: data.value?.cities.map(x => x.count) || [] }] }))
const trend = computed(() => ({ color: ['#246c5a'], tooltip: { trigger: 'axis' }, grid: { left: 45, right: 25, top: 20, bottom: 35 },
  xAxis: { type: 'category', data: [...(data.value?.years || [])].sort((a,b) => a.key-b.key).map(x => x.label) },
  yAxis: { type: 'value', minInterval: 1, splitLine: { lineStyle: { color: '#edf0ea' } } },
  series: [{ type: 'line', symbolSize: 8, data: [...(data.value?.years || [])].sort((a,b) => a.key-b.key).map(x => x.count), areaStyle: { opacity: .08 } }] }))
async function load() {
  const id = ++requestId
  loading.value = true; error.value = ''
  const params = new URLSearchParams({ data_kind: preferences.demo ? 'demo' : 'authorized' })
  if (source.value) params.set('source_name', source.value)
  if (major.value) params.set('major', major.value)
  if (year.value) params.set('graduation_year', year.value)
  try { const result = await api(`/dashboard?${params}`); if (id === requestId) data.value = result }
  catch (e) { if (id === requestId) { error.value = e.message; data.value = null } }
  finally { if (id === requestId) loading.value = false }
}
async function initialize() {
  const id = ++initializationId
  requestId += 1; error.value = ''; loading.value = true; data.value = null
  const demo = preferences.demo
  try {
    const [newSources, newOpportunities, newProfile] = await Promise.all([
      api(`/data-sources?data_kind=${demo ? 'demo' : 'authorized'}`),
      api(`/opportunities?data_kind=${demo ? 'demo' : 'public'}`),
      auth.user ? api('/profile') : Promise.resolve(null)
    ])
    if (id !== initializationId) return
    sources.value = newSources; source.value = sources.value[0] || ''
    opportunities.value = newOpportunities; profile.value = newProfile
    if (profile.value) major.value = profile.value.major
    await load()
  } catch (e) { if (id === initializationId) { error.value = e.message; loading.value = false; opportunities.value = [] } }
}
watch(() => preferences.demo, initialize)
onMounted(initialize)
</script>

<template>
  <div class="page-heading"><div><div class="eyebrow">DEVELOPMENT OVERVIEW</div><h1>{{ auth.user ? `${auth.user.nickname}，你好` : '从这里，看见更多可能' }}<span class="heading-dot">.</span></h1><p>了解同专业去向，发现机会，规划属于自己的下一步。</p></div><RouterLink class="button" to="/profile">完善个人画像 <span>↗</span></RouterLink></div>
  <section class="welcome-banner"><div><span class="overline">每一种未来，都值得认真探索</span><h2>你的方向，可以不止一个。</h2><p>就业、升学、考公与实习，多路径准备，从了解自己开始。</p><RouterLink to="/opportunities">去看看发展机会 <span>→</span></RouterLink></div><div class="compass-art" aria-hidden="true"><div class="orbit orbit-one"></div><div class="orbit orbit-two"></div><span class="north">N</span><span class="compass-arrow">↗</span><span class="art-label">FIND YOUR WAY</span></div></section>
  <div class="analytics-home-actions">
    <RouterLink to="/analytics" class="analytics-home-link"><span class="analytics-home-icon" aria-hidden="true">▥</span><div><span class="analytics-kicker">从数据看机会</span><h2>多维数据探索</h2><p>城市、路径、技能与公告趋势，六种图表共同观察。</p></div><span aria-hidden="true">↗</span></RouterLink>
    <RouterLink to="/decisions" class="analytics-home-link analytics-home-link-decision"><span class="analytics-home-icon" aria-hidden="true">◎</span><div><span class="analytics-kicker">从画像做选择</span><h2>职业决策工作台</h2><p>结合个人偏好比较多条路径，找到下一步行动。</p></div><span aria-hidden="true">↗</span></RouterLink>
  </div>
  <section class="panel"><div class="panel-heading"><h2>我的职业规划路线</h2><RouterLink to="/journey">查看步骤与我的进度 →</RouterLink></div><div class="home-journey" aria-label="职业规划五步流程"><RouterLink to="/profile">① 个人画像</RouterLink><RouterLink to="/interests">② 兴趣探索（可选）</RouterLink><RouterLink to="/opportunities">③ 筛选机会</RouterLink><RouterLink to="/decisions">④ 比较取舍</RouterLink><RouterLink to="/decisions#action-plan">⑤ 行动与复盘</RouterLink></div><p class="data-note">{{ profile ? `你已有 V${profile.version} 画像，可以查看机会并开始比较。` : '先保存一份画像，让机会比较有明确依据。' }} 学校与专业资料可在“学校概况”中查看。</p></section>
  <div v-if="preferences.demo" class="alert demo">演示模式 · 当前图表和机会均为模拟数据，不代表学校真实统计或招聘。</div>
  <div v-if="error" class="alert error" role="alert">{{ error }} <button class="ghost" @click="initialize">重试</button></div>
  <section class="filterbar">
    <label>专业<select v-model="major" @change="load"><option value="">全部专业</option><option>数据科学与大数据技术</option><option>软件工程</option><option>计算机科学与技术</option></select></label>
    <label>毕业届次<select v-model="year" @change="load"><option value="">全部届次</option><option v-for="y in [2023,2024,2025,2026]" :key="y" :value="y">{{ y }} 届</option></select></label>
    <label class="source-filter">数据来源<select v-model="source" @change="load"><option v-if="!sources.length" value="">暂无已导入来源</option><option v-for="s in sources" :key="s">{{ s }}</option></select></label>
    <span class="muted">{{ loading ? '更新中…' : `观察截止：${displayDate(data?.observed_on)}` }}</span>
  </section>
  <div class="stat-grid"><article class="stat-card"><span>当前统计样本</span><strong>{{ data?.sample_size === null ? '已保护' : data?.sample_size ?? '—' }}<small v-if="data?.sample_size !== null">人</small></strong><p>{{ preferences.demo ? '仅功能演示使用' : '授权样本 · 不代表全校' }}</p></article><article class="stat-card"><span>最近观察日期</span><strong class="date-value">{{ displayDate(data?.latest_observation) }}</strong><p>以实际去向观察日为准</p></article><article class="stat-card"><span>当前发展机会</span><strong>{{ opportunities.length }}<small>条</small></strong><p>{{ preferences.demo ? '模拟机会' : '已录入且未确认过期' }}</p></article><article class="stat-card"><span>我的画像版本</span><strong>{{ profile ? `V${profile.version}` : '待完善' }}</strong><p>保留历史，让变化有迹可循</p></article></div>
  <div v-if="data && !data.sample_size && !data.privacy_suppressed" class="empty large"><span>◎</span><h3>暂无已核实数据</h3><p>真实样本导入后将在这里展示。也可以打开演示模式，先体验完整流程。</p><button v-if="!preferences.demo" class="button" @click="setDemo(true)">查看模拟演示</button></div>
  <div v-else-if="data" class="chart-grid"><section class="panel"><div class="panel-heading"><h2>同专业毕业去向</h2><span class="tag">实际去向</span></div><Chart v-if="data.paths.length" :option="pie" label="毕业去向人数分布"/><div v-else class="empty">小样本保护：已隐藏整项分布</div><p class="chart-caption">{{ data.paths.map(x => `${x.label} ${x.count}人`).join(' · ') }}</p></section><section class="panel"><div class="panel-heading"><h2>目的城市分布</h2><span class="muted">单位：人</span></div><Chart v-if="data.cities.length" :option="bar" label="目的城市人数分布"/><div v-else class="empty">小样本保护：已隐藏整项分布</div><p class="chart-caption">{{ data.cities.map(x => `${x.label} ${x.count}人`).join(' · ') }}</p></section><section class="panel full-width"><div class="panel-heading"><h2>各届次样本数量</h2><span class="muted">描述性统计 · 非就业率趋势</span></div><Chart v-if="data.years.length" :option="trend" label="各毕业届次样本数量"/><div v-else class="empty">小样本保护：已隐藏整项分布</div><p class="chart-caption">{{ data.years.map(x => `${x.label}届 ${x.count}人`).join(' · ') }}</p></section></div>
  <p v-if="data" class="data-note">口径：{{ data.definition }} {{ data.notice }}<span v-if="data.batch_ids.length"> · 可追溯批次：{{ data.batch_ids.join('、') }}</span></p>
  <section class="panel"><div class="panel-heading"><h2>近期发展机会</h2><RouterLink to="/opportunities">查看全部 →</RouterLink></div><div v-if="!opportunities.length" class="empty">暂无已录入机会</div><div v-for="o in opportunities.slice(0,3)" :key="o.id" class="opportunity-row"><span class="opportunity-icon">↗</span><div><h3>{{ o.title }}</h3><p>{{ o.organization }} · {{ o.city || '城市待核对' }}</p></div><span class="tag">{{ paths[o.path] }}</span><RouterLink class="text-link" to="/opportunities">了解详情 →</RouterLink></div></section>
</template>
