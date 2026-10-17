import { defineConfig, loadEnv } from 'vite';
import react from '@vitejs/plugin-react';

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, '.', '');
  const configuredApi = env.VITE_PRESENTATIONS_API_BASE_URL || env.VITE_API_URL;
  const upstream = new URL(configuredApi?.startsWith('http') ? configuredApi : `${env.VITE_DEV_API_PROXY || 'http://127.0.0.1:8000'}/api/v1`);
  return {
    base: env.VITE_APP_BASE_PATH || '/',
    plugins: [react()],
    server: {
      proxy: {
        '/presentations/api/v1': {
          target: upstream.origin,
          changeOrigin: true,
          rewrite: path => path.replace(/^\/presentations\/api\/v1/, upstream.pathname.replace(/\/$/, '')),
        },
        '/api/v1': {
          target: upstream.origin,
          changeOrigin: true,
          rewrite: path => path.replace(/^\/api\/v1/, upstream.pathname.replace(/\/$/, '')),
        },
      },
    },
  };
});
