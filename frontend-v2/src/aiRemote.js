// The ONLY seam to the third-party AI functions in frontend/netlify/functions/.
//
// Those functions POST document content to api.anthropic.com and api.openai.com. They exist
// for the public Netlify demo. The Azure ACP deployment is a compliance product that promises
// document content never leaves the environment — so its bundle must not merely avoid CALLING
// them, it must not CONTAIN them.
//
// SIM is `import.meta.env.VITE_SIM !== 'false'`, which Vite inlines at build time. With
// VITE_SIM=false (the Azure Dockerfile) every function below folds to `return null` and the
// dynamic import becomes unreachable, so Rollup drops aiRemediate.js from the graph entirely.
// Verified by asserting no "/.netlify/functions/" string survives in the Azure dist.
//
// Do NOT convert these back to static imports.

import { SIM } from './sim.js'

const remote = () => import('./aiRemediate.js')

export async function generateAltText(args) {
  if (!SIM) return null
  return (await remote()).generateAltText(args)
}

export async function aiTextFix(args) {
  if (!SIM) return null
  return (await remote()).aiTextFix(args)
}

export async function generateCaptions(args) {
  if (!SIM) return null
  return (await remote()).generateCaptions(args)
}

export async function generateInsights(args) {
  if (!SIM) return null
  return (await remote()).generateInsights(args)
}
