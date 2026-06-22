import { defineConfig } from 'vitest/config'

// Smoke tests for the core engines (ontology rules, Office audit/remediate, HTML
// remediation). jsdom gives us DOMParser for the HTML-remediation tests.
export default defineConfig({
  test: {
    environment: 'jsdom',
    globals: true,
    include: ['src/**/*.test.{js,jsx}'],
  },
})
