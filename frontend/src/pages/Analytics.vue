<script setup>
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { api, preferences, setDemo, paths } from '../api'
import Chart from '../components/Chart.vue'
import '../styles/analytics.css'

const data = ref(null), loading = ref(false), error = ref(''), view = ref('charts')
const major = ref(''), city = ref(''), path = ref(''), startDate = ref(''), endDate = ref('')
const router = useRouter(), route = useRoute(), interaction = ref(''), sharedLink = ref('')
let restoringRoute = false
const queryKey = query => JSON.stringify(Object.entries(query).filter(([,value])=>value !== '').sort(([a],[b])=>a.localeCompare(b)))
function filterParams() {
  const params = {data_kind:preferences.demo ? 'demo' : 'public'}
  for (const [key,value] of Object.entries({major:major.value.trim(),city:city.value.trim(),path:path.value,start_date:startDate.value,end_date:endDate.value})) if(value) params[key]=value
  return params
}
function applyRoute() {
  const value = key => typeof route.query[key] === 'string' ? route.query[key] : ''
  restoringRoute = true
  if(['demo','public'].includes(value('data_kind'))) setDemo(value('data_kind') === 'demo')
  major.value=value('major');city.value=value('city');path.value=value('path');startDate.value=value('start_date');endDate.value=value('end_date')
  restoringRoute = false
}
applyRoute()
let requestId = 0, requestedQueryKey = ''
const colors = ['#2d7562', '#76a898', '#d6ae68', '#6e8ca7', '#ba91a3', '#9bad69', '#8b9998']
const rows = key => Array.isArray(data.value?.[key]) ? data.value[key] : []
const summary = computed(() => data.value?.summary || {})
const qualityRows = computed(() => data.value?.quality?.fields || [])
const appliedScope = computed(() => data.value?.scope || {})
function appliedParams() {
  return Object.fromEntries(Object.entries({data_kind:data.value?.data_kind || (preferences.demo ? 'demo':'public'),
    major:appliedScope.value.major,city:appliedScope.value.city,path:appliedScope.value.path,
    start_date:appliedScope.value.start_date,end_date:appliedScope.value.end_date}).filter(([,value])=>value))
}
function restoreApplied() {
  const s=appliedScope.value
  major.value=s.major || '';city.value=s.city || '';path.value=s.path || '';startDate.value=s.start_date || '';endDate.value=s.end_date || ''
}
function selectPath(event) {
  const item=pathRows.value[event.dataIndex]; if(!item) return
  restoreApplied();path.value=item.key;interaction.value=`已按发展路径“${item.label}”联动全部图表。`;load()
}
function selectCity(event) {
  const name=cityRows.value[event.dataIndex]?.key || event.name
  if(!name || name === '未知') { interaction.value='该项城市未标注，暂不能按具体城市筛选；请在字段完整性中核对缺失情况。';return }
  restoreApplied();city.value=name;interaction.value=`已按城市“${name}”联动全部图表。`;load()
}
function selectMonth(event) {
  const month=monthRows.value[event.dataIndex]?.month; if(!/^\d{4}-\d{2}$/.test(month || '')) return
  const [year,number]=month.split('-').map(Number)
  restoreApplied();startDate.value=`${month}-01`;endDate.value=`${month}-${new Date(Date.UTC(year,number,0)).getUTCDate()}`
  interaction.value=`已按 ${month} 的公告发布日期联动全部图表；未知发布日期不纳入。`;load()
}
function inspectSkill(name, place) {
  if(!name || place === '未知') {interaction.value='该格城市未标注，不能自动定位到具体城市；可从下方技能按钮查看全部来源。';return}
  const query={...appliedParams(),skill:name,include_expired:'true'}
  if(place) query.city=place
  router.push({path:'/opportunities',query})
}
function selectHeat(event) {
  if(!Array.isArray(event.value)) return
  inspectSkill(heat.value.skills[event.value[0]],heat.value.cities[event.value[1]])
}
function selectStack(event) {
  const key=Object.keys(paths).find(key=>paths[key] === event.seriesName)
  if(event.name === '未知' || !key) return
  restoreApplied();city.value=event.name;path.value=key;interaction.value=`已联动 ${event.name} · ${paths[key]} 的公告。`;load()
}
async function shareAnalysis() {
  sharedLink.value=window.location.origin+router.resolve({path:'/analytics',query:appliedParams()}).href
  try {await navigator.clipboard.writeText(sharedLink.value);interaction.value='已复制当前分析链接；对方打开后会恢复相同数据类型与筛选范围。'}
  catch {interaction.value='当前浏览器无法自动复制，请复制下方链接。'}
}
const hasData = computed(() => Number(summary.value.opportunities) > 0)
const pathRows = computed(() => rows('paths'))
const cityRows = computed(() => rows('cities'))
const skillRows = computed(() => rows('skills'))
const monthRows = computed(() => rows('monthly'))
const sourceRows = computed(() => rows('sources'))
const heat = computed(() => data.value?.heatmap || { cities: [], skills: [], cells: [] })
const matrix = computed(() => data.value?.city_path_matrix || { cities: [], paths: [], series: [] })
const heatRows = computed(() => (heat.value.cells || []).map(([skill, place, count]) => ({
  skill: heat.value.skills?.[skill] ?? '未标注', city: heat.value.cities?.[place] ?? '待核对', count
})).filter(row => row.count > 0))
const matrixRows = computed(() => (matrix.value.series || []).flatMap(series => (series.data || []).map((count, index) => ({
  city: matrix.value.cities?.[index] ?? '待核对', path: series.label || paths[series.path] || series.path, count
})).filter(row => row.count > 0)))
const totalSkills = computed(() => summary.value.total_skill_mentions ?? skillRows.value.reduce((sum, item) => sum + item.count, 0))
const datedCount = computed(() => monthRows.value.reduce((sum, item) => sum + item.count, 0))
const generated = computed(() => {
  if (!data.value?.generated_at) return '待更新'
  const stamp = new Date(data.value.generated_at)
  return Number.isNaN(stamp.getTime()) ? '待更新' : stamp.toLocaleString('zh-CN', { timeZone: 'Asia/Seoul', hour12: false })
})
const chartStyle = { textStyle: { fontFamily: 'Microsoft YaHei, sans-serif', color: '#587168', fontSize: 11 }, animationDuration: 350 }
const grid = { left: 40, right: 22, top: 22, bottom: 48, containLabel: true }
const countAxis = { type: 'value', minInterval: 1, splitLine: { lineStyle: { color: '#edf1ed' } } }
const tooltip = { trigger: 'axis', confine: true, renderMode: 'richText' }
const pie = computed(() => ({ ...chartStyle, color: colors,
  tooltip: { trigger: 'item', confine: true, renderMode: 'richText', formatter: item => `${item.name}\n公告：${item.value} 条（${(item.value / summary.value.opportunities * 100).toFixed(1)}%）` },
  legend: { bottom: 0, icon: 'circle', itemWidth: 9, textStyle: { fontSize: 10 } },
  series: [{ type: 'pie', radius: ['43%', '68%'], center: ['50%', '43%'], label: { show: false },
    emphasis: { label: { show: true, formatter: '{b}\n{c} 条', fontSize: 13 } },
    data: pathRows.value.map(item => ({ name: item.label, value: item.count })) }]
}))
const cityBar = computed(() => ({ ...chartStyle, tooltip, grid: { ...grid, left: 20, bottom: 30 },
  xAxis: countAxis, yAxis: { type: 'category', inverse: true, data: cityRows.value.slice(0, 12).map(item => item.label),
    axisLine: { show: false }, axisTick: { show: false }, axisLabel: { width: 75, overflow: 'truncate' } },
  series: [{ type: 'bar', barMaxWidth: 20, data: cityRows.value.slice(0, 12).map(item => item.count),
    itemStyle: { color: '#659c86', borderRadius: [0, 4, 4, 0] }, label: { show: true, position: 'right', color: '#5b7766' } }]
}))
const monthlyLine = computed(() => ({ ...chartStyle, color: ['#2d7562'], tooltip, grid,
  xAxis: { type: 'category', data: monthRows.value.map(item => item.month), axisLabel: { hideOverlap: true }, boundaryGap: false },
  yAxis: countAxis, series: [{ type: 'line', name: '当月发布公告', symbolSize: 7,
    data: monthRows.value.map(item => item.count), areaStyle: { opacity: .09 }, lineStyle: { width: 3 } }]
}))
const heatmap = computed(() => ({ ...chartStyle,
  tooltip: { position: 'top', confine: true, renderMode: 'richText', formatter: item => {
    const [skill, place, count] = item.data
    return `${heat.value.cities?.[place] || '待核对'} · ${heat.value.skills?.[skill] || '未标注'}：${count} 条`
  } },
  grid: { left: 65, right: 15, top: 20, bottom: 90 },
  xAxis: { type: 'category', data: heat.value.skills || [], splitArea: { show: true },
    axisLabel: { rotate: 35, width: 62, overflow: 'truncate', fontSize: 9 } },
  yAxis: { type: 'category', data: heat.value.cities || [], splitArea: { show: true },
    axisLabel: { width: 58, overflow: 'truncate', fontSize: 10 } },
  visualMap: { min: 0, max: Math.max(1, ...(heat.value.cells || []).map(item => item[2])), calculable: false,
    orient: 'horizontal', left: 'center', bottom: 0, itemWidth: 10, itemHeight: 100,
    text: ['更多', '较少'], textStyle: { fontSize: 10 }, inRange: { color: ['#f2f6ed', '#93be9f', '#286d55'] } },
  series: [{ type: 'heatmap', data: heat.value.cells || [], label: { show: true, fontSize: 10 },
    itemStyle: { borderColor: '#fff', borderWidth: 2 }, emphasis: { itemStyle: { shadowBlur: 8, shadowColor: '#42624b55' } } }]
}))
const stacked = computed(() => ({ ...chartStyle, color: colors, tooltip: { ...tooltip, axisPointer: { type: 'shadow' } },
  grid: { ...grid, top: 44, bottom: 35 }, legend: { top: 0, type: 'scroll', itemWidth: 9, textStyle: { fontSize: 10 } },
  xAxis: { type: 'category', data: matrix.value.cities || [], axisLabel: { hideOverlap: true, width: 65, overflow: 'truncate', fontSize: 10 } },
  yAxis: countAxis, series: (matrix.value.series || []).map(series => ({ name: series.label || paths[series.path] || series.path,
    type: 'bar', stack: 'opportunities', barMaxWidth: 35, data: series.data || [], emphasis: { focus: 'series' } }))
}))
const treemap = computed(() => ({ ...chartStyle, color: colors,
  tooltip: { trigger: 'item', confine: true, renderMode: 'richText', formatter: item => `${item.name}：${item.value} 条公告提及` },
  series: [{ type: 'treemap', roam: false, nodeClick: false, breadcrumb: { show: false },
    left: 0, right: 0, top: 8, bottom: 8, leafDepth: 1,
    label: { show: true, formatter: '{b}\n{c} 条', fontSize: 12 },
    itemStyle: { gapWidth: 3, borderColor: '#fff', borderWidth: 2 },
    levels: [{ colorSaturation: [.25, .6], itemStyle: { borderWidth: 2, gapWidth: 3 } }],
    data: skillRows.value.slice(0, 18).map(item => ({ name: item.label, value: item.count })) }]
}))

