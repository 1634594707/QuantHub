import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// vite.config.ts 运行在 Node 环境，process 全局可用；
// 此处声明类型以避免 tsc -b（npm run build）在无 @types/node 时报 TS2580。
declare const process: { env: Record<string, string | undefined> }

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    host: true,
    port: 5173,
    strictPort: false,
    // 开发态反代：前端用相对路径 /api/* 即可，无跨域、无 CORS 放开。
    // 生产态前后端同源反代到 /api/* 复用同一规则。
    // 默认指向统一 API 网关 8001；其他端口可经环境变量覆盖：
    //   $env:VITE_DEV_PROXY_TARGET='http://localhost:9000'; npm run dev
    proxy: {
      '/api': {
        target: process.env.VITE_DEV_PROXY_TARGET || 'http://localhost:8001',
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/api/, ''),
      },
    },
  },
})
