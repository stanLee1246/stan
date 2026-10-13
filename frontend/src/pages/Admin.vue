<script setup>
import { onMounted, reactive, ref } from 'vue'
import { api, paths, displayDate } from '../api'
const tab = ref('imports'), batches = ref([]), pending = ref([]), events = ref([]), report = ref(null), error = ref(''), message = ref(''), busy = ref(false)
const ingestion = reactive({ source_name: '', data_kind: 'demo', authorized_consent: false, csv_content: '' })
const opportunity = reactive({ source_record_id: '', title: '', organization: '', path: 'employment', organization_type: 'other', city: '衡阳', description: '', source_url: '', data_kind: 'public', requirements_verified: false, deadline: null, published_at: null, minimum_degree: null })
const skills = ref(''), majors = ref(''), note = ref('')
const crawlerSources = ref([]), crawlerRuns = ref([]), crawlerReport = ref(null), crawlerLoading = ref(false)
const crawl = reactive({ source_id: '', limit: 5, allow_demo_fallback: false })
const surveyBatches = ref([]), surveyReport = ref(null), surveyReportKind = ref('demo'), surveyFormat = ref('csv'), surveyContent = ref(''), surveyFilename = ref('')
const surveyMapping = ref(''), surveyIgnoredColumns = ref('')
const survey = reactive({ source_name: '', data_kind: 'demo', authorized_consent: false })
const crawlerStatus = { completed: '已完成', success: '已完成', partial: '部分完成', failed: '采集失败', fallback: '模拟回退', demo_fallback: '模拟回退', running: '采集中', blocked: '来源受限', no_data: '没有可用数据' }
const qualityColumns = [['total', '输入记录'], ['accepted', '接受'], ['rejected', '拒绝'], ['duplicates', '重复跳过']]
async function loadCrawler() {
  crawlerLoading.value = true
  try {
    const [sources, runs] = await Promise.all([api('/admin/crawler/sources'), api('/admin/crawler/runs')])
    crawlerSources.value = sources; crawlerRuns.value = runs
    if (!crawl.source_id && sources.length) crawl.source_id = sources[0].id
  } catch (e) { error.value = e.message }
  finally { crawlerLoading.value = false }
}
async function loadSurveys() {
  try { surveyBatches.value = (await api('/admin/batches')).filter(b => (b.quality?.cleaning_version || b.cleaning_version) === 'survey-v1') }
  catch (e) { error.value = e.message }
}
async function selectTab(value) {
  tab.value = value; error.value = ''; message.value = ''
  if (value === 'crawler') await loadCrawler()
  if (value === 'surveys') await loadSurveys()
}
async function runCrawler() {
  busy.value = true; error.value = ''; crawlerReport.value = null
  try {
    crawlerReport.value = await api('/admin/crawler/run', { method: 'POST', body: { ...crawl, limit: Number(crawl.limit) } })
    await Promise.all([loadCrawler(), load()])
  } catch (e) { error.value = e.message }
  finally { busy.value = false }
}
async function readSurveyFile(e) {
  const file = e.target.files[0]; if (!file) return
  surveyContent.value = ''; surveyFilename.value = ''
  if (file.size > 500000) { error.value = '问卷文件请小于 500KB，每批最多 2000 条记录。'; return }
  try {
    surveyContent.value = await file.text(); surveyFilename.value = file.name
    surveyFormat.value = file.name.toLowerCase().endsWith('.json') ? 'json' : 'csv'
    error.value = ''
  } catch { error.value = '无法读取文件，请检查文件编码与访问权限。' }
}
async function importSurvey() {
  busy.value = true; error.value = ''; surveyReport.value = null
  try {
    const body = { ...survey }
    if (surveyFormat.value === 'csv') {
      body.csv_content = surveyContent.value
      if (surveyMapping.value.trim()) {
        let mapping
        try { mapping = JSON.parse(surveyMapping.value) }
        catch { throw new Error('列映射须为 JSON 对象，例如 {"student_key":"匿名编号"}。') }
        if (!mapping || Array.isArray(mapping) || typeof mapping !== 'object' || Object.values(mapping).some(x => typeof x !== 'string')) throw new Error('列映射应为标准字段到 CSV 列名的 JSON 对象。')
        body.field_mapping = mapping
      }
      body.ignore_columns = surveyIgnoredColumns.value.split(/[,，、\n]/).map(x => x.trim()).filter(Boolean)
    }
    else {
      let parsed
      try { parsed = JSON.parse(surveyContent.value) }
      catch { throw new Error('JSON 格式无效，请检查引号、逗号与括号。') }
      const records = Array.isArray(parsed) ? parsed : parsed?.records
      if (!Array.isArray(records)) throw new Error('JSON 请使用记录数组，或含 records 数组的对象。')
      body.records = records
    }
    surveyReport.value = await api(surveyFormat.value === 'csv' ? '/admin/import/surveys/csv' : '/admin/import/surveys', { method: 'POST', body })
    surveyReportKind.value = body.data_kind
    await Promise.all([loadSurveys(), load()])
  } catch (e) { error.value = e.message }
  finally { busy.value = false }
}
const qualityValue = (quality, key) => quality?.[key] ?? 0
function fillSurveyExample() {
  survey.source_name = '模拟职业规划问卷'; survey.data_kind = 'demo'; survey.authorized_consent = false
  surveyFormat.value = 'json'; surveyFilename.value = ''; surveyMapping.value = ''; surveyIgnoredColumns.value = ''
  const answers = Object.fromEntries(['R','I','A','S','E','C'].flatMap((type, index) => Array.from({ length: 5 }, (_, i) => [`${type}${i + 1}`, index === 1 ? 5 : 3])))
  surveyContent.value = JSON.stringify([{ student_key: 'demo_survey_001', response_id: 'demo_questionnaire_001', major: '计算机科学与技术', graduation_year: 2026, skills: ['Python', 'SQL'], cities: ['衡阳'], intents: ['employment', 'postgraduate'], answers, consent: true }], null, 2)
}
async function load() { try { [batches.value,pending.value,events.value] = await Promise.all([api('/admin/batches'), api('/admin/experiences'), api('/admin/audit')]) } catch(e) { error.value = e.message } }
async function readFile(e) {
  const file = e.target.files[0]; if(!file) return
  if(file.size > 500000) { error.value = 'CSV 文件请小于 500KB，每批最多2000行。'; return }
  ingestion.csv_content = await file.text(); error.value = ''
}
async function importCSV() {
  busy.value = true; error.value = ''; report.value = null
  try { report.value = await api('/admin/import/outcomes', { method: 'POST', body: ingestion }); await load() }
  catch(e) { error.value = e.message } finally { busy.value = false }
}
async function saveOpportunity() {
  busy.value = true; error.value = ''; message.value = ''
  try {
    const body = { ...opportunity, deadline: opportunity.deadline || null, published_at: opportunity.published_at || null, minimum_degree: opportunity.minimum_degree || null, skills: skills.value.split(/[,，、]/).map(x=>x.trim()).filter(Boolean), majors: majors.value.split(/[,，、]/).map(x=>x.trim()).filter(Boolean) }
    const result = await api('/admin/opportunities', { method: 'POST', body }); message.value = `机会已保存为 V${result.version}；相同来源链接与记录编号会创建新版本。`; await load()
  } catch(e) { error.value = e.message } finally { busy.value = false }
}
async function moderate(post,status) {
  try { await api(`/admin/experiences/${post.id}/moderate`, { method: 'POST', body: { status, note: note.value } }); await load() }
  catch(e) { error.value = e.message }
}
onMounted(load)
</script>
<template><div class="page-heading"><div><div class="eyebrow">DATA WORKSPACE</div><h1>让每一条数据有据可查<span class="heading-dot">.</span></h1><p>原始批次、清洗结果、版本记录与公开审核。</p></div><span class="tag">管理员</span></div><div v-if="error" class="alert error" role="alert">{{ error }}</div><div v-if="message" class="alert success">{{ message }}</div><div class="tabbar"><button v-for="[key,label] in [['imports','去向导入'],['surveys','问卷接入'],['crawler','衡阳公告采集'],['opportunities','机会录入'],['moderation','经验审核'],['audit','操作记录']]" :key="key" :class="{active:tab === key}" @click="selectTab(key)">{{ label }}</button></div><template v-if="tab === 'imports'"><form class="panel profile-form" @submit.prevent="importCSV"><h2>导入逐人去向 CSV</h2><p class="muted">使用 data/outcome-template.csv 表头，匿名标识应由数据授权方生成。不得加入姓名、学号、电话。不同来源分别统计，不直接相加。</p><div class="form-grid"><label>来源名称<input v-model="ingestion.source_name" required minlength="2" maxlength="120" placeholder="用明确名称区分样本批次来源"></label><label>数据类型<select v-model="ingestion.data_kind"><option value="demo">模拟数据</option><option value="authorized">真实授权样本</option></select></label></div><label>UTF-8 CSV 文件<input type="file" accept=".csv" @change="readFile" required></label><label v-if="ingestion.data_kind === 'authorized'" class="choice"><input type="checkbox" v-model="ingestion.authorized_consent" required>确认已取得授权、已使用随机匿名标识且不包含直接身份信息</label><button class="button" :disabled="busy || !ingestion.csv_content">{{ busy ? '导入中…' : '校验并导入' }}</button></form><section v-if="report" class="panel"><h2>本次质量报告 · 批次 #{{ report.batch_id }}</h2><div class="quality-grid"><div v-for="[key,label] in [['total','输入记录'],['accepted','接受'],['rejected','拒绝'],['duplicates','重复跳过']]" :key="key"><span>{{ label }}</span><strong>{{ report.quality[key] }}</strong></div></div><p>字段完整率 {{ (report.quality.completeness*100).toFixed(1) }}% · 校验通过率 {{ (report.quality.validation_pass_rate*100).toFixed(1) }}% · 重复率 {{ (report.quality.duplicate_rate*100).toFixed(1) }}%</p><p class="muted">解析正确率需人工抽样核对，当前未测量。规则版本：{{ report.quality.cleaning_version }}</p><p v-for="e in report.quality.errors" :key="e.line" class="error-text">第 {{ e.line }} 行：{{ e.reason }}</p></section><section class="panel table-panel"><h2>最近导入批次</h2><div class="table-scroll"><table><thead><tr><th>批次</th><th>来源</th><th>类型</th><th>接受 / 拒绝 / 重复</th><th>时间</th></tr></thead><tbody><tr v-for="b in batches" :key="b.id"><td>#{{ b.id }}</td><td>{{ b.source_name }}</td><td>{{ b.data_kind === 'demo' ? '模拟' : '授权' }}</td><td>{{ b.quality.accepted }} / {{ b.quality.rejected }} / {{ b.quality.duplicates }}</td><td>{{ displayDate(b.created_at) }}</td></tr></tbody></table></div><div v-if="!batches.length" class="empty">暂无导入批次</div></section></template>
<template v-if="tab === 'crawler'">
  <form class="panel profile-form" @submit.prevent="runCrawler">
    <div class="panel-heading"><h2>衡阳公开公告采集</h2><span class="tag">固定来源 · 可追溯</span></div>
    <p class="muted">从已登记的衡阳本地公开栏目发现公告、读取详情并清洗入库。每次仅采集少量页面，保留原文链接、运行记录和失败原因。</p>
    <div class="form-grid">
      <label>采集来源<select v-model="crawl.source_id" required :disabled="crawlerLoading || busy"><option value="" disabled>请选择来源</option><option v-for="s in crawlerSources" :key="s.id" :value="s.id">{{ s.name }}</option></select></label>
      <label>本次最多读取公告数<input v-model.number="crawl.limit" type="number" min="1" max="10" required :disabled="busy"></label>
    </div>
    <article v-for="s in crawlerSources.filter(x => x.id === crawl.source_id)" :key="s.id" class="admin-source-card">
      <h3>{{ s.name }}</h3><p class="muted">{{ s.note }}</p><a :href="s.url" target="_blank" rel="noopener noreferrer">查看公开栏目 ↗</a>
    </article>
    <label class="choice"><input v-model="crawl.allow_demo_fallback" type="checkbox" :disabled="busy">采集受限或无结果时，插入明确标注的模拟机会用于功能演示</label>
    <p class="muted">模拟机会与真实公告分别统计；模拟回退不会显示成真实采集成功。公告资格、人数与截止日期仍需核对原文。</p>
    <button class="button" :disabled="busy || crawlerLoading || !crawl.source_id">{{ busy ? '采集中，请稍候…' : '开始采集并清洗' }}</button>
  </form>
  <section v-if="crawlerReport" class="panel profile-form" aria-live="polite">
    <div class="panel-heading"><h2>本次采集报告 · #{{ crawlerReport.run_id }}</h2><span class="tag" :class="{ amber: crawlerReport.data_kind === 'demo' || crawlerReport.fallback_used }">{{ crawlerStatus[crawlerReport.status] || crawlerReport.status }}</span></div>
    <div class="quality-grid"><div v-for="[key,label] in [['accepted','新增机会'],['duplicates','重复跳过'],['rejected','拒绝记录'],['documents','保存页面']]" :key="key"><span>{{ label }}</span><strong>{{ key === 'documents' ? (crawlerReport.documents?.length ?? crawlerReport.quality?.documents ?? 0) : (crawlerReport[key] ?? 0) }}</strong></div></div>
    <div v-if="crawlerReport.fallback_used || crawlerReport.data_kind === 'demo'" class="alert demo">本次使用模拟回退。新增数据仅用于演示，不能用作真实就业或招考依据。</div>
    <p v-if="crawlerReport.quality?.note" class="muted">{{ crawlerReport.quality.note }}</p><p class="muted">结构化报名条件暂未人工核验；请查看原文确认资格与附件。</p>
    <p v-for="(item,index) in crawlerReport.errors || []" :key="index" class="error-text">{{ typeof item === 'string' ? item : item.reason || item.message }}</p>
    <div v-if="crawlerReport.documents?.length" class="table-scroll"><table><thead><tr><th>采集记录</th><th>数据类型</th><th>解析状态</th><th>原文</th></tr></thead><tbody><tr v-for="d in crawlerReport.documents" :key="d.id"><td>{{ d.title || '来源栏目' }}</td><td>{{ d.data_kind === 'demo' ? '模拟' : '公开公告' }}</td><td>{{ ({list_page:'栏目页',requirements_review:'条件待核验',duplicate:'重复跳过',rejected:'拒绝入库'})[d.parsed_status] || d.parsed_status }}</td><td><a v-if="d.source_url" :href="d.source_url" target="_blank" rel="noopener noreferrer">查看原文 ↗</a></td></tr></tbody></table></div>
  </section>
  <section class="panel table-panel">
    <div class="panel-heading"><h2>采集运行记录</h2><button class="ghost" :disabled="busy || crawlerLoading" @click="loadCrawler">刷新记录</button></div>
    <div class="table-scroll"><table><thead><tr><th>运行</th><th>来源</th><th>状态 / 类型</th><th>新增 / 重复 / 拒绝</th><th>时间</th><th>报告</th></tr></thead><tbody><tr v-for="r in crawlerRuns" :key="r.run_id"><td>#{{ r.run_id }}</td><td>{{ r.source_name || r.source_id }}</td><td>{{ crawlerStatus[r.status] || r.status }}<span v-if="r.data_kind === 'demo' || r.fallback_used" class="tag amber">模拟</span></td><td>{{ r.accepted ?? r.quality?.accepted ?? 0 }} / {{ r.duplicates ?? r.quality?.duplicates ?? 0 }} / {{ r.rejected ?? 0 }}</td><td>{{ displayDate(r.created_at || r.started_at) }}</td><td><button class="ghost" @click="crawlerReport = r">查看报告</button></td></tr></tbody></table></div>
    <div v-if="!crawlerRuns.length" class="empty">暂无采集运行记录</div>
  </section>
