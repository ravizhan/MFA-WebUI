import { createRouter, createWebHistory } from "vue-router"
import HomeView from "@/views/home/HomeView.vue"

const router = createRouter({
  history: createWebHistory(import.meta.env.BASE_URL),
  routes: [
    {
      path: "/",
      name: "home",
      component: HomeView,
      meta: { transition: "slide-right" },
    },
    {
      path: "/tasks",
      name: "tasks",
      component: () => import("@/views/tasks/TasksView.vue"),
      meta: { transition: "slide-right" },
    },
    {
      path: "/routines",
      name: "routines",
      component: () => import("@/views/routines/RoutinesView.vue"),
      meta: { transition: "slide-left" },
    },
    {
      path: "/logs",
      name: "logs",
      component: () => import("@/views/logs/LogsView.vue"),
      meta: { transition: "slide-left" },
    },
    {
      path: "/settings",
      name: "settings",
      component: () => import("@/views/settings/SettingsView.vue"),
      meta: { transition: "slide-left" },
    },
  ],
})

export default router
