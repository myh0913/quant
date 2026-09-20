import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

export default defineConfig({
  plugins: [react()],
  // 与 Caddy 反代子路径一致(/qg)
  base: '/qg/',
  server: {
    port: 5273,
    host: '0.0.0.0',
    strictPort: true,
    // Caddy 共享反代:多 host 都允许
    allowedHosts: ['goldmac-mini.tail81369e.ts.net', '106.54.3.5', 'localhost', '127.0.0.1'],
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