</template>
<template v-if="tab === 'surveys'">
  <form class="panel profile-form" @submit.prevent="importSurvey">
    <div class="panel-heading"><h2>接入职业规划调查问卷</h2><span class="tag">CSV / JSON</span></div>
    <p class="muted">上传问卷导出文件，或粘贴记录内容。使用匿名 student_key 与 response_id 区分记录；不要导入姓名、学号、手机号或邮箱。问卷样本独立统计，不直接计入毕业去向。</p>
    <div class="form-grid"><label>问卷来源名称<input v-model="survey.source_name" required minlength="2" maxlength="120" placeholder="例如：2026 届职业规划问卷"></label><label>数据类型<select v-model="survey.data_kind"><option value="demo">模拟问卷</option><option value="authorized">真实授权问卷</option></select></label></div>
    <label>本地问卷文件<input type="file" accept=".csv,.json" @change="readSurveyFile"></label>
    <p v-if="surveyFilename" class="muted">已读取 {{ surveyFilename }}；文件内容仅在提交后送至本项目后端。</p>
    <label>内容格式<select v-model="surveyFormat"><option value="csv">UTF-8 CSV（首行为表头）</option><option value="json">JSON 记录数组</option></select></label>
    <label>问卷记录内容<textarea v-model="surveyContent" rows="8" required :placeholder="surveyFormat === 'csv' ? '粘贴带表头的 CSV 内容，或选择文件' : '粘贴 JSON 数组，或含 records 数组的对象'"></textarea></label>
    <p class="muted">必填：student_key（随机匿名标识）、response_id（本来源内唯一答卷编号）、consent（同意使用）。兴趣题为 R1–R5、I1–I5、A1–A5、S1–S5、E1–E5、C1–C5，分值 1–5，缺失留空；JSON 将题目放入 answers 对象。选填专业、毕业年份、技能、城市和发展意向。</p>
    <button type="button" class="ghost" :disabled="busy" @click="fillSurveyExample">填入一份模拟问卷示例</button>
    <details v-if="surveyFormat === 'csv'" class="admin-source-card"><summary>问卷平台 CSV 列映射（可选）</summary>
      <p class="muted">表头已经使用标准字段时无需填写。中文导出表头可显式映射；无关列需在导入前删除或明确填写忽略列。</p>
      <label>标准字段 → 导出列名（JSON 对象）<textarea v-model="surveyMapping" rows="3" placeholder='{"student_key":"匿名编号","response_id":"答卷编号","consent":"同意使用","R1":"第1题"}'></textarea></label>
      <label>忽略列（逗号分隔）<input v-model="surveyIgnoredColumns" placeholder="提交时间,所用时间"></label>
    </details>
    <label v-if="survey.data_kind === 'authorized'" class="choice"><input v-model="survey.authorized_consent" type="checkbox" required>已取得问卷使用授权，使用匿名标识，且记录不包含直接身份信息</label>
    <button class="button" :disabled="busy || !surveyContent.trim()">{{ busy ? '校验中…' : '清洗并导入问卷' }}</button>
  </form>
  <section v-if="surveyReport" class="panel profile-form" aria-live="polite">
    <div class="panel-heading"><h2>问卷质量报告 · 批次 #{{ surveyReport.batch_id }}</h2><span class="tag" :class="{ amber: surveyReportKind === 'demo' }">{{ surveyReportKind === 'demo' ? '模拟问卷' : '授权问卷' }}</span></div>
    <div class="quality-grid"><div v-for="[key,label] in qualityColumns" :key="key"><span>{{ label }}</span><strong>{{ qualityValue(surveyReport.quality,key) }}</strong></div></div>
    <p class="muted">兴趣题回答完整率 {{ ((surveyReport.quality?.answer_completeness || 0) * 100).toFixed(1) }}%。规则版本：{{ surveyReport.quality?.cleaning_version || 'survey-v1' }}。重复记录跳过，非法字段与无法清洗的记录会列入拒绝报告。</p><p v-if="surveyReport.quality?.notice" class="muted">{{ surveyReport.quality.notice }}</p>
    <p v-for="(item,index) in surveyReport.quality?.errors || []" :key="index" class="error-text">第 {{ item.line || item.row || index + 1 }} 行：{{ item.reason }}</p>
  </section>
  <section class="panel table-panel">
    <div class="panel-heading"><h2>问卷导入批次</h2><button class="ghost" :disabled="busy" @click="loadSurveys">刷新记录</button></div>
    <div class="table-scroll"><table><thead><tr><th>批次</th><th>来源</th><th>类型</th><th>接受 / 拒绝 / 重复</th><th>时间</th></tr></thead><tbody><tr v-for="b in surveyBatches" :key="b.id"><td>#{{ b.id }}</td><td>{{ b.source_name }}</td><td><span class="tag" :class="{ amber: b.data_kind === 'demo' }">{{ b.data_kind === 'demo' ? '模拟' : '授权' }}</span></td><td>{{ qualityValue(b.quality,'accepted') }} / {{ qualityValue(b.quality,'rejected') }} / {{ qualityValue(b.quality,'duplicates') }}</td><td>{{ displayDate(b.created_at) }}</td></tr></tbody></table></div>
    <div v-if="!surveyBatches.length" class="empty">暂无问卷批次</div>
  </section>
  <section class="panel profile-form">
    <h2>调查系统接口接入</h2><p class="muted">接口接受管理员身份认证后的批量导入请求。外部系统需在服务端持有有效的平台管理员登录令牌，并发送 Authorization: Bearer &lt;管理员令牌&gt;；不要把令牌放入问卷公开页面。</p>
    <pre class="admin-contract">POST /api/admin/import/surveys
