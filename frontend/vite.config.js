import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

const now = new Date()
// UTC, to match the authoritative stamp deploy.sh bakes into ACP_BUILD_VERSION. This is
// only the fallback shown when the server hasn't reported its version yet; using local
// getters made it silently disagree with the real version whenever the builder's zone
// was behind UTC (e.g. a 5pm PDT build is already the next day in UTC).
const calver = `${now.getUTCFullYear()}.${now.getUTCMonth() + 1}.${now.getUTCDate()}`

export default defineConfig({
  plugins: [react()],
  server: { port: parseInt(process.env.PORT || '5173') },
  define: {
    __BUILD_TIME__: JSON.stringify(now.toISOString()),
    __BUILD_VERSION__: JSON.stringify(calver),
  },
  build: {
    // Audited 2026-07: every heavy dep (axe-core, pdfjs, pdf-lib, jspdf, jszip, d3/
    // KnowledgeGraph) is behind a dynamic import — the >500 kB chunks the default
    // limit flags are all lazy-loaded, and the ~720 kB entry chunk is intrinsic app
    // code. 750 keeps a tripwire for real regressions without warning on every build.
    chunkSizeWarningLimit: 750,
  },
})
