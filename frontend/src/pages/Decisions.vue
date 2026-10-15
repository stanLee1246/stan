<script setup>
import { computed, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { api, paths, preferences, displayDate } from '../api'
const route = useRoute()
let queryApplied = false
let requestEpoch = 0
const candidates = ref([]), selected = ref([]), result = ref(null), history = ref([]), historyId = ref(''), busy = ref(false), loading = ref(true), error = ref(''), message = ref(''), comparisonIsHistory = ref(false), showCandidates = ref(false)
const profile = ref(null), role = ref(null)
const profileGaps = computed(()=>[['skills','自报技能'],['cities','城市偏好']].filter(([key])=>!profile.value?.[key]?.length).map(([,label])=>label))
const sensitivityNames = {stable:'本组设置下稳定',sensitive:'会随偏好变化',insufficient_peers:'缺少同路径比较对象',insufficient_evidence:'证据不足',excluded:'条件不符，不排名'}
const weightPresets = [{label:'均衡关注',weights:{skills:50,city:50,major:50}},{label:'技能优先',weights:{skills:70,city:15,major:15}},{label:'城市优先',weights:{skills:15,city:70,major:15}}]
function applyPreset(preset){Object.assign(weights,preset.weights)}
const weights = reactive({skills:50,city:30,major:20})
const weightLabels = {skills:'技能关联',city:'城市偏好',major:'专业关联'}
const weightTotal = computed(()=>Object.values(weights).reduce((sum,n)=>sum+Number(n),0))
const normalizedWeights = computed(()=>Object.fromEntries(Object.entries(weights).map(([k,n])=>[k,weightTotal.value > 0 ? Number(n)/weightTotal.value : 0])))
const dataKind = computed(()=>preferences.demo ? 'demo' : 'public')
const visibleHistory = computed(()=>history.value.filter(h=>h.data_kind === dataKind.value))
const resultWeightTotal = computed(()=>Object.values(result.value?.weights || {}).reduce((sum,n)=>sum+Number(n),0))
const weightPercent = value => resultWeightTotal.value > 0 ? Math.round(Number(value)/resultWeightTotal.value*100) : 0
const grouped = computed(()=>Object.entries(paths).map(([path,label])=>({path,label,items:result.value?.comparisons.filter(c=>c.opportunity.path === path) || []})).filter(g=>g.items.length))
const chosenCandidates = computed(()=>selected.value.map(id=>candidates.value.find(c=>c.id === id) || {id,title:`机会 #${id}（当前来源列表中不存在，请移除后重选）`}))
const completed = computed(()=>result.value?.action_plan.filter(a=>a.status === 'done').length || 0)
const eligibilityNames = {candidate:'可进一步了解',needs_review:'资格待核对',ineligible:'存在明确条件不符'}
function isCurrent(generation, kind) { return generation === requestEpoch && kind === dataKind.value }
function acceptResult(snapshot, generation, kind) {
  if (!isCurrent(generation,kind)) return false
  if (snapshot.data_kind !== kind) throw new Error('这份记录的数据类型与当前模式不同，请切换到对应模式查看。')
  return true
}
async function load() {
  const generation = ++requestEpoch, kind = dataKind.value
  loading.value = true; busy.value = false; error.value = ''
  try {
    const [items,h,p,r] = await Promise.all([api(`/opportunities?data_kind=${kind}&include_expired=true`),api('/decisions/history'),api('/profile'),api('/profile/roles')])
    if (!isCurrent(generation,kind)) return
    candidates.value = items; history.value = h; profile.value = p; role.value = r
    if (!queryApplied) {
      queryApplied = true
      const query = [...new Set(String(route.query.ids || '').split(',').map(Number).filter(n=>Number.isInteger(n)&&n>0))]
      if (query.length) { selected.value = query.slice(0,6); showCandidates.value = true }
    }
  } catch(e) { if(isCurrent(generation,kind)) error.value = e.message }
  finally { if(isCurrent(generation,kind)) loading.value = false }
}
function toggleCandidate(id){if(selected.value.includes(id)) selected.value=selected.value.filter(n=>n!==id); else if(selected.value.length < 6) selected.value.push(id); else error.value='一次最多比较 6 个机会，请先移除一个。'}
async function compare() {
  const generation = ++requestEpoch, kind = dataKind.value
  busy.value = true; error.value = ''; message.value = ''
  try {
    const body = {weights:normalizedWeights.value}
    if (selected.value.length) body.opportunity_ids = [...selected.value]
    const snapshot = await api(`/decisions/compare?data_kind=${kind}`,{method:'POST',body})
    if (!acceptResult(snapshot,generation,kind)) return
    result.value = snapshot; historyId.value = ''; comparisonIsHistory.value = false
    const savedHistory = await api('/decisions/history')
    if (!isCurrent(generation,kind)) return
    history.value = savedHistory; message.value = '已保存本次比较与行动计划；画像和机会版本可以回溯。'
  } catch(e) { if(isCurrent(generation,kind)) error.value = e.message }
  finally { if(isCurrent(generation,kind)) busy.value = false }
}
async function showHistory() {
  if (!historyId.value) return
  const generation = ++requestEpoch, kind = dataKind.value, id = historyId.value
  busy.value = true; error.value = ''
  try {
    const snapshot = await api(`/decisions/${id}`)
    if (!acceptResult(snapshot,generation,kind)) return
    result.value = snapshot; comparisonIsHistory.value = true
  } catch(e) { if(isCurrent(generation,kind)) error.value = e.message }
  finally { if(isCurrent(generation,kind)) busy.value = false }
}
async function setAction(action,status) {
  if (!result.value || result.value.data_kind !== dataKind.value) return
  const generation = ++requestEpoch, kind = dataKind.value, runId = result.value.id
  busy.value = true; error.value = ''
  try {
    const snapshot = await api(`/decisions/${runId}/actions/${action.id}`,{method:'PATCH',body:{status}})
    if (!acceptResult(snapshot,generation,kind)) return
    result.value = snapshot
    const savedHistory = await api('/decisions/history')
    if (isCurrent(generation,kind)) history.value = savedHistory
  } catch(e) { if(isCurrent(generation,kind)) error.value = e.message }
  finally { if(isCurrent(generation,kind)) busy.value = false }
}
watch(()=>preferences.demo,()=>{
  ++requestEpoch; busy.value = false; loading.value = false
  selected.value = []; candidates.value = []; history.value = []; historyId.value = ''; result.value = null
  comparisonIsHistory.value = false; error.value = ''; message.value = ''; queryApplied = true
  load()
},{flush:'sync'})
onBeforeUnmount(()=>{ ++requestEpoch })
onMounted(load)
</script>
<template>
  <div class="page-heading"><div><div class="eyebrow">YOUR NEXT STEP, YOUR DECISION</div><h1>把选择，变成可以比较的行动<span class="heading-dot">.</span></h1><p>同一份画像，多条发展路径。看依据、核对条件、发现差距，再制定下一步计划。</p></div><RouterLink class="button" to="/profile">完善我的画像 ↗</RouterLink></div>
  <div v-if="preferences.demo" class="alert demo">当前使用模拟机会。这里只验证比较流程，不可作为真实投递或报名依据。</div><div v-if="error" class="alert error" role="alert">{{ error }}<p>没有画像时请先填写；版本变化或机会过期时，请重新筛选并生成比较。</p></div><div v-if="message" class="alert success" role="status">{{ message }}</div>
  <section class="panel decision-readiness" aria-label="决策准备检查">
    <div class="panel-heading"><h2>先确认：这次想探索什么？</h2><RouterLink to="/journey">查看完整业务流程 ↗</RouterLink></div>
    <ol class="decision-flow"><li>明确意向</li><li>核对证据</li><li>比较与取舍</li><li>行动与复盘</li></ol>
    <p v-if="loading" class="muted">正在读取你的准备情况…</p>
    <div v-else-if="!profile" class="empty"><h3>先保存一份个人画像</h3><p>选择意向路径，填写专业和学历，即可开始比较；技能和城市偏好可逐步补充。</p><RouterLink class="button small" to="/profile">填写个人画像 →</RouterLink></div>
    <template v-else>
      <div class="readiness-grid"><article><strong>发展意向 · 画像 V{{ profile.version }}</strong><p>{{ profile.intents.map(p=>paths[p]).join('、') }}</p><RouterLink to="/profile">调整意向与画像 ↗</RouterLink></article><article><strong>比较依据</strong><p>{{ profileGaps.length ? `仍可补充：${profileGaps.join('、')}。未知信息会保留为空。` : '已填写技能与城市偏好；请为自报能力准备课程或作品依据。' }}</p><RouterLink to="/analytics">先看机会分布 ↗</RouterLink></article><article><strong>兴趣探索 · 可选</strong><p>{{ role ? '已填写兴趣问卷，可用探索任务验证兴趣。' : '尚未填写兴趣问卷，仍可直接生成方案。' }}</p><RouterLink to="/interests">{{ role ? '回看兴趣依据 ↗' : '了解我的职业兴趣 ↗' }}</RouterLink></article></div>
    </template>
  </section>
  <section class="panel decision-controls"><div class="panel-heading"><h2>1 · 确定你关心的比较依据</h2><span class="tag">你可以调整</span></div><div class="actions weight-presets"><button v-for="preset in weightPresets" :key="preset.label" class="ghost" @click="applyPreset(preset)">{{ preset.label }}</button></div><div class="decision-weight-grid"><label v-for="(label,key) in weightLabels" :key="key"><span>{{ label }} <strong>{{ weightTotal ? Math.round(weights[key]/weightTotal*100) : 0 }}%</strong></span><input v-model.number="weights[key]" type="range" min="0" max="100" step="5"><small>设置值 {{ weights[key] }}</small></label></div><p class="muted">只使用已填写的技能、城市和专业；未知项不按零分处理。资格条件单独核对，兴趣角色不会替你筛掉路径。</p><p v-if="!weightTotal" class="error-text">至少保留一项非零权重。</p><hr><div class="panel-heading"><h2>2 · 选择最多 6 个机会，或直接比较当前路径</h2><button class="ghost" @click="showCandidates = !showCandidates">{{ showCandidates ? '收起机会' : '挑选比较机会' }} · 已选 {{ selected.length }}</button></div><div v-if="chosenCandidates.length" class="shortlist"><button v-for="o in chosenCandidates" :key="o.id" class="tag shortlist-tag" @click="toggleCandidate(o.id)" :aria-label="`移除${o.title}`">{{ o.title }} ×</button></div><div v-if="showCandidates" class="decision-candidates"><p v-if="loading" class="empty">正在加载机会…</p><p v-else-if="!candidates.length" class="empty">当前暂无机会；管理员可采集公开公告，或切换模拟演示。</p><label v-for="o in candidates" :key="o.id" class="choice candidate-choice"><input :checked="selected.includes(o.id)" type="checkbox" :disabled="!selected.includes(o.id) && selected.length >= 6" @change="toggleCandidate(o.id)"><span><strong>{{ o.title }}</strong><small>{{ paths[o.path] }} · {{ o.city || '城市待核对' }} · {{ o.organization }}{{ o.expired ? ' · 已过期' : '' }}</small></span></label></div><div class="actions decision-generate"><button class="button" :disabled="busy || loading || !profile || !weightTotal" @click="compare">{{ busy ? '正在处理…' : result ? '按当前画像重新比较 →' : '生成路径比较与行动计划 →' }}</button><span class="muted">{{ selected.length ? `比较 ${selected.length} 个自选机会` : '未选具体机会：比较各路径的当前候选' }}</span></div></section>
  <section v-if="visibleHistory.length" class="panel decision-history"><label>回看一次已保存的比较<select v-model="historyId" :disabled="busy" @change="showHistory"><option value="">选择历史记录</option><option v-for="h in visibleHistory" :key="h.id" :value="h.id">#{{ h.id }} · 画像 V{{ h.profile_version }} · {{ displayDate(h.generated_at) }} · {{ h.data_kind === 'demo' ? '模拟' : '公开机会' }}</option></select></label><p class="muted">历史比较保留生成时的画像、机会及规则，后续信息更新不会覆盖依据。</p></section>
  <template v-if="result">
    <section class="panel decision-summary"><div class="panel-heading"><h2>{{ comparisonIsHistory ? '已保存的历史比较' : '本次比较的出发点' }}</h2><span class="tag">画像 V{{ result.profile_version }} · #{{ result.id }}</span></div><p>{{ result.summary }}</p><p class="data-note">规则 {{ result.model_version }} · {{ displayDate(result.generated_at) }} · {{ result.data_kind === 'demo' ? '模拟数据' : '公开来源' }} · 技能 / 城市 / 专业权重 {{ Object.values(result.weights).map(w=>`${weightPercent(w)}%`).join(' / ') }}</p><p class="role-notice">{{ result.notice }}</p></section>
    <section class="decision-path-grid"><article v-for="p in result.paths" :key="p.path" class="panel decision-path-card"><div class="panel-heading"><h2>{{ p.label || paths[p.path] }}</h2><span class="tag neutral">{{ p.candidate_count }} 个候选</span></div><p>{{ p.readiness }}</p><div class="path-metrics"><span>待核对 <strong>{{ p.review_count }}</strong></span><span>已知截止日期 <strong>{{ p.known_deadlines }}</strong></span></div><div v-if="p.skill_gaps?.length" class="skill-tags"><span v-for="gap in p.skill_gaps" :key="gap.skill" class="tag amber">待探索 {{ gap.skill }} · {{ gap.count }}</span></div><ul class="compact-list"><li v-for="action in p.next_actions" :key="action">{{ action }}</li></ul></article></section>
    <section class="panel"><div class="panel-heading"><h2>3 · 逐项查看依据与条件</h2><span class="tag">只在同一路径内排序</span></div><p class="muted">参考分用于查看信息关联，不是录用概率。不同路径的分数不用于判断哪一种人生选择“更好”。</p><div v-if="!result.comparisons.length" class="empty">暂无可比较的机会。保留意向，等待新增公告，或查看下方探索行动。</div><div v-for="group in grouped" :key="group.path" class="comparison-group"><h3>{{ group.label }}</h3><article v-for="(c,index) in group.items" :key="c.opportunity.id" class="comparison-card"><div class="comparison-title"><div><span class="muted">本路径第 {{ index+1 }} 项 · 机会 V{{ c.opportunity_version }}</span><h3>{{ c.opportunity.title }}</h3><p>{{ c.opportunity.organization }} · {{ c.opportunity.city || '城市待核对' }}</p></div><div class="score"><strong>{{ c.score ?? '—' }}</strong><small>{{ c.eligibility === 'ineligible' ? '条件不符，不评分' : c.score == null ? '信息不足' : '路径内关联分' }}</small></div></div><div class="comparison-meta"><span class="tag" :class="{amber:c.eligibility !== 'candidate'}">{{ eligibilityNames[c.eligibility] || '资格待核对' }}</span><span class="muted">已观测权重 {{ weightPercent(c.observed_weight) }}%</span><span class="muted">截止 {{ displayDate(c.opportunity.deadline) }}{{ c.deadline_days == null ? '' : ` · ${c.deadline_days < 0 ? '已过期' : `剩 ${c.deadline_days} 天`}` }}</span></div><p v-for="reason in c.reasons" :key="reason" class="evidence-line">{{ reason }}</p><p v-for="reason in c.exclusion_reasons" :key="reason" class="error-text">资格限制：{{ reason }}</p><p class="muted">{{ c.qualification_note }}</p><div class="skill-tags"><span v-for="s in c.matched_skills" :key="`match-${s}`" class="tag">已填写 {{ s }}</span><span v-for="s in c.skill_gaps" :key="`gap-${s}`" class="tag amber">待补充 {{ s }}</span></div><p v-if="c.skills_unknown" class="muted">技能未填写，暂不判断技能差距。</p><details class="evidence-details"><summary>查看逐项分数与行动建议</summary><div v-for="component in c.components" :key="component.key" class="component-row"><strong>{{ component.label }}</strong><span>{{ component.value == null ? '未知' : `${Math.round(component.value*100)} / 100` }}</span><p>{{ component.evidence }}</p></div><ul class="compact-list"><li v-for="a in c.suggested_actions" :key="a">{{ a }}</li></ul></details><div class="card-footer"><span class="muted">{{ c.opportunity.data_kind === 'demo' ? '模拟示例' : '核对原文再决定' }}</span><a :href="c.opportunity.source_url" target="_blank" rel="noopener noreferrer">查看原文 ↗</a></div></article></div></section>
    <section v-if="result.sensitivity" class="panel decision-sensitivity">
      <div class="panel-heading"><h2>4 · 换一种侧重点，选择会变吗？</h2><span class="tag">权重敏感性分析</span></div>
      <p class="muted">{{ result.sensitivity.notice }}</p>
      <p v-if="!result.sensitivity.paths.length" class="empty">当前没有可比较机会。先从机会探索加入同一路径的两条记录，再观察取舍。</p>
      <article v-for="path in result.sensitivity.paths" :key="path.path" class="sensitivity-path">
        <h3>{{ path.label }} · 本次清单 {{ path.compared_count }} 项</h3><p class="data-note">{{ path.coverage_note }}</p>
        <div class="table-scroll" tabindex="0" :aria-label="`${path.label}权重敏感性比较表`"><table><caption class="visually-hidden">同一路径内各权重方案名次；横向滚动查看全部方案</caption><thead><tr><th scope="col">机会</th><th v-for="scenario in result.sensitivity.scenarios" :key="scenario.id" scope="col">{{ scenario.label }}</th><th scope="col">如何理解</th></tr></thead><tbody><tr v-for="item in path.stability" :key="item.opportunity_id"><th scope="row">{{ item.title }}</th><td v-for="scenario in result.sensitivity.scenarios" :key="scenario.id">{{ item.ranks[scenario.id] == null ? '—' : `第 ${item.ranks[scenario.id]} 名` }}</td><td><span class="tag" :class="{amber:item.status !== 'stable'}">{{ sensitivityNames[item.status] }}</span></td></tr></tbody></table></div>
        <ul class="sensitivity-explanations"><li v-for="item in path.stability" :key="item.opportunity_id"><strong>{{ item.title }}：</strong>{{ item.explanation }}</li></ul>
      </article>
      <details class="evidence-details"><summary>查看本次分析各组权重</summary><p v-for="scenario in result.sensitivity.scenarios" :key="scenario.id" class="muted">{{ scenario.label }}：{{ Object.entries(scenario.weights).map(([key,value])=>`${weightLabels[key]} ${Math.round(value/Object.values(scenario.weights).reduce((a,b)=>a+b,0)*100)}%`).join(' · ') }}</p></details>
    </section>
    <section id="action-plan" class="panel action-plan"><div class="panel-heading"><h2>5 · 我的下一步行动与复盘</h2><span class="tag">完成 {{ completed }} / {{ result.action_plan.length }}</span></div><p class="muted">先核对条件，再做两周小任务，第 14 天回看证据、调整画像并生成新方案。行动完成代表进展，不代表资格审核通过。</p><article v-for="action in result.action_plan" :key="action.id" class="action-row" :class="{done:action.status === 'done'}"><div><span class="tag neutral">{{ paths[action.path] || '共同准备' }}</span><h3>{{ action.title }}</h3><p>{{ action.detail }}</p></div><label><span class="visually-hidden">{{ action.title }}的进度</span><select :value="action.status" :disabled="busy" @change="setAction(action,$event.target.value)"><option value="todo">待开始</option><option value="doing">进行中</option><option value="done">已完成</option></select></label></article><div class="actions review-links"><RouterLink class="button small" to="/profile">把实践反馈更新到画像 →</RouterLink><RouterLink class="ghost" to="/opportunities">继续探索机会 ↗</RouterLink><RouterLink class="ghost" to="/skills">制定技能成长计划 ↗</RouterLink><RouterLink class="ghost" to="/experiments">查看推荐方法对照 ↗</RouterLink></div><div v-if="!result.action_plan.length" class="empty">暂无自动行动建议，可先补充画像或比较新机会。</div></section>
  </template>
  <section v-else class="welcome-banner decision-intro"><div><div class="overline">从看见选项，到开始行动</div><h2>每一条路，都可以认真比较。</h2><p>上方调整关注点，然后生成比较。你将看到路径机会、条件依据、技能差距和个人行动清单。</p></div><span class="role-avatar avatar-U" role="img" aria-label="探索小兔拿着地图陪你选择方向"></span></section>
</template>

<style scoped>
.decision-flow{display:flex;flex-wrap:wrap;list-style:none;padding:0;gap:8px;margin:16px 0 22px;counter-reset:flow}
.decision-flow li{counter-increment:flow;padding:9px 14px;background:#eef3e9;border-radius:5px;font-size:12px;color:#537446}
.decision-flow li::before{content:counter(flow) ' · ';font-weight:650}
.readiness-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:16px}
.readiness-grid article{background:#f8faf4;border:1px solid var(--line);padding:16px;border-radius:6px;font-size:12px}
.readiness-grid p{line-height:1.9;margin:8px 0}.readiness-grid a{font-size:11px}
.weight-presets{margin-top:12px}.weight-presets button{border:1px solid var(--line);border-radius:4px}
.sensitivity-path{margin-top:24px}.sensitivity-path .data-note{margin:10px 0}
.sensitivity-path .table-scroll{max-width:100%;border:1px solid var(--line);border-radius:5px}
.sensitivity-path th[scope=row]{font-weight:400;background:white;white-space:normal;min-width:150px;max-width:260px;overflow-wrap:anywhere}
.sensitivity-explanations{padding-left:20px;font-size:11px;color:var(--muted);line-height:1.9}.sensitivity-explanations li{margin-top:8px}
.review-links{margin-top:24px}
@media(max-width:900px){.readiness-grid{grid-template-columns:1fr}.decision-flow li{font-size:11px;padding:8px 10px}}
</style>
