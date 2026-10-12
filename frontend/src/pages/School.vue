<script setup>
import { onMounted, ref } from 'vue'
import { api } from '../api'
const school = ref(null), error = ref('')
onMounted(async () => { try { school.value = await api('/school') } catch(e) { error.value = e.message } })
</script>
<template><div class="page-heading"><div><div class="eyebrow">SCHOOL & SOURCES</div><h1>学校概况<span class="heading-dot">.</span></h1><p>用公开资料了解学校，用明确口径理解指标。</p></div></div><div v-if="error" class="alert error">{{ error }}</div><section v-if="school" class="panel"><span class="tag">资料入口</span><h2 class="school-title">{{ school.name }}</h2><div class="empty large"><span>▦</span><h3>暂无已核实的统计指标</h3><p>{{ school.notice }}</p></div><div class="source-grid"><a v-for="s in school.sources" :key="s.url" :href="s.url" target="_blank" rel="noopener noreferrer" class="source-card"><span>公开来源 ↗</span><h3>{{ s.name }}</h3><p>{{ s.url }}</p></a></div></section><section class="panel"><h2>阅读数据时，先看这四件事</h2><div class="source-grid"><article class="source-card" v-for="[title,body] in [['年份','历史报告描述过去，不代表当前市场。'],['统计口径','就业率与毕业去向落实率不能互换。'],['样本范围','公开报告与逐人授权样本分别统计。'],['来源与分母','每个百分比需要原始出处和明确分母。']]" :key="title"><h3>{{ title }}</h3><p>{{ body }}</p></article></div></section></template>
