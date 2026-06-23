import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import path from "path";
import tailwindcss from "@tailwindcss/vite";
import fs from "fs";
import AutoImport from "unplugin-auto-import/vite";
import checker from "vite-plugin-checker";
import * as lucide from "lucide-react";

// 只把 lucide 带 Icon 后缀的别名（MapIcon / FileIcon / StarIcon ...）纳入 auto-import。
// 这组名字由 lucide 官方 PR #2328 提供，天然不与 JS 全局 / DOM / React 导出撞名。
// 配合 src/vite-env.d.ts 里的 `declare module "lucide-react"` 重定向使用。
const lucideIconNames = Object.keys(lucide).filter(
  (k) => /^[A-Z]/.test(k) && k.endsWith("Icon")
);

const apiProxyTarget =
  process.env.VITE_DEV_API_PROXY_TARGET ||
  process.env.AUTO_WECHAT_API_PROXY_TARGET ||
  "http://127.0.0.1:9000";

const douyinAiCsProxyTarget =
  process.env.VITE_DEV_DOUYIN_AI_CS_PROXY_TARGET ||
  process.env.DOUYIN_AI_CS_PROXY_TARGET ||
  "http://127.0.0.1:9100";

// https://vite.dev/config/
export default defineConfig({
  plugins: [
    react(),
    tailwindcss(),
    AutoImport({
      dts: "auto-imports.d.ts",
      include: [/\.[tj]sx?$/],
      imports: [
        "react",
        { "lucide-react": lucideIconNames },
      ],
      eslintrc: { enabled: false },
    }),
    checker({
      typescript: {
        tsconfigPath: "tsconfig.app.json",
      },
      enableBuild: true,
    }),
  ],
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "./src"),
    },
  },
  server: {
    proxy: {
      // Docker 前端容器可把浏览器侧 /api 转发到 9000，避免 Vite 返回 index.html。
      "/api": {
        target: apiProxyTarget,
        changeOrigin: true,
        rewrite: (value) => value.replace(/^\/api/, ""),
      },
      // 抖音 AI 客服独立服务的开发代理，保持与 /api 同一套浏览器侧前缀策略。
      "/ai-cs-api": {
        target: douyinAiCsProxyTarget,
        changeOrigin: true,
        rewrite: (value) => value.replace(/^\/ai-cs-api/, ""),
      },
    },
  },
});
