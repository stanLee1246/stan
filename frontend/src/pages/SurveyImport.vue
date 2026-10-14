<script setup>
import { computed, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { api } from '../api'
const instrument = ref(null), file = ref(null), inspected = ref(null), preview = ref(null), report = ref(null)
const busy = ref(false), error = ref(''), confirmed = ref(false), ignoreConfirmed = ref(false)
const config = reactive({ source_name: '', data_kind: 'demo', authorized_consent: false })
const mapping = reactive({})
let epoch = 0
const metadataFields = [['response_id','答卷编号（必选）'],['consent','本人同意授权（必选）'],['student_key','匿名标识（可选）'],['major','专业（可选）'],['graduation_year','毕业届次（可选）'],['skills','技能（可选）'],['cities','偏好城市（可选）'],['intents','发展意向（可选）']]
const questions = computed(() => instrument.value?.questions || [])
const used = computed(() => Object.values(mapping).filter(Boolean))
const unmapped = computed(() => (inspected.value?.columns || []).filter(column => !used.value.includes(column)))
const missing = computed(() => ['response_id','consent',...questions.value.map(q=>q.id)].filter(key=>!mapping[key]))
const body = computed(() => ({ ...config, ...file.value, instrument_version: instrument.value?.version || '', instrument_confirmed: confirmed.value,
  field_mapping: Object.fromEntries(Object.entries(mapping).filter(([,value])=>value)), ignore_columns: ignoreConfirmed.value ? unmapped.value : [] }))
const canPreview = computed(() => file.value && inspected.value && config.source_name.trim().length >= 2 && confirmed.value && !missing.value.length && (!unmapped.value.length || ignoreConfirmed.value) && (config.data_kind !== 'authorized' || config.authorized_consent))
watch(() => JSON.stringify(body.value), () => { epoch++; preview.value = null; report.value = null; busy.value = false })
async function chooseFile(event) {
  epoch++; file.value = null; inspected.value = null; preview.value = null; report.value = null; error.value = ''; confirmed.value = false; ignoreConfirmed.value = false
  Object.keys(mapping).forEach(key=>delete mapping[key])
  const selected = event.target.files[0]
  if (!selected) return
  if (selected.size > 1000000) { error.value = '文件须小于 1 MB；CSV 转换后最多 500 KB，每批最多 1000 条问卷。'; return }
  busy.value = true
  try {
    const bytes = new Uint8Array(await selected.arrayBuffer())
    let binary = ''; for(let offset=0;offset<bytes.length;offset+=8192) binary += String.fromCharCode(...bytes.subarray(offset,offset+8192))
    file.value = { filename: selected.name, content_base64: btoa(binary) }
    // Let local invalidation settle before the request generation is captured.
    await Promise.resolve()
    const generation = ++epoch
    const response = await api('/admin/surveys/file/inspect', { method:'POST', body:file.value })
    if (generation !== epoch) return
    inspected.value = response
    Object.assign(mapping, response.suggested_mapping)
  } catch(e) { error.value = e.message }
  finally { busy.value = false }
}
async function preflight() {
  const generation = ++epoch
  busy.value = true; error.value = ''; preview.value = null; report.value = null
  try { const result = await api('/admin/surveys/preview', {method:'POST',body:body.value}); if(generation === epoch) preview.value = result }
  catch(e) { if(generation === epoch) error.value = e.message }
  finally { if(generation === epoch) busy.value = false }
}
async function commit() {
  if(!preview.value) return
  const generation = ++epoch
  busy.value = true; error.value = ''
  try {
    const result = await api('/admin/surveys/commit', {method:'POST',body:{...body.value,preview_fingerprint:preview.value.preview_fingerprint}})
    if(generation === epoch) { report.value = result; preview.value = null }
  } catch(e) { if(generation === epoch) error.value = e.message }
  finally { if(generation === epoch) busy.value = false }
}
function downloadTemplate() {
  const keys = questions.value.map(q=>q.id)
  const csv = '\ufeff' + ['答卷编号','同意授权','专业','毕业届次',...keys].join(',') + '\r\n' + ['demo_001','是','数据科学与大数据技术','2027',...keys.map(k=>k.startsWith('I') ? '5' : '2')].join(',') + '\r\n'
  const url=URL.createObjectURL(new Blob([csv],{type:'text/csv;charset=utf-8'}));const link=document.createElement('a');link.href=url;link.download='career-survey-demo-template.csv';link.click();setTimeout(()=>URL.revokeObjectURL(url),1000)
}
onMounted(async()=>{try{instrument.value=await api('/interests/instrument')}catch(e){error.value=e.message}})
onBeforeUnmount(()=>{epoch++})
const statuses = {accepted:'可导入',duplicate:'重复跳过',rejected:'拒绝'}
const roleStatuses = {classified:'已有突出兴趣',insufficient_data:'回答不足',multiple_interests:'多种兴趣接近',exploring:'继续探索'}
</script>

<template>
  <div class="page-heading"><div><div class="eyebrow">SURVEY IMPORT STUDIO</div><h1>把问卷回答，变成可核对的数据<span class="heading-dot">.</span></h1><p>问卷星 / 腾讯问卷导出 → 对应字段 → 预检清洗 → 确认入库。</p></div><RouterLink class="button" to="/data-pipeline">查看数据加工结果 →</RouterLink></div>
  <p v-if="error" class="alert error" role="alert">{{ error }}</p>
  <ol class="import-steps" aria-label="问卷导入四步"><li :class="{active:!inspected}">1 · 选择文件</li><li :class="{active:inspected && !preview && !report}">2 · 对应题目</li><li :class="{active:preview}">3 · 预检清洗</li><li :class="{active:report}">4 · 确认入库</li></ol>
  <section class="panel"><div class="panel-heading"><h2>1 · 准备问卷文件</h2><button class="ghost" :disabled="!instrument" @click="downloadTemplate">下载模拟 CSV 模板 ↓</button></div><p>支持 CSV（UTF-8 / GB18030）和 XLSX，每批最多 1000 条。Excel 仅读第一张可见工作表；旧版 XLS 请另存为 XLSX。导入者确认数据使用授权，每条答卷也必须有本人同意列。</p><p class="data-note">本向导用于本平台的 30 题活动兴趣问卷；题目和五级选项须对应。其他调查的题目不能直接转成职业兴趣或能力分数。外部答卷不自动绑定登录学生账号。</p><div class="form-grid"><label>问卷来源名称<input v-model="config.source_name" placeholder="例如：2026秋季职业兴趣问卷" minlength="2" maxlength="120" :disabled="busy" /></label><label>问卷数据类型<select v-model="config.data_kind" :disabled="busy"><option value="demo">模拟问卷（练习流程）</option><option value="authorized">真实授权问卷</option></select></label></div><label v-if="config.data_kind === 'authorized'" class="choice"><input v-model="config.authorized_consent" type="checkbox" :disabled="busy">我确认已取得该批真实问卷的数据使用授权</label><label class="file-picker">选择问卷导出文件<input type="file" accept=".csv,.xlsx" :disabled="busy || !instrument" @change="chooseFile" /></label><p v-if="busy && !inspected" role="status">正在读取文件结构…</p><p v-if="inspected" class="alert success">{{ file.filename }} · {{ inspected.record_count }} 条答卷 · {{ inspected.encoding }} · 已排除 {{ inspected.removed_personal_columns }} 列身份或联系方式字段。文件和预检结果尚未保存。</p></section>
  <section v-if="inspected" class="panel"><div class="panel-heading"><h2>2 · 对应字段与活动兴趣题目</h2><span class="tag">{{ 30 - missing.filter(key=>questions.some(q=>q.id === key)).length }} / 30 题已对应</span></div><p class="data-note">答卷编号会按来源转换为去标识编号；同一来源与答卷编号用于重复检查。不能据此证明跨问卷是同一学生。姓名、手机等列不参与对应和存储。</p><div class="mapping-grid"><label v-for="[key,label] in metadataFields" :key="key">{{ label }}<select v-model="mapping[key]" :disabled="busy"><option value="">不导入此字段</option><option v-for="column in inspected.columns" :key="column">{{ column }}</option></select></label></div><details class="question-mapping" open><summary>对应全部 30 题 · 按实际题意逐一核对</summary><p class="data-note">选项：1 很不喜欢 / 2 不太喜欢 / 3 一般 / 4 比较喜欢 / 5 很喜欢。空白与“不了解”保留未知。编号不相同的导出列，可以按题意手动选择。</p><div class="mapping-grid"><label v-for="question in questions" :key="question.id">{{ question.id }} · {{ question.text }}<select v-model="mapping[question.id]" :aria-label="`${question.id}对应导出列`" :disabled="busy"><option value="">请选择对应题目列</option><option v-for="column in inspected.columns" :key="column">{{ column }}</option></select></label></div></details><p v-if="missing.length" class="data-note">尚未对应：{{ missing.join('、') }}</p><label v-if="unmapped.length" class="choice import-confirm"><input v-model="ignoreConfirmed" type="checkbox" :disabled="busy">确认忽略其余 {{ unmapped.length }} 列：{{ unmapped.join('、') }}</label><label class="choice import-confirm"><input v-model="confirmed" type="checkbox" :disabled="busy">我已核对这 30 题及五级选项与平台职业活动兴趣问卷对应一致</label><button class="button" :disabled="busy || !canPreview" @click="preflight">{{ busy ? '正在处理…' : '预检并查看清洗结果' }}</button></section>
  <section v-if="preview" class="panel" aria-live="polite"><div class="panel-heading"><h2>3 · 预检结果（尚未入库）</h2><span class="tag">只读预检</span></div><div class="quality-grid"><div v-for="[key,label] in [['total','输入'],['accepted','可导入'],['rejected','拒绝'],['duplicates','重复跳过']]" :key="key"><span>{{ label }}</span><strong>{{ preview.quality[key] }}</strong></div></div><p class="data-note">{{ preview.notice }}</p><div class="table-scroll"><table aria-label="问卷预检逐行报告"><thead><tr><th>文件行号</th><th>结果</th><th>回答题数</th><th>说明</th></tr></thead><tbody><tr v-for="row in preview.rows" :key="row.line"><td>{{ row.line }}</td><td>{{ statuses[row.status] }}</td><td>{{ row.answered_items ?? '—' }}</td><td>{{ row.reason }}</td></tr></tbody></table></div><p v-if="preview.rows_truncated" class="data-note">逐行预览仅显示前 100 条，顶部计数包含全部记录。</p><p class="data-note">原始文件 SHA-256：{{ preview.source_file_hash }}</p><p class="data-note">确认后只保留校验通过、明确同意的白名单数据；拒绝行不保存原始值。修改文件、来源或列对应后需要重新预检。</p><button class="button" :disabled="busy" @click="commit">{{ busy ? '正在入库…' : '确认导入并保存质量报告' }}</button></section>
  <section v-if="report" class="panel" role="status"><div class="panel-heading"><h2>4 · 导入完成 · 批次 #{{ report.batch_id }}</h2><span class="tag">{{ config.data_kind === 'demo' ? '模拟问卷' : '真实授权问卷' }}</span></div><div class="quality-grid"><div v-for="[key,label] in [['total','输入'],['accepted','已入库'],['rejected','拒绝'],['duplicates','重复跳过']]" :key="key"><span>{{ label }}</span><strong>{{ report.quality[key] }}</strong></div></div><p v-for="(item,index) in report.quality.errors" :key="index" class="error-text">第 {{ item.line }} 行：{{ item.reason }}</p><p class="data-note">同一来源的相同答卷重复导入会跳过；存在不同答案会拒绝覆盖。外部匿名答卷不会替登录学生生成兴趣答案。</p><div class="actions"><RouterLink class="button small" to="/data-pipeline">查看清洗批次与数据仓库 →</RouterLink><button class="ghost" :disabled="busy" @click="preflight">重新预检（核对重复记录）</button></div></section>
  <section class="panel"><h2>问卷星 / 腾讯问卷的导出方式</h2><ol class="export-help"><li>在问卷后台选择导出答卷明细，保留一条答卷一行的 CSV 或 XLSX 文件。</li><li>保留答卷序号、明确同意的数据授权题和本平台 30 道活动兴趣题；普通满意度问卷须另行设计分析方案。</li><li>移除文件开头的说明行，让第一行直接是列标题。Excel 把数据表放在第一张可见工作表。</li><li>按题意对应字段，检查授权与缺失情况，预检后再确认导入。模拟模板仅用于练习。</li></ol><p class="data-note">{{ instrument?.notice }}</p><RouterLink to="/admin?tab=surveys">查看现有 JSON / CSV 接口接入 →</RouterLink></section>
</template>

<style scoped>
.import-steps{display:flex;list-style:none;gap:10px;padding:0;margin:0 0 20px;flex-wrap:wrap}.import-steps li{flex:1;min-width:130px;background:#eaf0e4;color:#6a8164;border:1px solid #dae4d1;padding:12px 16px;border-radius:6px;font-size:12px}.import-steps li.active{background:#245f4f;color:white;border-color:#245f4f}.panel>p{font-size:12px;line-height:1.9}.panel>.form-grid{margin:20px 0}.file-picker{display:grid;gap:9px;margin-top:20px;max-width:550px;font-size:12px}.mapping-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:16px;margin:18px 0}.mapping-grid label{display:grid;gap:7px;font-size:12px;min-width:0}.mapping-grid select{min-width:0;width:100%}.question-mapping{border-top:1px solid var(--line);padding-top:18px;margin-top:20px}.question-mapping summary{cursor:pointer;color:#4d7055;font-size:13px}.import-confirm{align-items:flex-start;margin:20px 0;font-size:12px;overflow-wrap:anywhere}.import-confirm input{flex-shrink:0;margin-top:5px}.actions{flex-wrap:wrap}.export-help{padding-left:20px;line-height:2.2;color:var(--muted);font-size:12px}.table-scroll td{font-size:12px}table{width:100%}.data-note{overflow-wrap:anywhere}.page-heading .button{white-space:normal}@media(max-width:640px){.mapping-grid{grid-template-columns:1fr}.page-heading{flex-direction:column;align-items:flex-start}.import-steps{gap:6px}.import-steps li{min-width:115px;font-size:11px;padding:10px}.panel .button{white-space:normal}}
</style>
