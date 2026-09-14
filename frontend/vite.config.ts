/// <reference types="vitest" />
import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import path from 'path';

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      '@': path.resolve(__dirname, './src'),
    },
  },
  server: {
    port: 5174,
    proxy: {
      '/api': {
        target: 'http://localhost:8000',
        changeOrigin: true,
      },
      '/ws': {
        target: 'ws://localhost:8000',
        ws: true,
      },
    },
  },
  test: {
    globals: true,
    environment: 'jsdom',
    setupFiles: './src/setupTests.ts',
    css: false,
    // Vitest defaults to (cores - 1) forks. On a 16-core box that is 15 concurrent jsdom +
    // MSW environments, and the suite then fails differently on every run: 1 failure, then 2,
    // then 14, all of them `findBy*` timeouts on pages that pass in isolation in under a
    // second. The tests were never flaky — they were starved. Four forks keeps the wall clock
    // close to the parallel best case while leaving headroom for whatever else is running.
    maxWorkers: 4,
    minWorkers: 1,
    // A loaded machine must produce a slow pass, not a false failure. The pass path is
    // unaffected by these ceilings; only a genuinely hung test reaches them.
    testTimeout: 20_000,
    hookTimeout: 20_000,
  },
});
