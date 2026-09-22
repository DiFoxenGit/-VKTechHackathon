import { defineConfig, loadEnv } from 'vite';
import react from '@vitejs/plugin-react';

/** В разработке браузер ходит на свой же адрес, а vite проксирует /api на бэкенд:
 *  прямой запрос на чужой хост браузер блокирует политикой CORS. Адрес бэкенда —
 *  в `VITE_DEV_API_PROXY` (по умолчанию локальный `uvicorn`). */
export default defineConfig(({ mode }) => {
  const target = loadEnv(mode, process.cwd(), '').VITE_DEV_API_PROXY || 'http://localhost:8000';
  return {
    plugins: [react()],
    server: { proxy: { '/api': { target, changeOrigin: true } } },
  };
});
