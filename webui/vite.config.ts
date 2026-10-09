import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
//import basicSsl from '@vitejs/plugin-basic-ssl'; // 🚀 1. 引入它

// 🚀 核心修改：用标准 import 满足 Vite，同时用 ts-ignore 让 TypeScript 闭嘴
// @ts-ignore
import basicSsl from '@vitejs/plugin-basic-ssl';
export default defineConfig({
  plugins: [
    react(),
    basicSsl() // 🚀 2. 塞进插件数组
  ],
  server: {
    host: "0.0.0.0",
    port: 5173,
    allowedHosts: true,
    proxy: {
      "/api": {
        target: "http://localhost:9000",
        changeOrigin: true,
      },
      "/ws": {
        target: "ws://localhost:9000",
        ws: true,
        changeOrigin: true,
      },
    },
  },
});
