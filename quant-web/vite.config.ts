import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

export default defineConfig({
  plugins: [react()],
  // 走 tailscale funnel 时的挂载前缀：caddy 按 /quant/* 原样转发（不剥前缀）
  base: '/quant/',
  server: {
    port: 5273,
    host: '0.0.0.0',
    strictPort: true,
    // 允许 tailscale funnel 域名访问 dev server
    allowedHosts: ['goldmac-mini.tail81369e.ts.net', 'localhost', '127.0.0.1'],
    proxy: {
      // 后端启动后代理 /api → localhost:8000（后端路由本身带 /api 前缀，不剥）
      '/api': {
        target: 'http://localhost:8000',
        changeOrigin: true,
      },
      '/ws': {
        target: 'ws://localhost:8000',
        ws: true,
        changeOrigin: true,
      },
    },
  },
});