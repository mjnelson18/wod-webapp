import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// base must match the GitHub Pages repo path. Routing is hash-based, so no
// 404.html fallback is needed for deep links.
export default defineConfig({
  base: '/wod-webapp/',
  plugins: [react()],
  build: { outDir: 'dist', emptyOutDir: true },
})
