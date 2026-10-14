<script setup>
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { api } from '../api'
import Chart from '../components/Chart.vue'

const school = ref(null), data = ref(null), error = ref(''), loading = ref(true)
const district = ref(''), type = ref(''), university = ref(''), discipline = ref(''), level = ref(''), major = ref('')
const selected = ref(['湖南交通工程学院', '南华大学'])
const showRates = ref(false)
let alive = true
const count = value => Number(value ?? 0).toLocaleString('zh-CN')
const universities = computed(() => (data.value?.universities || []).filter(row =>
  (!district.value || row.district === district.value) && (!type.value || row.institution_type === type.value) && (!university.value.trim() || row.name.includes(university.value.trim()))))
const majors = computed(() => (data.value?.majors || []).filter(row =>
  (!discipline.value || row.discipline === discipline.value) && (!level.value || row.level === level.value) && (!major.value.trim() || row.name.includes(major.value.trim()))))
const compare = computed(() => (data.value?.universities || []).filter(row => selected.value.includes(row.name)))
const majorStudents = computed(() => majors.value.reduce((sum, row) => sum + row.students, 0))
const disciplines = computed(() => {
  const groups = new Map()
  majors.value.forEach(row => groups.set(row.discipline, (groups.get(row.discipline) || 0) + row.students))
  return [...groups].map(([name, value]) => ({ name, value })).sort((a, b) => b.value - a.value)
})
const baseChart = { textStyle: { fontFamily: 'Microsoft YaHei, sans-serif', fontSize: 10, color: '#557561' }, animationDuration: 300,
  tooltip: { trigger: 'axis', confine: true, renderMode: 'richText' } }
const schoolChart = computed(() => ({ ...baseChart, grid: { left: 10, right: 52, top: 10, bottom: 25, containLabel: true },
  xAxis: { type: 'value', name: '人', minInterval: 1 },
  yAxis: { type: 'category', inverse: true, data: universities.value.map(row => row.name), axisLabel: { width: 130, overflow: 'truncate', fontSize: 10 } },
  series: [{ name: '原文在校学生数', type: 'bar', barMaxWidth: 18, data: universities.value.map(row => row.students), itemStyle: { color: '#6b9e86' }, label: { show: true, position: 'right', formatter: '{c}' } }]
}))
const majorChart = computed(() => {
  const rows = [...majors.value].sort((a, b) => b.students - a.students).slice(0, 12)
  return { ...baseChart, grid: { left: 10, right: 45, top: 10, bottom: 25, containLabel: true },
    xAxis: { type: 'value', name: '人', minInterval: 1 }, yAxis: { type: 'category', inverse: true, data: rows.map(row => row.name), axisLabel: { width: 130, overflow: 'truncate', fontSize: 10 } },
    series: [{ name: '原文专业在读人数', type: 'bar', barMaxWidth: 18, data: rows.map(row => row.students), itemStyle: { color: '#91a475' }, label: { show: true, position: 'right' } }]
  }
})
const disciplineChart = computed(() => ({ ...baseChart, color: ['#397964', '#7e9fa5', '#b9a677', '#a28fa1', '#98ab73'],
  tooltip: { trigger: 'item', confine: true, renderMode: 'richText', formatter: '{b}：{c} 人（筛选范围内 {d}%）' },
  legend: { bottom: 0, textStyle: { fontSize: 10 } },
  series: [{ type: 'pie', radius: ['35%', '63%'], center: ['50%', '44%'], data: disciplines.value, label: { formatter: '{b}\n{c} 人', fontSize: 10 } }]
}))
function toggleCompare(name) {
  if (selected.value.includes(name)) selected.value = selected.value.filter(item => item !== name)
  else if (selected.value.length < 3) selected.value = [...selected.value, name]
}
function clearFilters() { district.value = ''; type.value = ''; university.value = ''; discipline.value = ''; level.value = ''; major.value = '' }
onMounted(async () => {
  try {
    const results = await Promise.allSettled([api('/school'), api('/school/data')])
    if (!alive) return
    if (results[0].status === 'fulfilled') school.value = results[0].value
    if (results[1].status === 'fulfilled') data.value = results[1].value
    else error.value = results[1].reason.message
  } catch (failure) { if (alive) error.value = failure.message }
  finally { if (alive) loading.value = false }
})
onBeforeUnmount(() => { alive = false })
</script>

