<script setup>
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { api, auth, preferences } from '../api'
const profile = ref(null), interest = ref(null), history = ref([]), error = ref(''), loading = ref(false)
let epoch = 0
const kind = computed(() => preferences.demo ? 'demo' : 'public')
const latest = computed(() => history.value.find(item => item.data_kind === kind.value))
const done = computed(() => latest.value?.action_plan?.filter(item => item.status === 'done').length || 0)
const total = computed(() => latest.value?.action_plan?.length || 0)
const steps = computed(() => [
  { title: '了解自己', to: '/profile', action: profile.value ? '更新我的画像' : '填写个人画像', status: profile.value ? `已保存 V${profile.value.version}` : '从这里开始', text: '填写专业、技能、城市偏好与多条发展意向，保存一个可以回溯的画像版本。', output: '个人画像、已知条件与待补信息' },
  { title: '探索兴趣', to: '/interests', action: '查看职业探索', status: interest.value?.response_id ? '已有兴趣记录' : '可选步骤', text: '自愿回答30题活动兴趣问卷，用六维兴趣与拟人化伙伴帮助自我探索；也可以跳过。', output: '兴趣解释与可自主选择的探索伙伴' },
  { title: '收集选择依据', to: '/analytics', action: '打开数据洞察', status: '随时查看', text: '先看城市、路径与技能分布，再到发展机会核对来源与条件，勾选最多6个候选。', output: '有来源的市场信息与候选清单', secondary: { to: '/opportunities', label: '筛选发展机会 →' } },
  { title: '比较与取舍', to: '/decisions', action: '进入辅助决策', status: latest.value ? `已有比较 #${latest.value.id}` : '等待首次比较', text: '说明你重视什么，比较同一路径的机会、缺失依据和技能差距，再观察改变偏好后排序是否变化。', output: '比较依据、权重敏感性与历史快照' },
  { title: '行动后再评估', to: '/decisions#action-plan', action: '查看行动与历史', status: total.value ? `${done.value} / ${total.value} 项已完成` : '比较后生成', text: '执行两周行动清单，记录进度。获得新技能或发现新要求后更新画像，再生成一份比较。', output: '行动进度与新一轮决策依据' },
])
async function load() {
  const id = ++epoch
  profile.value = null; interest.value = null; history.value = []; error.value = ''
  if (!auth.user) { loading.value = false; return }
  loading.value = true
  const results = await Promise.allSettled([api('/profile'), api('/profile/roles'), api('/decisions/history')])
  if (id !== epoch) return
  if (results[0].status === 'fulfilled') profile.value = results[0].value
  if (results[1].status === 'fulfilled') interest.value = results[1].value
  if (results[2].status === 'fulfilled') history.value = results[2].value
  if (results.some(item => item.status === 'rejected')) error.value = '部分进度未能读取，请重试；各功能仍可从下面的入口打开。'
  loading.value = false
}
watch(() => auth.user?.id, load)
onMounted(load)
onBeforeUnmount(() => { epoch += 1 })
</script>

<template>
  <div class="page-heading"><div><div class="eyebrow">YOUR NEXT STEP</div><h1>从了解自己，到做出选择<span class="heading-dot">.</span></h1><p>每一步都有输入、结果和下一步；你可以随时回来调整方向。</p></div><RouterLink class="button" :to="profile ? '/decisions' : '/profile'">{{ profile ? '继续比较选择 →' : '开始填写画像 →' }}</RouterLink></div>
  <p v-if="!auth.user" class="alert demo">登录后可以保存画像、比较记录与行动进度。学校概况和数据洞察可以直接浏览。</p>
  <div v-if="error" class="alert error" role="alert">{{ error }} <button class="ghost" @click="load">重试读取进度</button></div>
  <section class="panel journey-context"><span class="tag">{{ preferences.demo ? '模拟机会流程' : '公开机会流程' }}</span><p>{{ loading ? '正在读取你的进度…' : '比较与行动进度按当前数据模式展示。学校资料始终保留附件来源标记。' }}</p><RouterLink to="/school">查看已导入的高校与专业资料 →</RouterLink></section>
  <ol class="journey-list" aria-label="学生职业决策业务流程">
    <li v-for="(step, index) in steps" :key="step.title" class="panel journey-step">
      <span class="journey-number" aria-hidden="true">0{{ index + 1 }}</span><div class="journey-body"><div class="panel-heading"><h2>{{ step.title }}</h2><span class="tag">{{ step.status }}</span></div><p>{{ step.text }}</p><p class="journey-output">这一步得到：{{ step.output }}</p><div class="actions"><RouterLink class="button small" :to="step.to">{{ step.action }} ↗</RouterLink><RouterLink v-if="step.secondary" :to="step.secondary.to">{{ step.secondary.label }}</RouterLink></div></div>
    </li>
  </ol>
  <section class="panel"><h2>两种信息，一起帮助选择</h2><div class="journey-dual"><article><h3>外部依据：机会与数据</h3><p>来源、发布日期、城市、专业条件与技能要求，帮助判断有哪些选择。附件中的就业率口径待核对，不参与个人机会评分。</p></article><article><h3>个人依据：目标与取舍</h3><p>画像、兴趣、自选权重与可执行行动，帮助解释选择理由。兴趣伙伴可修改、隐藏；参考排序不代表录取或就业概率。</p></article></div></section>
  <section v-if="auth.user?.role === 'admin'" class="panel"><div class="panel-heading"><h2>管理员的数据业务流程</h2><RouterLink to="/data-pipeline">查看数据加工全景 →</RouterLink></div><ol class="journey-admin"><li>导入问卷 / 采集公告：记录来源与批次。</li><li>清洗：查看接受、拒绝、重复和缺失原因。</li><li>入仓：核对原始层、明细层和汇总层记录。</li><li>挖掘：刷新汇总与技能共现，核对样本与指标定义。</li><li>应用：查看数据洞察，并支持学生比较与行动。</li></ol><div class="actions"><RouterLink class="button small" to="/admin/surveys">导入问卷文件</RouterLink><RouterLink to="/admin?tab=crawler">采集衡阳公告 →</RouterLink><RouterLink to="/data-pipeline">查看处理结果 →</RouterLink></div></section>
</template>

<style scoped>
.journey-context{display:flex;gap:16px;align-items:center;flex-wrap:wrap}.journey-context p{flex:1;min-width:180px;font-size:12px}.journey-context a{font-size:12px}.journey-list{padding:0;list-style:none;display:grid;gap:15px}.journey-step{display:flex;gap:22px;margin:0}.journey-number{font-size:23px;color:#659079;background:#edf3e7;border-radius:10px;width:49px;height:49px;display:grid;place-items:center;flex-shrink:0}.journey-body{flex:1;min-width:0}.journey-body p{font-size:13px}.journey-output{background:#f5f7f1;padding:10px 13px;border-radius:5px;margin:13px 0;color:#526c5b}.journey-body .panel-heading{flex-wrap:wrap;gap:9px}.journey-body .actions,.actions{flex-wrap:wrap;gap:18px}.journey-dual{display:grid;grid-template-columns:1fr 1fr;gap:24px;margin-top:16px}.journey-dual p{font-size:12px;margin-top:7px}.journey-admin{line-height:2.2;color:#61766a;padding-left:20px;font-size:13px}@media(max-width:640px){.journey-step{gap:11px;padding:17px}.journey-number{width:32px;height:36px;font-size:17px}.journey-dual{grid-template-columns:1fr}.journey-body p{font-size:12px}.journey-body .button{white-space:normal}.page-heading{align-items:flex-start;flex-direction:column}}
</style>
