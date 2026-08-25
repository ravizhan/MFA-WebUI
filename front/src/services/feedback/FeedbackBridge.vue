<template>
  <slot />
</template>

<script setup lang="ts">
import { useMessage } from "naive-ui"
import { registerMessageApi } from "./message"

registerMessageApi(useMessage())
</script>
