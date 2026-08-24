import { defineConfig, loadEnv } from 'vite'
import react from '@vitejs/plugin-react'

// One app, one build, several published sites. `--mode <slug>` picks up
// .env.<slug>, which carries that site's branding and — importantly — the base
// path GitHub Pages serves it from. Routing is hash-based, so no 404.html
// fallback is needed for deep links at either path.
//
//   npm run build                 -> /wod-webapp/          (uses .env)
//   npm run build:dunelmliga      -> /wod-webapp/dunelmliga/
export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), 'VITE_')
  return {
    base: env.VITE_SITE_BASE || '/wod-webapp/',
    plugins: [react()],
    build: { outDir: 'dist', emptyOutDir: true },
  }
})
