
import path from 'node:path';
import react from '@vitejs/plugin-react';
import { defineConfig } from 'vite';

export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      '/api.php': 'http://127.0.0.1:8000',
      '/market.php': 'http://127.0.0.1:8000',
      '/geocode.php': 'http://127.0.0.1:8000',
    },
  },
  resolve: {
    alias: { '@': path.resolve(import.meta.dirname, 'src') },
  },
  build: {
    outDir: 'dist',
    emptyOutDir: true,
  },
});
