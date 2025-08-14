<template>
  <div class="lg:pt-10 lg:pb-10 pt-0 pb-0">
    <n-layout class="lg:shadow-3xl lg:w-[80vw] w-full m-auto m-0 pt-0">
      <n-layout-header bordered>
        <div class="text-align-center mt-3 text-2xl">{{ name }}</div>
        <n-menu mode="horizontal" class="justify-between" :options="menuOptions" />
      </n-layout-header>
      <n-layout>
        <router-view></router-view>
      </n-layout>
      <n-layout-footer bordered class="text-align-center"> Powered bt MFA-WebUI </n-layout-footer>
    </n-layout>
  </div>
</template>

<script setup>
import { NIcon } from 'naive-ui'
import { h, ref, onMounted, watch, computed } from 'vue'
import { RouterLink } from 'vue-router'
import { useInterfaceStore } from '@/stores/index.js'

function renderIcon(icon) {
  return () => h(NIcon, null, { default: () => h('div', { class: icon }) })
}
const interfaceStore = useInterfaceStore()
const name = computed(() => interfaceStore.interface?.name || '')
const offset = ref(0)
const screenWidth = ref(window.innerWidth)
const handleResize = () => {
  screenWidth.value = window.innerWidth
}
onMounted(async () => {
  await interfaceStore.setInterface()
  window.addEventListener('resize', handleResize)
})
watch(screenWidth, (newValue) => {
  if (newValue < 450) {
    offset.value = 0
  } else if (newValue >= 450 && newValue < 600) {
    offset.value = 1
  } else {
    offset.value = 3
  }
})

const menuOptions = [
  {
    label: () =>
      h(
        RouterLink,
        {
          to: {
            name: 'home',
          },
        },
        { default: () => '首页' },
      ),
    key: 'home',
    icon: renderIcon('i-mdi-home'),
  },
  {
    label: () =>
      h(
        RouterLink,
        {
          to: {
            name: 'setting',
          },
        },
        { default: () => '设置' },
      ),
    key: 'setting',
    icon: renderIcon('i-mdi-cog'),
  },
]
</script>
