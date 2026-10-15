<script setup>
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { api, paths, preferences, displayDate } from '../api'

const snapshot = ref(null), selected = ref([]), loading = ref(true), error = ref(''), message = ref('')
const preferredCityOnly = ref(false)
const dataKind = computed(() => preferences.demo ? 'demo' : 'public')
const chosen = computed(() => snapshot.value?.skills.filter(item => selected.value.includes(item.skill)) || [])
const stateLabels = { unknown: '尚未判断能力', self_reported: '已自报 · 可巩固', not_reported: '尚未自报 · 可探索' }
const exclusionLabels = { intent: '意向路径不符', expired: '已明确过期', major: '已知专业不符', degree: '已知学历不符', city: '城市筛选不符或未知' }
let epoch = 0
function current(generation, kind) { return generation === epoch && kind === dataKind.value }
async function load() {
  const generation = ++epoch, kind = dataKind.value
  snapshot.value = null; selected.value = []; loading.value = true; error.value = ''; message.value = ''
  try {
    const value = await api(`/skills/roadmap?data_kind=${kind}&preferred_city_only=${preferredCityOnly.value}`)
    if (!current(generation, kind)) return
    if (value.data_kind !== kind) throw new Error('返回记录与当前数据模式不一致，请重新加载。')
    snapshot.value = value
    selected.value = value.skills.slice(0, 1).map(item => item.skill)
  } catch (e) { if (current(generation, kind)) error.value = e.message }
  finally { if (current(generation, kind)) loading.value = false }
}
function selectSkill(skill) {
  message.value = ''
  if (selected.value.includes(skill)) selected.value = selected.value.filter(value => value !== skill)
  else if (selected.value.length < 3) selected.value.push(skill)
  else message.value = '一次选择1–3项即可。先完成小成果，再扩展练习范围。'
}
function opportunityLink(item) {
  const query = { data_kind: dataKind.value, skill: item.skill }
  if (preferredCityOnly.value && snapshot.value?.profile_state.cities.length === 1) query.city = snapshot.value.profile_state.cities[0]
  if (snapshot.value?.profile_state.intents.length === 1) query.path = snapshot.value.profile_state.intents[0].key
  return { path: '/opportunities', query }
}
function comparisonLink(item) { return { path: '/decisions', query: { ids: item.evidence.slice(0, 6).map(record => record.id).join(',') } } }
function markdownText(value) { return String(value).replace(/[\r\n]/g, ' ').replace(/[\\`*_{}\[\]<>#!|]/g, '\\$&') }
function markdownUrl(value) { return String(value).replace(/\(/g, '%28').replace(/\)/g, '%29').replace(/ /g, '%20') }
function exportPlan() {
  if (!chosen.value.length || !snapshot.value) return
  const value = snapshot.value
  const lines = ['# 我的两周技能尝试计划', '', `数据范围：${value.data_kind === 'demo' ? '模拟演示' : '公开公告'}；统计日期：${value.scope.as_of}；画像 V${value.profile_state.version}。`,
    '', value.notice, '', `符合本次口径 ${value.summary.qualifying_records} 条，其中 ${value.summary.known_skill_records} 条列出了技能要求。`,
    '', `统计规则：${value.scope.counting_rule}`, '', '## 我选择的练习']
  for (const item of chosen.value) {
    lines.push('', `### ${markdownText(item.skill)}`, '', `${stateLabels[item.state]}；${item.count}/${item.known_skill_denominator} 条已列技能的机会提及。`,
      '', `练习：${markdownText(item.recipe.practice)}`, '', `成果：${markdownText(item.recipe.artifact)}`, '', `验证：${markdownText(item.recipe.verification)}`,
      '', '学习资料：')
    if (!item.recipe.resources.length) lines.push('- 请先向老师或领域内从业者确认术语与可靠资料。')
    for (const resource of item.recipe.resources) lines.push(`- [${markdownText(resource.title)}](${markdownUrl(resource.url)})`)
    lines.push('', `来源证据（展示 ${item.evidence.length}/${item.evidence_total} 条）：`)
    for (const record of item.evidence) lines.push(`- #${record.id} V${record.version} [${markdownText(record.title)}](${markdownUrl(record.source_url)})；截止 ${record.deadline || '未知，需核对'}。`)
  }
  lines.push('', '## 两周安排')
  for (const stage of value.schedule) lines.push('', `### ${stage.days} · ${stage.title}`, '', stage.detail)
  lines.push('', '## 第14天复盘', '', '- 我完成的成果与保存位置：', '- 验证结果和反馈：', '- 仍然未知的部分：', '- 我准备怎样调整画像或机会选择：', '')
  const url = URL.createObjectURL(new Blob([lines.join('\n')], { type: 'text/markdown;charset=utf-8' }))
  const anchor = document.createElement('a')
  anchor.href = url; anchor.download = `my-skill-plan-${value.data_kind}-${value.scope.as_of}.md`
  document.body.appendChild(anchor); anchor.click(); anchor.remove()
  setTimeout(() => URL.revokeObjectURL(url), 1000)
  message.value = '已导出你的练习计划与来源依据。选择只在本页保留，不会自动改写画像。'
}
function printPlan() { window.print() }
watch(() => preferences.demo, () => { ++epoch; load() }, { flush: 'sync' })
watch(preferredCityOnly, load)
onMounted(load)
onBeforeUnmount(() => { ++epoch })
</script>

