<script setup>
import { nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import * as echarts from 'echarts/core'
import { BarChart, PieChart, LineChart, RadarChart, ScatterChart, HeatmapChart, TreemapChart } from 'echarts/charts'
import { GridComponent, TooltipComponent, LegendComponent, RadarComponent, VisualMapComponent, GraphicComponent, AriaComponent } from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'
echarts.use([BarChart, PieChart, LineChart, RadarChart, ScatterChart, HeatmapChart, TreemapChart,
  GridComponent, TooltipComponent, LegendComponent, RadarComponent, VisualMapComponent, GraphicComponent, AriaComponent, CanvasRenderer])
const props = defineProps({ option: Object, label: String })
const element = ref(null)
let chart, observer
onMounted(() => {
  chart = echarts.init(element.value)
  chart.setOption({ ...props.option, aria: { enabled: true, label: { description: props.label } } })
  observer = new ResizeObserver(() => chart?.resize())
  observer.observe(element.value)
})
watch(() => props.option, async option => { await nextTick(); chart?.setOption({ ...option, aria: { enabled: true, label: { description: props.label } } }, true) }, { deep: true })
onBeforeUnmount(() => { observer?.disconnect(); chart?.dispose() })
</script>
<template><div ref="element" class="chart" role="img" :aria-label="label"></div></template>