async function load() {
  const current = ++requestId
  if (startDate.value && endDate.value && startDate.value > endDate.value) {
    error.value = '开始日期不能晚于结束日期。'; data.value = null; loading.value = false; return
  }
  loading.value = true; error.value = ''; data.value = null
  const query = filterParams(), params = new URLSearchParams(query)
  requestedQueryKey = queryKey(query)
  sharedLink.value = ''
  if(queryKey(route.query) !== queryKey(query)) router.replace({query})
  try { const result = await api(`/analytics?${params}`); if (current === requestId) data.value = result }
  catch (failure) { if (current === requestId) error.value = failure.message }
  finally { if (current === requestId) loading.value = false }
}
function reset() {
  major.value = ''; city.value = ''; path.value = ''; startDate.value = ''; endDate.value = ''; interaction.value='已清除分析筛选。';load()
}
function exportCsv() {
  if (!data.value || loading.value) return
  const kind = preferences.demo ? '模拟数据' : '公开公告'
  const records = [['数据类型', '维度', '项目', '子项目', '数量', '单位'],
    ...pathRows.value.map(item => [kind, '发展路径', item.label, '', item.count, '条公告']),
    ...cityRows.value.map(item => [kind, '城市', item.label, '', item.count, '条公告']),
    ...monthRows.value.map(item => [kind, '发布月份', item.month, '', item.count, '条公告']),
    ...skillRows.value.map(item => [kind, '技能', item.label, '', item.count, '条公告提及']),
    ...heatRows.value.map(item => [kind, '城市×技能', item.city, item.skill, item.count, '条公告提及']),
    ...matrixRows.value.map(item => [kind, '城市×路径', item.city, item.path, item.count, '条公告']),
    ...sourceRows.value.map(item => [kind, '来源', item.name, '', item.count, '条公告']),
    [kind, '统计范围', JSON.stringify(data.value.scope || {}), '', '', ''],
    [kind, '口径说明', data.value.notice || '', '', '', '']]
  records.push(...qualityRows.value.map(item=>[kind,'字段完整性',item.label,`已知 / ${data.value.quality.denominator}`,item.known,'条公告']))
  // Quoting protects CSV structure; prefix text that spreadsheet apps could interpret as a formula.
  const encode = value => {
    let text = String(value ?? '')
    if (typeof value === 'string' && /^[\s]*[=+\-@]/.test(text)) text = `'${text}`
    return `"${text.replaceAll('"', '""')}"`
  }
  const blob = new Blob(['\uFEFF' + records.map(record => record.map(encode).join(',')).join('\r\n')], { type: 'text/csv;charset=utf-8;' })
  const url = URL.createObjectURL(blob), link = document.createElement('a')
  link.href = url; link.download = `career-analytics-${preferences.demo ? 'demo' : 'public'}-${new Date().toISOString().slice(0, 10)}.csv`
  document.body.appendChild(link); link.click(); link.remove(); URL.revokeObjectURL(url)
}
watch(() => preferences.demo, () => {if(!restoringRoute) {interaction.value='';load()}},{flush:'sync'})
watch(() => route.query, () => {applyRoute();if(requestedQueryKey !== queryKey(filterParams())) load()})
onMounted(load)
onBeforeUnmount(() => { requestId += 1 })
</script>

