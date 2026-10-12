import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// Dashboard dev server. The API runs separately on http://localhost:8000 (see VITE_API_URL).
export default defineConfig({
  plugins: [react()],
  server: { port: 5175, strictPort: true },
})