<template>
  <div class="page-heading"><div><div class="eyebrow">SCHOOL & MAJOR EXPLORER</div><h1>高校与专业<span class="heading-dot">.</span></h1><p>先了解学校与专业，再结合自己的兴趣、能力和机会做选择。</p></div><RouterLink to="/decisions" class="button secondary">进入辅助决策 →</RouterLink></div>
  <div v-if="error" class="alert error" role="alert">{{ error }}</div>
  <div v-if="loading" class="panel" role="status">正在读取学校资料…</div>
  <template v-if="data">
    <section class="panel school-provenance">
      <span class="tag">用户提供 · 待核验</span><h2>衡阳高校资料与湖南交通工程学院专业数据</h2>
      <p>{{ data.notice }}</p><p class="muted">来源：{{ data.source.file_name }} · 原文导出时间 {{ data.source.exported_at }}（时区未注明，统计年份未给出）</p>
      <div class="school-flow" aria-label="学校资料处理流程"><span>① 保存原始导出</span><span>② 统一人数与专业字段</span><span>③ 核对明细与汇总</span><span>④ 展示并保留待核验项</span></div>
    </section>
    <div class="stat-grid school-stats">
      <article class="stat-card"><span>附件所列高校</span><strong>{{ data.summary.universities }} <small>所</small></strong><p>并非完整官方高校名录</p></article>
      <article class="stat-card"><span>附件所列在校学生合计</span><strong>{{ count(data.summary.school_students) }}</strong><p>13 所高校原文数值相加</p></article>
      <article class="stat-card"><span>附件所列教职工合计</span><strong>{{ count(data.summary.school_staff) }}</strong><p>学校整体人数，无个人资料</p></article>
      <article class="stat-card"><span>交通工程学院专业明细</span><strong>{{ data.summary.majors }} <small>个</small></strong><p>在读人数合计 {{ count(data.summary.major_students) }} 人</p></article>
    </div>
    <section class="panel school-quality"><h2>先看数据核对结果</h2><ul><li v-for="warning in data.quality.warnings" :key="warning.code">{{ warning.message }}</li></ul><p class="muted">专业数、专业总人数和 5 个学科汇总已与明细逐项核对；数学汇总一致不代表来源已经官方核实。</p></section>

    <section class="panel">
      <div class="panel-heading"><div><span class="tag">城市范围：衡阳</span><h2>探索高校 · 选择最多 3 所进行对照</h2></div><button class="ghost" @click="clearFilters">重置筛选</button></div>
      <div class="school-filters">
        <label>所在区<select v-model="district"><option value="">全部区域</option><option v-for="item in data.filters.districts" :key="item">{{ item }}</option></select></label>
        <label>办学类型<select v-model="type"><option value="">全部类型</option><option v-for="item in data.filters.institution_types" :key="item">{{ item }}</option></select></label>
        <label>高校名称<input v-model="university" placeholder="输入高校名称" /></label>
      </div>
      <p class="muted">当前显示 {{ universities.length }} 所；在校人数、教职工人数只用于了解学校规模，不代表教学质量或就业机会。对照栏保留已选高校，可逐项移除。</p>
      <div class="school-comparisons" aria-label="高校对照">
        <article v-for="row in compare" :key="row.name" class="school-compare-card"><div class="school-card-title"><h3>{{ row.name }}</h3><button class="ghost" :aria-label="`移除对照${row.name}`" @click="toggleCompare(row.name)">×</button></div><span class="tag">{{ row.institution_type }} · {{ row.district }}</span><dl><dt>原文在校学生数</dt><dd>{{ count(row.students) }} 人</dd><dt>原文教职工数</dt><dd>{{ count(row.staff) }} 人</dd><dt>建校年份</dt><dd>{{ row.founded_year }}</dd></dl><p>{{ row.description }}</p></article>
      </div>
      <p v-if="!compare.length" class="empty">勾选下方高校，即可并排查看规模、类型与学校简介。</p>
      <Chart v-if="universities.length" class="school-wide-chart" :option="schoolChart" label="附件高校在校学生人数柱状图，来源待核验" />
      <p v-else class="empty">没有符合当前筛选的高校。</p>
      <div class="table-scroll"><table aria-label="高校原始数据"><thead><tr><th>对照</th><th>高校名称</th><th>类型</th><th>所在区</th><th>在校学生（人）</th><th>教职工（人）</th><th>建校年份</th></tr></thead><tbody><tr v-for="row in universities" :key="row.id"><td><input type="checkbox" :aria-label="`对照${row.name}`" :checked="selected.includes(row.name)" :disabled="!selected.includes(row.name) && selected.length >= 3" @change="toggleCompare(row.name)" /></td><td>{{ row.name }} <span v-if="row.dataset_focus" class="tag">资料重点</span></td><td>{{ row.institution_type }}</td><td>{{ row.district }}</td><td>{{ count(row.students) }}</td><td>{{ count(row.staff) }}</td><td>{{ row.founded_year }}</td></tr></tbody></table></div>
    </section>

    <section class="panel">
      <div class="panel-heading"><div><span class="tag">湖南交通工程学院</span><h2>专业结构 · 从兴趣方向探索专业</h2></div><RouterLink class="text-link" to="/interests">了解我的职业兴趣 →</RouterLink></div>
      <p>此处仅含附件中湖南交通工程学院的 31 个专业，与上方高校筛选分别生效。人数占比以原文专业合计 12,440 人为分母，不使用学校概况的 12,000 人。</p>
      <div class="school-filters"><label>学科门类<select v-model="discipline"><option value="">全部学科</option><option v-for="item in data.filters.disciplines" :key="item">{{ item }}</option></select></label><label>专业层次<select v-model="level"><option value="">全部层次</option><option v-for="item in data.filters.levels" :key="item">{{ item }}</option></select></label><label>专业名称<input v-model="major" placeholder="例如：数据科学" /></label></div>
      <p class="muted">当前 {{ majors.length }} 个专业，{{ count(majorStudents) }} 名在读学生。图中为所选专业的人数结构；专业人数与个人适合程度没有直接对应关系。</p>
      <div v-if="majors.length" class="school-chart-grid"><div><h3>所选专业学科分布</h3><Chart :option="disciplineChart" label="筛选专业的学科在读人数分布" /></div><div><h3>所选专业人数 · 最多显示前 12 项</h3><Chart :option="majorChart" label="筛选专业在读人数前十二项柱状图" /></div></div>
      <p v-else class="empty">没有符合当前筛选的专业。</p>
      <div class="table-scroll"><table aria-label="专业明细"><thead><tr><th>专业名称</th><th>学科</th><th>层次</th><th>在读人数（人）</th><th>原文人数占比</th></tr></thead><tbody><tr v-for="row in majors" :key="row.id"><td>{{ row.name }}</td><td>{{ row.discipline }}</td><td>{{ row.level }}</td><td>{{ count(row.students) }}</td><td>{{ row.reported_student_share }}</td></tr></tbody></table></div>
      <details class="school-review" @toggle="showRates = $event.target.open"><summary>查看原文就业率与来源学科汇总（用于数据复核）</summary><div v-if="showRates"><p class="alert">原文就业率缺少毕业届次、观察日期、就业定义与人数分母。以下仅保留原值，不能计算就业人数、平均就业率或作为推荐评分。</p><div class="table-scroll"><table aria-label="待核验就业率原值"><thead><tr><th>所选专业</th><th>原文就业率</th><th>统计口径</th></tr></thead><tbody><tr v-for="row in majors" :key="row.id"><td>{{ row.name }}</td><td>{{ row.reported_employment_rate }}</td><td>待核对</td></tr></tbody></table></div><h3>原文完整学科汇总（不随筛选变化）</h3><div class="table-scroll"><table aria-label="原文学科汇总"><thead><tr><th>学科门类</th><th>专业数</th><th>在读人数</th><th>原文占比</th></tr></thead><tbody><tr v-for="row in data.source_discipline_summary" :key="row.name"><td>{{ row.name }}</td><td>{{ row.major_count }}</td><td>{{ count(row.students) }}</td><td>{{ row.reported_student_share }}</td></tr></tbody></table></div></div></details>
    </section>
    <section class="panel"><h2>资料可追溯</h2><p>保留原始表格、标准化后的高校与专业记录，以及每次核对结果。重复运行安装脚本会识别同一文件，不重复插入。</p><dl class="school-metadata"><dt>原文数据库</dt><dd>{{ data.source.database }}</dd><dt>原文数据表</dt><dd>{{ data.source.tables.join(' / ') }}</dd><dt>原文件 SHA-256</dt><dd>{{ data.source.file_sha256 }}</dd><dt>统计年份 / 时间范围</dt><dd>原文未注明</dd><dt>原文件导出时间</dt><dd>{{ data.source.exported_at }}（原文时间，无时区）</dd><dt>来源状态</dt><dd>用户上传，待独立核验</dd></dl></section>
  </template>
  <section v-if="school" class="panel"><h2>公开资料与升学就业入口</h2><p>可从下列入口补充带有年份、统计范围与分母的正式报告，逐步核验本页资料。</p><div class="source-grid"><a v-for="item in school.sources" :key="item.url" :href="item.url" target="_blank" rel="noopener noreferrer" class="source-card"><span>公开来源 ↗</span><h3>{{ item.name }}</h3><p>{{ item.url }}</p></a></div></section>