<template>
  <div class="analytics-page">
    <div class="page-heading"><div><div class="eyebrow">OPPORTUNITY DATA EXPLORER</div><h1>多维数据探索<span class="heading-dot">.</span></h1><p>从城市、发展路径和技能需求出发，看清机会的分布。</p></div><RouterLink class="button" to="/decisions">去做职业决策 <span>↗</span></RouterLink></div>
    <section class="analytics-intro">
      <div><span class="analytics-kicker">六个视角 · 同一个可追溯范围</span><h2>把信息变成选择的依据。</h2><p>这里只统计已导入的机会公告。公告数量反映采集范围，不代表地区全部岗位、招聘人数或就业概率。</p></div>
      <div class="analytics-mode" role="group" aria-label="机会统计数据类型"><button :class="{ active: !preferences.demo }" @click="setDemo(false)">公开数据</button><button :class="{ active: preferences.demo }" @click="setDemo(true)">模拟演示</button></div>
    </section>
    <div v-if="preferences.demo" class="alert demo">模拟演示 · 所有公告、城市分布和技能需求均为测试数据，不能作为真实职业决策依据。</div>
    <div v-if="error" class="alert error" role="alert">{{ error }} <button class="ghost" @click="load">重试</button></div>
    <form class="analytics-filters panel" @submit.prevent="load">
      <label>面向专业<input v-model="major" placeholder="全部专业" list="analytics-majors"/><datalist id="analytics-majors"><option>数据科学与大数据技术</option><option>软件工程</option><option>计算机科学与技术</option></datalist></label>
      <label>机会城市<input v-model="city" placeholder="全部城市，如衡阳"/></label>
      <label>发展路径<select v-model="path"><option value="">全部路径</option><option v-for="(label, key) in paths" :key="key" :value="key">{{ label }}</option></select></label>
      <label>发布日期起<input v-model="startDate" type="date" :max="endDate || undefined"/></label>
      <label>发布日期止<input v-model="endDate" type="date" :min="startDate || undefined"/></label>
      <div class="analytics-filter-actions"><button class="button small" :disabled="loading" type="submit">{{ loading ? '查询中…' : '应用筛选' }}</button><button class="ghost" type="button" @click="reset">重置</button></div>
    </form>
    <p class="analytics-date-note">日期筛选按公告发布日期计算；缺少发布日期的公告只参与未限定日期的统计。公开数据与模拟数据分别统计。</p>
    <div v-if="loading" class="empty large" role="status">正在整理当前范围的数据…</div>
    <template v-else-if="data">
      <div class="analytics-summary">
        <article><span class="analytics-stat-symbol" aria-hidden="true">▤</span><div><span>机会公告</span><strong>{{ summary.opportunities ?? 0 }}<small>条</small></strong><p>已去重 · 当前统计范围</p></div></article>
        <article><span class="analytics-stat-symbol" aria-hidden="true">⌖</span><div><span>已知城市</span><strong>{{ summary.unique_cities ?? 0 }}<small>座</small></strong><p>缺失城市单独标注</p></div></article>
        <article><span class="analytics-stat-symbol" aria-hidden="true">◷</span><div><span>截止日期未过</span><strong>{{ summary.total_active ?? 0 }}<small>条</small></strong><p>另有 {{ summary.deadline_unknown ?? 0 }} 条日期待核对</p></div></article>
        <article><span class="analytics-stat-symbol" aria-hidden="true">◈</span><div><span>已导入来源</span><strong>{{ summary.source_count ?? 0 }}<small>个</small></strong><p>来源覆盖影响统计分布</p></div></article>
      </div>
      <div v-if="!hasData" class="empty large analytics-empty"><span aria-hidden="true">▥</span><h3>{{ preferences.demo ? '当前筛选没有模拟公告' : '当前范围尚无公开公告' }}</h3><p>{{ preferences.demo ? '试试清除筛选条件，查看完整模拟样本。' : '管理员采集、核验或导入公告后，这里会显示真实分布。可以先切换模拟演示体验六种图表。' }}</p><button v-if="!preferences.demo" class="button" @click="setDemo(true)">体验模拟演示</button><button v-else class="button" @click="reset">清除筛选</button></div>
      <template v-else>
        <div class="analytics-toolbar"><p><span class="analytics-live-dot"></span>{{ preferences.demo ? '模拟机会' : '公开公告' }} · 共 {{ summary.opportunities }} 条 <span class="muted">统计生成于 {{ generated }}（UTC+9）</span></p><div class="analytics-tools"><div class="analytics-view-switch" role="group" aria-label="统计呈现方式"><button :class="{ active: view === 'charts' }" @click="view = 'charts'">图表</button><button :class="{ active: view === 'tables' }" @click="view = 'tables'">表格</button></div><button class="ghost" @click="exportCsv">导出统计 CSV ↓</button></div></div>
        <section class="panel analytics-drilldown"><div class="panel-heading"><h2>把图表里的线索，追到具体机会</h2><button class="ghost" @click="shareAnalysis">复制当前分析链接</button></div><p class="data-note">点击路径、城市、月份图可联动筛选；点击技能或热力格可查看原始机会。以下按钮提供相同的键盘操作。</p><p v-if="interaction" role="status" class="data-note">{{ interaction }}</p><label v-if="sharedLink">当前分析链接<input :value="sharedLink" readonly @focus="$event.target.select()"></label><div class="analytics-drill-group" role="group" aria-label="按发展路径联动"><button v-for="(item,index) in pathRows" :key="item.key" class="tag" :aria-label="`按发展路径筛选${item.label}`" @click="selectPath({dataIndex:index})">{{ item.label }} · {{ item.count }}</button></div><div class="analytics-drill-group" role="group" aria-label="按城市联动"><button v-for="(item,index) in cityRows.slice(0,12)" :key="item.key" class="tag neutral" :disabled="item.key === '未知'" :aria-label="`按城市筛选${item.label}`" @click="selectCity({dataIndex:index})">{{ item.label }} · {{ item.count }}</button></div><div class="analytics-drill-group" role="group" aria-label="按发布月份联动"><button v-for="(item,index) in monthRows" :key="item.month" class="tag neutral" :aria-label="`按发布月份筛选${item.month}`" @click="selectMonth({dataIndex:index})">{{ item.month }} · {{ item.count }}</button></div><div class="analytics-drill-group" role="group" aria-label="从技能查看机会"><button v-for="item in skillRows.slice(0,12)" :key="item.key" class="tag amber" :aria-label="`查看要求${item.label}的机会`" @click="inspectSkill(item.key)">{{ item.label }} ↗</button></div><p class="data-note">{{ appliedScope.city ? `城市：${appliedScope.city} · ` : '' }}{{ appliedScope.path ? `路径：${paths[appliedScope.path]} · ` : '' }}{{ appliedScope.start_date || appliedScope.end_date ? `发布日：${appliedScope.start_date || '不限'} 至 ${appliedScope.end_date || '不限'}` : '发布日期不限' }}。技能钻取包含过期公告，与图表统计范围一致；申请前核对截止时间。</p><button class="ghost" @click="reset">清除联动筛选</button></section><section class="panel analytics-quality"><div class="panel-heading"><h2>先看字段是否齐全，再解释图表</h2><span class="tag">当前 {{ data.quality?.denominator ?? summary.opportunities }} 条公告</span></div><p class="data-note">{{ data.quality?.definition }}</p><div class="table-scroll"><table aria-label="公告字段完整性"><thead><tr><th>字段</th><th>已知 / 总公告</th><th>缺失</th><th>字段覆盖率</th></tr></thead><tbody><tr v-for="item in qualityRows" :key="item.key"><td>{{ item.label }}</td><td>{{ item.known }} / {{ data.quality.denominator }}</td><td>{{ item.unknown }}</td><td>{{ item.coverage == null ? '暂无分母' : `${(item.coverage*100).toFixed(1)}%` }}</td></tr></tbody></table></div><p class="data-note">仍需核对完整资格：{{ data.quality?.qualification_review }} 条。覆盖率仅描述信息缺失，不能代表数据准确率、模型准确率或个人录用概率。</p></section><div class="analytics-chart-grid">
          <section class="panel analytics-chart-card"><div class="analytics-card-head"><div><span class="analytics-chart-number">01 / 环形图</span><h2>机会的路径构成</h2></div><span class="tag">条公告</span></div><Chart v-if="view === 'charts' && pathRows.length" :option="pie" label="机会公告发展路径占比" @select="selectPath"/><div v-else-if="view === 'tables'" class="table-scroll"><table><caption class="analytics-sr-only">发展路径公告数量</caption><thead><tr><th scope="col">路径</th><th scope="col">公告</th><th scope="col">占比</th></tr></thead><tbody><tr v-for="item in pathRows" :key="item.key"><td>{{ item.label }}</td><td>{{ item.count }}</td><td>{{ (item.count / summary.opportunities * 100).toFixed(1) }}%</td></tr></tbody></table></div><div v-else class="empty">暂无路径数据</div><p class="analytics-chart-note">每条公告归属一条发展路径，分母为当前 {{ summary.opportunities }} 条公告。点击图例可聚焦某一路径。</p></section>
          <section class="panel analytics-chart-card"><div class="analytics-card-head"><div><span class="analytics-chart-number">02 / 横向条形图</span><h2>机会集中在哪些城市</h2></div><span class="tag">条公告</span></div><Chart v-if="view === 'charts' && cityRows.length" :option="cityBar" label="机会公告城市数量排名" @select="selectCity"/><div v-else-if="view === 'tables'" class="table-scroll"><table><thead><tr><th scope="col">城市</th><th scope="col">公告</th></tr></thead><tbody><tr v-for="item in cityRows" :key="item.key"><td>{{ item.label }}</td><td>{{ item.count }}</td></tr></tbody></table></div><div v-else class="empty">暂无城市数据</div><p class="analytics-chart-note">图表展示前 12 个城市，表格与导出包含全部。缺失城市显示为待核对。</p></section>
          <section class="panel analytics-chart-card"><div class="analytics-card-head"><div><span class="analytics-chart-number">03 / 折线图</span><h2>公告发布时间分布</h2></div><span class="tag">条公告 / 月</span></div><Chart v-if="view === 'charts' && monthRows.length" :option="monthlyLine" label="各月发布机会公告数量" @select="selectMonth"/><div v-else-if="view === 'tables'" class="table-scroll"><table><thead><tr><th scope="col">发布月份</th><th scope="col">公告</th></tr></thead><tbody><tr v-for="item in monthRows" :key="item.month"><td>{{ item.month }}</td><td>{{ item.count }}</td></tr></tbody></table></div><div v-else class="empty">暂无可统计的发布日期</div><p class="analytics-chart-note">{{ datedCount }} 条有发布日期，{{ Math.max(0, summary.opportunities - datedCount) }} 条日期待核对；缺失日期不补造月份。这是公告发布分布，采集覆盖会影响曲线。</p></section>
          <section class="panel analytics-chart-card"><div class="analytics-card-head"><div><span class="analytics-chart-number">04 / 堆叠柱状图</span><h2>城市与路径交叉观察</h2></div><span class="tag">条公告</span></div><Chart v-if="view === 'charts' && matrixRows.length" :option="stacked" label="各城市不同发展路径公告数量" @select="selectStack"/><div v-else-if="view === 'tables'" class="table-scroll"><table><thead><tr><th scope="col">城市</th><th scope="col">路径</th><th scope="col">公告</th></tr></thead><tbody><tr v-for="(item, index) in matrixRows" :key="index"><td>{{ item.city }}</td><td>{{ item.path }}</td><td>{{ item.count }}</td></tr></tbody></table></div><div v-else class="empty">暂无城市与路径交叉数据</div><p class="analytics-chart-note">展示公告数量最多的 {{ matrix.cities?.length || 0 }} 个城市，各色为对应路径。点击图例可筛看某条路径，数量不代表招聘名额。</p></section>
          <section class="panel analytics-chart-card"><div class="analytics-card-head"><div><span class="analytics-chart-number">05 / 热力图</span><h2>各城市关注的技能</h2></div><span class="tag">条公告提及</span></div><Chart v-if="view === 'charts' && heatRows.length" :option="heatmap" label="城市和技能公告提及数量热力图" @select="selectHeat"/><div v-else-if="view === 'tables'" class="table-scroll"><table><thead><tr><th scope="col">城市</th><th scope="col">技能</th><th scope="col">提及公告</th></tr></thead><tbody><tr v-for="(item, index) in heatRows" :key="index"><td>{{ item.city }}</td><td>{{ item.skill }}</td><td>{{ item.count }}</td></tr></tbody></table></div><div v-else class="empty">暂无已标注技能，采集文本须核验后才纳入</div><p class="analytics-chart-note">展示前 {{ heat.cities?.length || 0 }} 个城市与前 {{ heat.skills?.length || 0 }} 项技能。颜色越深，提及该技能的公告越多；一条公告可含多项技能。</p></section>
          <section class="panel analytics-chart-card"><div class="analytics-card-head"><div><span class="analytics-chart-number">06 / 矩形树图</span><h2>技能需求的相对构成</h2></div><span class="tag">条公告提及</span></div><Chart v-if="view === 'charts' && skillRows.length" :option="treemap" label="机会公告技能提及数量矩形树图" @select="event=>inspectSkill(event.name)"/><div v-else-if="view === 'tables'" class="table-scroll"><table><thead><tr><th scope="col">技能</th><th scope="col">提及公告</th></tr></thead><tbody><tr v-for="item in skillRows" :key="item.key"><td>{{ item.label }}</td><td>{{ item.count }}</td></tr></tbody></table></div><div v-else class="empty">暂无技能标签</div><p class="analytics-chart-note">面积按技能提及公告数绘制，展示前 18 项；当前共 {{ totalSkills }} 次技能提及。同一公告内同一技能只计一次。</p></section>
        </div>
        <section class="panel analytics-source-panel"><div><span class="analytics-chart-number">DATA PROVENANCE</span><h2>来源与统计边界</h2><p>{{ data.notice || '仅统计当前筛选范围内最新版本的已导入公告。' }}</p></div><ul v-if="sourceRows.length"><li v-for="(item, index) in sourceRows" :key="`${item.name}-${index}`"><span>{{ item.name || '来源待核对' }}</span><strong>{{ item.count }} 条</strong></li></ul><p v-else>暂无来源统计</p><div class="analytics-source-footer">已确认过期 {{ summary.total_expired ?? 0 }} 条 · 截止日期待核对 {{ summary.deadline_unknown ?? 0 }} 条。所有图表含当前范围内已过期公告；申请前请查看原始公告并核对资格与截止日期。</div></section>
        <section class="analytics-next-step"><div><span class="analytics-kicker">下一步，把范围缩小到适合自己</span><h2>看完机会，再比较你的选择。</h2><p>将个人画像、偏好和准备成本放在一起，逐项比较发展路径。</p></div><RouterLink class="button" to="/decisions">打开职业决策工作台 →</RouterLink></section>
      </template>
    </template>
  </div>
</template>

<style scoped>
.analytics-drill-group{display:flex;gap:7px;flex-wrap:wrap;margin:11px 0}.analytics-drill-group button{cursor:pointer;white-space:normal;text-align:left}.analytics-drill-group button:hover{outline:1px solid #a8bd9b}.analytics-drill-group button:disabled{cursor:default}.analytics-drilldown .panel-heading{flex-wrap:wrap;gap:10px}.analytics-drilldown input{font-size:11px;min-width:0}.analytics-quality table{font-size:12px}.analytics-quality .data-note,.analytics-drilldown .data-note{line-height:1.9;overflow-wrap:anywhere}
</style>
