<template>
  <router-view v-slot="{ Component, route: r }">
    <transition
      :name="typeof r.meta.transition === 'string' ? r.meta.transition : 'fade'"
      mode="out-in"
    >
      <!-- Key by route name: guarantees unmount/remount across routes so
           multi-root views (e.g. TasksView) never leak sibling nodes into
           the next route under transition mode="out-in". -->
      <div :key="r.name">
        <component :is="Component" />
      </div>
    </transition>
  </router-view>
</template>
