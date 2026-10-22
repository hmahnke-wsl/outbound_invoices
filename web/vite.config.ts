/// <reference types="vitest" />
import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import { readFileSync } from 'node:fs';

// Dev ports live in the repo's ports.env (one block per repo -- see PORTS.md
// next to the repos), shared with dashboard.command.
const ports = Object.fromEntries(
  [...readFileSync(new URL('../ports.env', import.meta.url), 'utf8').matchAll(/^(\w+)=(\d+)$/gm)].map(
    ([, key, value]) => [key, Number(value)],
  ),
);

export default defineConfig({
  plugins: [react()],
  resolve: { dedupe: ['react', 'react-dom'] },
  test: {
    globals: true,
    environment: 'jsdom',
    setupFiles: './src/test/setup.ts',
  },
  server: {
    port: ports.PORT_WEB,
    strictPort: true, // fail if taken, rather than drifting onto another project's port
    fs: { allow: ['../..'] }, // @wsl/ui lives in ../../shared_ui
    // API_PORT: lets the auth-on "api-wsl-ldap"/"web-login" launch configs run alongside the usual PORT_API API.
    proxy: { '/api': { target: `http://localhost:${process.env.API_PORT ?? ports.PORT_API}`, changeOrigin: true } },
  },
});