</template>

<style scoped>
.school-chart-grid>div{min-width:0}
.school-provenance h2{margin:17px 0 12px;font-size:20px}.school-provenance p,.school-quality li{line-height:1.9}.school-flow{display:flex;gap:10px;flex-wrap:wrap;margin-top:18px}.school-flow span{background:#eef3e9;padding:8px 12px;border-radius:5px;font-size:11px;color:#4a7454}.school-stats{margin-bottom:24px}.school-stats small{font-size:14px}.school-quality{border-left:4px solid #ba9b58;background:#fdfbf5}.school-quality ul{padding-left:20px;font-size:12px;color:#756d51}.school-quality li{margin:8px 0}.school-filters{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:18px;margin:20px 0}.school-filters label{min-width:0}.school-comparisons{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:14px;margin:20px 0}.school-compare-card{border:1px solid #dce6d7;background:#fafcf7;border-radius:7px;padding:17px}.school-card-title{display:flex;justify-content:space-between;align-items:start;gap:8px}.school-card-title h3{font-size:14px;line-height:1.6}.school-card-title button{font-size:22px;padding:0 5px}.school-compare-card dl{display:grid;grid-template-columns:1fr auto;font-size:11px;gap:10px;margin:19px 0}.school-compare-card dd{margin:0;color:#345c40}.school-compare-card p{font-size:11px}.school-wide-chart{height:430px;margin-top:25px}.school-chart-grid{display:grid;grid-template-columns:1fr 1fr;gap:20px;margin-top:25px}.school-chart-grid h3{font-size:13px;color:#55725d}.school-chart-grid .chart{height:365px}.school-review{margin-top:23px;padding-top:17px;border-top:1px solid #e5ecdf;font-size:12px}.school-review summary{cursor:pointer;color:#54785d;line-height:1.9}.school-review .alert{margin-top:16px;line-height:1.9}.school-review h3{margin-top:25px}.school-metadata{display:grid;grid-template-columns:150px minmax(0,1fr);font-size:12px;gap:12px;margin-top:20px}.school-metadata dd{margin:0;overflow-wrap:anywhere;color:#53735e}.school-metadata dt{color:#8d9986}table input[type=checkbox]{width:16px;height:16px;accent-color:#628255}.table-scroll{max-width:100%}
@media(max-width:1100px){.school-comparisons{grid-template-columns:1fr 1fr}.school-chart-grid{grid-template-columns:1fr}.school-stats strong{font-size:26px}}@media(max-width:640px){.school-filters{grid-template-columns:1fr}.school-comparisons{grid-template-columns:1fr}.school-metadata{grid-template-columns:1fr;gap:5px}.school-metadata dd{margin-bottom:10px}.school-provenance h2{font-size:17px}.school-flow{gap:7px}.school-flow span{font-size:10px}.school-wide-chart{height:400px}.school-stats strong{font-size:23px}.panel-heading{flex-wrap:wrap}}
</style>