Content-Type: application/json

{
  "source_name": "职业规划问卷批次",
  "data_kind": "authorized",
  "authorized_consent": true,
  "records": [{
    "student_key": "random_001",
    "response_id": "survey_001",
    "answers": { "R1": 3, "I1": 5 },
    "consent": true
  }]
}</pre>
    <p class="muted">JSON 使用 records 数组；CSV 请求发送至 /api/admin/import/surveys/csv，使用 csv_content 并可附 field_mapping、ignore_columns。本页面与外部系统使用同一套清洗与重复检查规则。</p>
  </section>
</template>
<form v-if="tab === 'opportunities'" class="panel profile-form" @submit.prevent="saveOpportunity"><h2>录入已核对的机会资料</h2><div class="form-grid"><label>来源记录编号<input v-model="opportunity.source_record_id" required maxlength="80"></label><label>机会标题<input v-model="opportunity.title" required maxlength="150"></label><label>单位 / 院校<input v-model="opportunity.organization" required maxlength="150"></label><label>发展路径<select v-model="opportunity.path"><option v-for="p in ['employment','postgraduate','civil_service','public_institution','internship']" :key="p" :value="p">{{ paths[p] }}</option></select></label><label>单位性质<select v-model="opportunity.organization_type"><option value="other">其他 / 待核对</option><option value="private">民企</option><option value="state_owned">国企</option><option value="government">政府机关</option><option value="public_institution">事业单位</option><option value="university">高校</option></select></label><label>城市<input v-model="opportunity.city" maxlength="80"></label><label>截止日期<input type="date" v-model="opportunity.deadline"></label><label>发布日期<input type="date" v-model="opportunity.published_at"></label><label>最低学历<select v-model="opportunity.minimum_degree"><option :value="null">未知 / 需核对</option><option value="junior_college">专科</option><option value="bachelor">本科</option><option value="master">硕士</option><option value="doctor">博士</option></select></label><label>数据类型<select v-model="opportunity.data_kind"><option value="public">公开真实公告</option><option value="demo">模拟示例</option></select></label></div><label>技能要求（逗号或顿号分隔）<input v-model="skills"></label><label>结构化专业条件（须精确到标准名称；未知留空）<input v-model="majors"></label><label>原文 URL<input v-model="opportunity.source_url" type="url" required maxlength="255"></label><label>描述与资格说明<textarea v-model="opportunity.description" required rows="5" maxlength="10000"></textarea></label><label class="choice"><input v-model="opportunity.requirements_verified" type="checkbox">已人工核对结构化条件（复杂招考条件仍需用户核对原文）</label><button class="button" :disabled="busy">保存机会版本</button></form><section v-if="tab === 'moderation'" class="panel"><h2>待审核经验（{{ pending.length }}）</h2><label>审核说明<input v-model="note" maxlength="300" placeholder="注明依据或需修改之处"></label><div v-if="!pending.length" class="empty">暂无待审核经验</div><article v-for="p in pending" :key="p.id" class="moderation-card"><h3>{{ p.title }}</h3><p>{{ p.public_nickname }} · {{ p.graduation_year }} 届</p><p class="post-body">{{ p.body }}</p><div class="actions"><button class="button small" @click="moderate(p,'approved')">审核通过</button><button class="ghost" @click="moderate(p,'rejected')">拒绝发布</button></div></article></section><section v-if="tab === 'audit'" class="panel table-panel"><h2>最近操作记录</h2><div class="table-scroll"><table><thead><tr><th>编号</th><th>操作人 ID</th><th>操作</th><th>对象 ID</th><th>日期</th></tr></thead><tbody><tr v-for="e in events" :key="e.id"><td>{{ e.id }}</td><td>{{ e.actor_id }}</td><td>{{ e.action }}</td><td>{{ e.target_id }}</td><td>{{ displayDate(e.created_at) }}</td></tr></tbody></table></div></section></template>
