import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

const now = new Date()
const calver = `${now.getFullYear()}.${now.getMonth() + 1}.${now.getDate()}`

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
