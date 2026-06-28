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
})