<template>
  <div class="skill-roadmap">
    <div class="page-heading"><div><div class="eyebrow">FROM EVIDENCE TO PRACTICE</div><h1>把机会线索，变成一份小成果<span class="heading-dot">.</span></h1><p>先看当前意向机会提到什么，再自主挑选1–3项，两周内做一次有证据的尝试。</p></div><RouterLink class="button" to="/profile">更新我的画像 ↗</RouterLink></div>
    <div v-if="preferences.demo" class="alert demo">当前使用模拟机会展示学习路线，技能频次不代表真实市场需求。</div>
    <div v-if="error" class="alert error" role="alert">{{ error }} <RouterLink to="/profile">查看个人画像 ↗</RouterLink><button class="ghost" @click="load">重新加载</button></div>
    <div v-if="message" class="alert success" role="status">{{ message }}</div>
    <section class="panel roadmap-controls" aria-label="学习路线范围">
      <div class="panel-heading"><h2>1 · 先明确这次的范围</h2><RouterLink to="/journey">回看完整使用路线 ↗</RouterLink></div>
      <p class="muted">自动沿用你当前画像的发展意向，并排除明确过期或已知专业、学历不符的条目；缺失条件继续保留为待核对。</p>
      <label class="choice"><input v-model="preferredCityOnly" type="checkbox" :disabled="loading">只看画像中的偏好城市（未知城市也会排除）</label>
      <p v-if="loading" role="status" class="empty">正在整理你的机会依据与练习建议…</p>
      <template v-else-if="snapshot"><div class="roadmap-context"><span class="tag">画像 V{{ snapshot.profile_state.version }}</span><span class="tag neutral">{{ snapshot.profile_state.intents.map(item=>item.label).join('、') }}</span><span class="tag neutral">{{ snapshot.scope.preferred_city_only ? `城市：${snapshot.profile_state.cities.join('、')}` : '城市不作硬筛选' }}</span></div><p class="data-note">统计截至 {{ snapshot.scope.as_of }} · {{ snapshot.rule_version }} · {{ snapshot.scope.version_rule }}</p></template>
    </section>
    <template v-if="snapshot">
      <section class="roadmap-stat-grid" aria-label="本次技能统计口径"><article class="panel"><strong>{{ snapshot.summary.qualifying_records }}</strong><span>符合当前口径的条目</span></article><article class="panel"><strong>{{ snapshot.summary.known_skill_records }}</strong><span>列出技能要求的条目</span></article><article class="panel"><strong>{{ snapshot.summary.skill_requirements_unknown }}</strong><span>技能要求未知的条目</span></article><article class="panel"><strong>{{ snapshot.summary.needs_review }}</strong><span>仍需原文核对的条目</span></article></section>
      <section class="panel roadmap-method"><details><summary>这些数字从哪里来？查看范围、去重和排序规则</summary><p>{{ snapshot.scope.population }}</p><p>{{ snapshot.scope.counting_rule }}</p><p>{{ snapshot.scope.priority_rule }}</p><p>最新条目 {{ snapshot.summary.all_latest_records }}；排除 {{ snapshot.summary.excluded_records }}；截止日期未知 {{ snapshot.summary.deadline_unknown }}。</p><ul v-if="Object.keys(snapshot.summary.exclusion_reasons).length"><li v-for="(count,key) in snapshot.summary.exclusion_reasons" :key="key">{{ exclusionLabels[key] || key }}：{{ count }}</li></ul><p class="muted">{{ snapshot.scope.exclusion_note }} 每项技能频次只适用于本次已采集条目，不等于完整市场需求。</p></details></section>
      <div v-if="snapshot.profile_state.skills_unknown" class="alert demo">你尚未填写技能，因此这里提供探索线索，不判断你缺少哪些能力。可以从课程作业、练习或作品中补充自报依据。</div>
      <section v-if="!snapshot.skills.length" class="panel empty roadmap-empty"><h2>{{ snapshot.summary.qualifying_records ? '当前机会还没有结构化技能要求' : '当前范围还没有可用的机会线索' }}</h2><p>{{ snapshot.data_kind === 'public' ? '可等待管理员采集公开公告，或调整画像与城市筛选。真实数据为空时不会混入模拟数据。' : '可以调整画像意向与城市范围，或请管理员补充模拟条目验证流程。' }}</p><div class="actions"><RouterLink class="button small" to="/opportunities">查看机会 →</RouterLink><RouterLink class="ghost" to="/profile">调整画像 ↗</RouterLink></div></section>
      <section v-else class="roadmap-selection" aria-label="选择学习技能">
        <div class="panel-heading"><div><h2>2 · 从最多6项线索中，选1–3项尝试</h2><p class="muted">默认勾选第一项供预览，你可以按兴趣、课程安排和可投入时间调整。</p></div><span class="tag">已选 {{ selected.length }}/3</span></div>
        <div class="roadmap-skill-grid"><article v-for="item in snapshot.skills" :key="item.skill" class="panel roadmap-skill-card" :class="{chosen:selected.includes(item.skill)}"><div class="panel-heading"><label class="choice roadmap-skill-choice"><input type="checkbox" :checked="selected.includes(item.skill)" :disabled="!selected.includes(item.skill) && selected.length >= 3" @change="selectSkill(item.skill)"><strong>{{ item.skill }}</strong></label><span class="tag" :class="{amber:item.state!=='self_reported'}">{{ stateLabels[item.state] }}</span></div><p class="roadmap-frequency"><strong>{{ item.count }}<small>/{{ item.known_skill_denominator }}</small></strong> 条已列技能的机会提及 <span>（{{ Math.round(item.share*100) }}%）</span></p><p class="muted">“尚未自报”只表示画像没有这项标签，不能据此认定你不会。</p><h3>尝试什么</h3><p>{{ item.recipe.practice }}</p><h3>留下什么成果</h3><p>{{ item.recipe.artifact }}</p><h3>怎样检查</h3><p>{{ item.recipe.verification }}</p><ul v-if="item.recipe.resources.length" class="roadmap-resources"><li v-for="resource in item.recipe.resources" :key="resource.url"><a :href="resource.url" target="_blank" rel="noopener noreferrer">{{ resource.title }} ↗</a></li></ul><p v-else class="data-note">暂未配置对应官方资料，请先向老师确认术语与可靠来源。</p><details class="roadmap-evidence"><summary>查看 {{ item.count }} 条来源依据{{ item.evidence_truncated ? `（展示前${item.evidence.length}条）` : '' }}</summary><ul><li v-for="record in item.evidence" :key="record.id"><a :href="record.source_url" target="_blank" rel="noopener noreferrer">{{ record.title }} ↗</a><small>#{{ record.id }} · V{{ record.version }} · {{ paths[record.path] }} · {{ record.city || '城市未知' }} · 截止 {{ displayDate(record.deadline) }}{{ record.needs_review ? ' · 条件待核对' : '' }}</small></li></ul></details><div class="roadmap-card-links"><RouterLink :to="opportunityLink(item)">查看提及该技能的机会 ↗</RouterLink><RouterLink :to="comparisonLink(item)">用前{{ Math.min(item.evidence.length,6) }}项做决策比较 ↗</RouterLink></div></article></div>
      </section>
      <section v-if="snapshot.skills.length" class="panel roadmap-plan" aria-label="我的两周技能计划"><div class="panel-heading"><div><h2>3 · 我的两周尝试计划</h2><p>{{ chosen.length ? chosen.map(item=>item.skill).join('、') : '请先选择至少一项技能，安排属于自己的练习。' }}</p></div><div class="actions roadmap-controls"><button class="button small" :disabled="!chosen.length" @click="exportPlan">导出 Markdown 计划 ↓</button><button class="ghost" :disabled="!chosen.length" @click="printPlan">打印计划</button></div></div><ol class="roadmap-timeline"><li v-for="stage in snapshot.schedule" :key="stage.days"><span>{{ stage.days }}</span><div><h3>{{ stage.title }}</h3><p>{{ stage.detail }}</p></div></li></ol><p class="data-note">选择与预览只保留在本页；导出后可自行记录进度。需要保存长期行动状态时，可进入辅助决策生成并追踪行动计划。</p><div class="actions roadmap-controls"><RouterLink class="button small" to="/profile">把有依据的变化写入画像 →</RouterLink><RouterLink class="ghost" to="/decisions">回到辅助决策 ↗</RouterLink></div></section>
      <p class="role-notice">{{ snapshot.notice }}</p>
    </template>
  </div>
</template>
<style src="../styles/skill-roadmap.css" scoped></style>
