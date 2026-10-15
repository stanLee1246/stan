<script setup>
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { api, displayDate, paths, preferences } from '../api'

const profile = ref(null), result = ref(null), loading = ref(true), busy = ref(false), error = ref('')
const dataKind = computed(() => preferences.demo ? 'demo' : 'public')
const hasCandidates = computed(() => result.value?.paths.some(path => path.candidate_count > 0))
let epoch = 0
const isCurrent = (generation, kind) => generation === epoch && kind === dataKind.value
async function load() {
  const generation = ++epoch, kind = dataKind.value
  loading.value = true; busy.value = false; error.value = ''; result.value = null
  try { const value = await api('/profile'); if (isCurrent(generation, kind)) profile.value = value }
  catch (e) { if (isCurrent(generation, kind)) error.value = e.message }
  finally { if (isCurrent(generation, kind)) loading.value = false }
}
async function compare() {
  const generation = ++epoch, kind = dataKind.value
  busy.value = true; error.value = ''
  try {
    const value = await api(`/experiments/recommendations?data_kind=${kind}`, { method: 'POST' })
    if (!isCurrent(generation, kind)) return
    if (value.data_kind !== kind) throw new Error('返回的数据范围与当前模式不一致，请重新运行。')
    result.value = value
  } catch (e) { if (isCurrent(generation, kind)) error.value = e.message }
  finally { if (isCurrent(generation, kind)) busy.value = false }
}
const decimal = value => value == null ? '—' : Number(value).toFixed(4)
const rank = value => value == null ? '未排序' : `第 ${value} 名`
const textStates = {query_without_corpus_terms:'画像文本尚未与本路径词表重合',document_without_terms:'机会缺少可用文本',no_shared_terms:'该机会与查询无共同词片段',shared_terms:'可查看共同词片段的贡献'}
function download(format) {
  if (!result.value || result.value.data_kind !== dataKind.value) return
  const r = result.value
  let content, type
  if (format === 'json') { content = JSON.stringify(r, null, 2); type = 'application/json' }
  else {
    const safe = value => String(value ?? '—').replaceAll('|', '\\|').replaceAll('\n', ' ')
    const lines = ['# 推荐方法对照报告', '', `模型：${r.model_version}`, `生成时间：${r.generated_at}`, `数据范围：${r.data_kind === 'demo' ? '模拟演示' : '公开来源'}`, `画像版本：V${r.profile_version}`, '', '## 查询依据', '', `技能：${r.query.skills.join('、') || '未填写'}`, `项目经历：${safe(r.query.summary || '未填写')}`, `查询指纹：${r.query.fingerprint}`, '', '## 共同范围与参数', '', `最新快照 ${r.scope.latest_in_scope} 条，实际候选 ${r.scope.evaluated_candidates} 条，上限 ${r.scope.candidate_limit} 条。`, `达到上限：${r.scope.candidate_cap_reached ? '是' : '否'}`, `IDF：${r.parameters.idf}；TF：${r.parameters.tf}；归一化：${r.parameters.normalization}`, `规则权重：${JSON.stringify(r.parameters.rule_weights)}`, '']
    for (const p of r.paths) {
      lines.push(`## ${p.label}`, '', `候选 ${p.candidate_count} 条；词表 ${p.vocabulary_size} 项；冻结语料指纹：${p.corpus_fingerprint}`, '', '| 机会 | 规则分（0–100） | 规则名次 | 文本余弦（0–1） | 文本名次 | 共同片段 |', '| --- | ---: | --- | ---: | --- | --- |')
      for (const item of p.comparisons) lines.push(`| ${safe(item.opportunity.title)} | ${safe(item.rule_score)} | ${rank(item.rule_rank)} | ${decimal(item.text_similarity)} | ${rank(item.text_rank)} | ${item.matched_terms.map(t => safe(t.term)).join('、') || '无'} |`)
      lines.push('', ...p.comparisons.map(item => `- ${safe(item.opportunity.title)}：${item.opportunity.source_url}（机会 V${item.opportunity.version}）`), '')
    }
    lines.push('## 解读边界', '', r.notice, '', ...r.limitations.map(value => `- ${value}`), '', `本次服务器耗时 ${r.metrics.elapsed_ms} ms。${r.metrics.timing_note}`, '没有真实相关性标签，准确率、Precision、Recall、NDCG 尚未评估。')
    content = lines.join('\n'); type = 'text/markdown;charset=utf-8'
  }
  const url = URL.createObjectURL(new Blob([content], { type }))
  const link = document.createElement('a'); link.href = url
  link.download = `recommendation-comparison-${r.data_kind}-profile-v${r.profile_version}.${format === 'json' ? 'json' : 'md'}`
  document.body.appendChild(link); link.click(); link.remove(); setTimeout(() => URL.revokeObjectURL(url), 1000)
}
watch(() => preferences.demo, load, { flush: 'sync' })
onBeforeUnmount(() => { ++epoch })
onMounted(load)
</script>

