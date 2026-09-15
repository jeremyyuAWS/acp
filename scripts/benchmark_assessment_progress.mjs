// Offline presentation benchmark. Consume outputs so work cannot be optimized away.
import { performance } from 'node:perf_hooks'
import { assessmentProgress, assessmentLine } from '../frontend/src/assessmentProgress.js'
const iterations = 100000
const samples = []
let checksum = 0
for (let trial = 0; trial < 7; trial++) {
  const start = performance.now()
  for (let i = 0; i < iterations; i++) {
    const p = { phase: ['queued', 'analysing', 'blocked', 'done'][i % 4],
      files_found: 250, files_done: i % 251, elapsed: 300 }
    const vm = assessmentProgress(p)
    checksum += vm.percent + assessmentLine(p).length
  }
  samples.push(performance.now() - start)
}
console.log(JSON.stringify({ runtime: process.version, iterations, trials: samples.length,
  samples_ms: samples, median_ms: [...samples].sort((a, b) => a - b)[3], checksum }, null, 2))
