<script setup>
import { computed, ref } from 'vue'
const props = defineProps({ snapshot: { type: Object, default: null }, roles: { type: Array, default: () => [] }, editable: Boolean, busy: Boolean })
const emit = defineEmits(['display'])
const selecting = ref(false)
const fallback = [
  {code:'R',name:'实干小浣熊',tags:['动手实践','搭建验证']}, {code:'I',name:'研究小猫头鹰',tags:['追问原因','分析验证']},
  {code:'A',name:'创意小狐狸',tags:['创意表达','多种可能']}, {code:'S',name:'协作小金毛',tags:['支持他人','共同成长']},
  {code:'E',name:'开拓小狮子',tags:['发起行动','推动合作']}, {code:'C',name:'规划小企鹅',tags:['条理清晰','细节可靠']},
  {code:'U',name:'探索小兔',tags:['多路试探','允许未定']},
]
const allRoles = computed(() => props.roles.length ? props.roles : fallback)
const roleCode = value => typeof value === 'string' ? value.split('_')[0] : value?.code
const code = computed(() => roleCode(props.snapshot?.display_role || props.snapshot?.primary_role))
const current = computed(() => allRoles.value.find(r=>r.code === code.value))
const secondary = computed(() => allRoles.value.find(r=>r.code === roleCode(props.snapshot?.secondary_role)))
const retainedOverride = computed(() => props.snapshot?.manual_override ? props.snapshot.display_role : null)
const stateNames = {insufficient_data:'回答尚不完整',exploring:'正在探索',multiple_interests:'多方向兴趣',highlighted_interest:'当前偏好'}
function display(display_role, hidden = false) { emit('display',{display_role,hidden}); selecting.value = false }
</script>
<template>
  <section class="panel role-panel">
    <div class="panel-heading"><h2>我的职业探索伙伴</h2><span class="tag neutral">{{ snapshot ? (stateNames[snapshot.status] || '当前兴趣倾向') : '还未填写兴趣问卷' }}</span></div>
    <div v-if="snapshot?.hidden" class="role-hidden"><p>你已隐藏探索伙伴。问卷与原始结果仍仅本人可见。</p><button v-if="editable" class="ghost" :disabled="busy" @click="display(retainedOverride, false)">重新显示伙伴</button></div>
    <template v-else>
      <div v-if="current" class="role-intro"><span class="role-avatar" :class="`avatar-${current.code}`" role="img" :aria-label="`${current.name}的动物拟人化形象`"></span><div><span class="overline">{{ snapshot?.manual_override ? '你选择的展示伙伴' : '当前兴趣倾向' }}</span><h3>{{ current.name }}</h3><div class="skill-tags"><span v-for="t in current.tags || []" :key="t" class="tag">{{ t }}</span></div><p v-if="secondary">辅助兴趣：{{ secondary.name }}</p><p v-if="snapshot?.manual_override" class="muted">自主选择只改变头像展示，不修改问卷分数。</p></div></div>
      <div v-else class="role-intro"><span class="role-avatar avatar-U" role="img" aria-label="探索小兔邀请你认识职业活动"></span><div><h3>{{ snapshot?.status === 'insufficient_data' ? '先补充一些回答' : '从一次小探索开始' }}</h3><p>{{ snapshot?.status === 'insufficient_data' ? '六维回答不足，暂不自动判断兴趣角色。你仍可选择喜欢的伙伴。' : '完成自愿兴趣问卷后，看看你当前更喜欢哪些职业活动。' }}</p></div></div>
      <div v-if="snapshot?.reasons?.length" class="role-explanation"><p v-for="reason in snapshot.reasons" :key="reason">{{ reason }}</p></div>
      <p class="role-notice">角色描述当前活动兴趣，允许变化和重叠；不是固定人格、能力测验或岗位资格判断。</p>
      <p v-if="snapshot" class="data-note">本次兴趣来自画像 V{{ snapshot.profile_version }} 对应的问卷。个人信息更新后，可自愿重新填写以记录兴趣变化。</p>
      <div v-if="snapshot?.actions?.length" class="role-steps"><h3>试一试这些小行动</h3><ul><li v-for="action in snapshot.actions" :key="action">{{ action }}</li></ul></div>
      <div class="actions"><RouterLink class="button small" to="/interests">{{ snapshot ? '查看与更新兴趣问卷 →' : '认识我的兴趣伙伴 →' }}</RouterLink><button v-if="editable && snapshot" class="ghost" :disabled="busy" @click="selecting = !selecting">选择展示伙伴</button><button v-if="editable && snapshot" class="ghost" :disabled="busy" @click="display(retainedOverride,true)">隐藏伙伴</button></div>
      <div v-if="selecting" class="role-picker"><p class="muted">选择喜欢的头像，原始问卷结果保持不变。</p><div class="role-picker-grid"><button v-for="r in allRoles" :key="r.code" :disabled="busy" :aria-label="`选择${r.name}`" @click="display(r.code)"><span class="role-avatar" :class="`avatar-${r.code}`" role="img" :aria-label="r.name"></span><span>{{ r.name }}</span></button></div><button v-if="snapshot" class="ghost" :disabled="busy" @click="display(null)">恢复问卷建议</button></div>
    </template>
  </section>
</template>