<template>
  <div class="page-heading"><div><div class="eyebrow">COMPARE METHODS, READ THE EVIDENCE</div><h1>推荐方法对照<span class="heading-dot">.</span></h1><p>用同一份画像和同一批候选，看看结构化条件与文本词面分别提供什么线索。</p></div><RouterLink class="button" to="/decisions">回到辅助决策 →</RouterLink></div>
  <div v-if="preferences.demo" class="alert demo">当前使用模拟机会，实验用于验证算法和业务流程，不能证明真实推荐效果。</div>
  <div v-if="error" class="alert error" role="alert">{{ error }}</div>
  <section class="panel">
    <div class="panel-heading"><h2>1 · 确认共同的比较依据</h2><span class="tag">{{ dataKind === 'demo' ? '模拟演示' : '公开来源' }}</span></div>
    <p v-if="loading" class="muted">正在读取本人画像…</p>
    <div v-else-if="!profile" class="empty"><h3>先保存个人画像</h3><p>填写能举出课程或作品依据的技能、项目经历，以及想探索的路径，再运行对照。</p><RouterLink class="button small" to="/profile">填写我的画像 →</RouterLink></div>
    <template v-else>
      <div class="experiment-inputs"><article><strong>本人画像 V{{ profile.version }}</strong><p>意向：{{ profile.intents.map(p => paths[p]).join('、') }}</p><p>技能：{{ profile.skills.join('、') || '尚未填写' }}</p><p class="query-summary">项目经历：{{ profile.summary || '尚未填写' }}</p><RouterLink to="/profile">更新画像依据 ↗</RouterLink></article><article><strong>先核对资格，再比较关联</strong><p>两种方法共同排除明确过期、专业不符、学历不足或意向之外的机会；未知条件保留待核对。各发展路径单独比较，最多分析 100 条最新可用候选。</p><p>文本查询只用技能与项目经历；专业不当作职业兴趣，问卷角色和心理特征不参与计算。</p></article></div>
      <div class="actions"><button class="button" :disabled="loading || busy" @click="compare">{{ busy ? '正在计算…' : '运行推荐方法对照 →' }}</button><span class="muted">只读取当前数据，不生成决策记录。</span></div>
    </template>
  </section>
  <section class="experiment-methods" aria-label="两种推荐方法的依据"><article class="panel"><span class="tag">方法 A · 结构化规则</span><h2>明确条件，逐项解释</h2><p>使用自报技能覆盖、城市偏好与专业条件，默认权重 0.5 / 0.3 / 0.2。至少两项有效观测才评分；未知项保留为空，并在已知项中重新分配权重。</p><strong>路径内关联分：0–100</strong></article><article class="panel"><span class="tag neutral">方法 B · TF-IDF + 余弦</span><h2>从共同词面找到线索</h2><p>使用机会标题、技能和前 4,000 字描述，在每一路径的固定候选集上建立词表。英文标识统一大小写，中文使用相邻双字片段；显示共同片段对相似度的贡献。</p><strong>文本余弦相似度：0–1</strong></article></section>
  <template v-if="result">
    <section class="panel experiment-scope"><div class="panel-heading"><h2>2 · 本次实验范围</h2><span class="tag">画像 V{{ result.profile_version }}</span></div><div class="metric-strip"><div><small>本范围最新快照</small><strong>{{ result.scope.latest_in_scope }}</strong></div><div><small>实际共同候选</small><strong>{{ result.scope.evaluated_candidates }}</strong></div><div><small>本次服务器耗时</small><strong>{{ result.metrics.elapsed_ms }} <small>ms</small></strong></div></div><p class="data-note">{{ result.scope.version_rule }}。{{ result.scope.count_note }}</p><div v-if="result.scope.candidate_cap_reached" class="alert demo">已达到 {{ result.scope.candidate_limit }} 条分析上限；结果仅代表本次候选集，排除原因统计也仅覆盖已检查记录。</div><p v-if="!result.query.evidence_present" class="alert demo">画像还没有可用的技能或项目文本。请补充经历再对照；仅填写专业不会产生文本偏好分。</p><p class="role-notice">{{ result.notice }}</p><details class="experiment-details"><summary>查看可复核的参数与数据版本</summary><p>{{ result.model_version }} · {{ result.generated_at }}</p><p>IDF = {{ result.parameters.idf }}；TF = {{ result.parameters.tf }}；{{ result.parameters.normalization }} 归一化。</p><p>查询指纹：<code>{{ result.query.fingerprint }}</code></p><p class="muted">{{ result.metrics.timing_note }}</p><ul><li v-for="(count, reason) in result.scope.excluded_reason_counts_inspected" :key="reason">{{ reason }}：{{ count }} 条</li></ul><p v-if="!Object.keys(result.scope.excluded_reason_counts_inspected).length">已检查快照中没有明确条件不符的记录。</p></details></section>
    <section v-if="!hasCandidates" class="panel empty"><h2>当前没有符合已知条件的候选</h2><p>可调整画像意向，或查看发展机会与原始来源。公开来源为空时，不会自动混入模拟记录。</p><RouterLink to="/opportunities">查看发展机会与来源 ↗</RouterLink></section>
    <section v-for="path in result.paths" :key="path.path" class="panel experiment-path"><div class="panel-heading"><h2>{{ path.label }} · 方法对照</h2><span class="tag">{{ path.candidate_count }} 条共同候选</span></div><p class="data-note">本路径词表 {{ path.vocabulary_size }} 项；查询中 {{ path.query_term_coverage.matched_distinct }}/{{ path.query_term_coverage.distinct }} 个不同片段进入词表。规则可评分 {{ path.rule_ranked_count }} 条，文本有正相似度 {{ path.text_ranked_count }} 条。相同分数并列名次。</p><p v-if="!path.candidate_count" class="empty">本次范围内暂无此路径候选。</p><div v-else class="table-scroll experiment-table" tabindex="0" :aria-label="`${path.label}推荐方法对照表`"><table><caption class="visually-hidden">同一路径同一候选集，两种方法分数和名次的对照</caption><thead><tr><th scope="col">机会与资格</th><th scope="col">规则关联分<br><small>0–100</small></th><th scope="col">词面余弦<br><small>0–1</small></th><th scope="col">依据与差异</th></tr></thead><tbody><tr v-for="item in path.comparisons" :key="item.opportunity.id"><th scope="row"><strong>{{ item.opportunity.title }}</strong><p>{{ item.opportunity.organization }} · {{ item.opportunity.city || '城市待核对' }}</p><span class="tag" :class="{amber:item.eligibility === 'needs_review'}">{{ item.eligibility === 'needs_review' ? '资格待核对' : '可进一步了解' }}</span><p class="muted">机会 V{{ item.opportunity.version }} · 截止 {{ displayDate(item.opportunity.deadline) }}</p><a :href="item.opportunity.source_url" target="_blank" rel="noopener noreferrer">核对原文 ↗</a></th><td><strong class="experiment-value">{{ item.rule_score ?? '—' }}</strong><small>{{ rank(item.rule_rank) }}</small><p v-if="item.rule_score == null" class="muted">有效观测不足两项</p></td><td><strong class="experiment-value">{{ decimal(item.text_similarity) }}</strong><small>{{ rank(item.text_rank) }}</small><p class="muted">{{ textStates[item.text_status] }}</p></td><td><p v-if="item.missing_rule_dimensions.length" class="muted">规则未知：{{ item.missing_rule_dimensions.join('、') }}</p><p v-else class="muted">规则的技能、城市和专业均有观测依据。</p><div class="experiment-terms"><span v-for="term in item.matched_terms" :key="term.term" class="tag neutral">{{ term.term }} · {{ decimal(term.contribution) }}</span><span v-if="!item.matched_terms.length" class="muted">没有可展示的共同词片段。</span></div><details class="experiment-details"><summary>查看计算依据</summary><p v-for="component in item.rule_components" :key="component.key">{{ component.label }}：{{ component.value == null ? '未知' : decimal(component.value) }}。{{ component.evidence }}</p><p>词片段贡献总和 = {{ decimal(item.contribution_sum) }}；未展示的尾部贡献 {{ decimal(item.unshown_contribution) }}。</p><p v-for="term in item.matched_terms" :key="term.term"><code>{{ term.term }}</code>：查询次数 {{ term.query_count }}，机会次数 {{ term.document_count }}，IDF {{ decimal(term.idf) }}。</p><p v-if="item.description_truncated" class="muted">此条描述超过 4,000 字，本次只分析前 4,000 字。</p></details></td></tr></tbody></table></div><details class="experiment-details"><summary>查看本路径语料指纹</summary><code>{{ path.corpus_fingerprint }}</code></details></section>
    <section class="panel"><div class="panel-heading"><h2>3 · 回看证据，再做决定</h2><span class="tag neutral">效果待真实标注验证</span></div><ul class="experiment-limits"><li v-for="limitation in result.limitations" :key="limitation">{{ limitation }}</li></ul><p class="muted">名次变化说明两种方法关注的依据不同，不能据此判定哪种方法更准确。可以回到辅助决策调整关注点并制定行动，后续用经授权的真实相关性标注评估模型。</p><div class="actions"><RouterLink class="button small" to="/decisions">带着依据做决策 →</RouterLink><button class="ghost" @click="download('md')">导出对照报告 Markdown ↓</button><button class="ghost" @click="download('json')">导出完整结果 JSON ↓</button></div><p class="muted">报告包含本人的技能与项目描述，请按需分享。</p></section>
  </template>
