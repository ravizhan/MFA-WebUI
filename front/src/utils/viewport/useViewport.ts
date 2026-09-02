import { computed, onMounted, onUnmounted, readonly, ref } from "vue"

export const MOBILE_BREAKPOINT = 768
export const DESKTOP_BREAKPOINT = 1280

const viewportWidth = ref(getWindowWidth())
let activeConsumers = 0
let listening = false

function getWindowWidth() {
  if (typeof window === "undefined") {
    return DESKTOP_BREAKPOINT
  }
  return window.innerWidth
}

function updateViewportWidth() {
  viewportWidth.value = getWindowWidth()
}

function startResizeListener() {
  if (listening || typeof window === "undefined") {
    return
  }
  window.addEventListener("resize", updateViewportWidth)
  listening = true
}

function stopResizeListener() {
  if (!listening || typeof window === "undefined") {
    return
  }
  window.removeEventListener("resize", updateViewportWidth)
  listening = false
}

export function useViewport() {
  onMounted(() => {
    activeConsumers += 1
    updateViewportWidth()
    startResizeListener()
  })

  onUnmounted(() => {
    activeConsumers = Math.max(0, activeConsumers - 1)
    if (activeConsumers === 0) {
      stopResizeListener()
    }
  })

  const isMobile = computed(() => viewportWidth.value < MOBILE_BREAKPOINT)

  return {
    width: readonly(viewportWidth),
    isMobile,
  }
}