</template>

<style scoped>
.experiment-inputs,.experiment-methods{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:22px}.experiment-inputs{margin:20px 0}.experiment-inputs article{padding:18px;background:#f7f9f3;border:1px solid var(--line);border-radius:6px}.experiment-inputs p,.experiment-methods p{font-size:12px;line-height:1.9}.query-summary{white-space:pre-wrap;overflow-wrap:anywhere;max-height:180px;overflow:auto}.experiment-methods .panel{margin-bottom:24px}.experiment-methods h2{margin-top:15px}.metric-strip{display:flex;gap:38px;flex-wrap:wrap;margin:24px 0}.metric-strip>div{display:flex;flex-direction:column;gap:8px}.metric-strip strong{font-size:26px;font-weight:550}.metric-strip small{font-size:11px;color:var(--muted)}.experiment-details{font-size:11px;line-height:1.8;margin:15px 0;color:var(--muted)}.experiment-details summary{cursor:pointer;color:var(--green)}.experiment-details code{overflow-wrap:anywhere;white-space:normal}.experiment-table{max-width:100%;border:1px solid var(--line);border-radius:5px}.experiment-table table{min-width:760px;width:100%;table-layout:fixed}.experiment-table th:first-child{width:29%}.experiment-table th:nth-child(2),.experiment-table th:nth-child(3){width:15%}.experiment-table th:last-child{width:41%}.experiment-table th[scope=row]{font-weight:400;background:white;text-align:left}.experiment-table th,.experiment-table td{vertical-align:top;white-space:normal;overflow-wrap:anywhere;padding:18px 12px}.experiment-table p{font-size:11px;line-height:1.8;margin:7px 0}.experiment-table small{display:block;font-size:10px;color:var(--muted)}.experiment-value{display:block;font-size:23px;color:var(--green);font-weight:550;margin-bottom:6px}.experiment-terms{display:flex;flex-wrap:wrap;gap:5px;margin:10px 0}.experiment-terms .tag{font-size:10px}.experiment-limits{font-size:12px;color:var(--muted);line-height:2;padding-left:20px}.experiment-path{min-width:0}
@media(max-width:800px){.experiment-inputs,.experiment-methods{grid-template-columns:1fr;gap:12px}.experiment-methods .panel{margin-bottom:10px}.metric-strip{gap:22px}.experiment-table th,.experiment-table td{padding:12px 9px}}
</style>
