import { confidenceForFinding, methodForSc } from './confidence.js'
import { proposalMeta } from './reviewCard.js'
import { scOf } from './fixSummary.js'

export const AUTOMATION_LEVELS = [
  { value: 1, name: 'Strict', description: 'Verified deterministic fixes only' },
  { value: 2, name: 'Cautious', description: 'Deterministic fixes with complete evidence' },
  { value: 3, name: 'Balanced', description: 'Adds validated, non-subjective proposals' },
  { value: 4, name: 'Assisted', description: 'Adds supported AI proposals' },
  { value: 5, name: 'Maximum', description: 'Adds lower-confidence eligible proposals' },
]

export const DEFAULT_AUTOMATION_LEVEL = 3

const requiredLevel = (finding) => {
  const sc = scOf(finding?.rule_id || finding?.ruleId)
  const proposal = proposalMeta(finding)
  const method = methodForSc(sc)

  // These are product safety boundaries, not user preferences. Moving the slider never
  // makes subjective, unsupported, or human-only work eligible for unattended changes.
  if (finding?.rejectedFix || method === 'human' || sc === '1.3.3' || proposal?.subjective || !finding?.hasProposal) {
    return null
  }
  const confidence = confidenceForFinding({
    sc,
    proposal: proposal && { validated: proposal.validated, subjective: proposal.subjective },
  })
  // Strict means VERIFIED deterministic work, not merely a high-confidence deterministic
  // detector. A proposal does not earn that label until the stored post-apply validation signal
  // exists; without it the safest setting would promise more than the evidence proves.
  if (method === 'deterministic' && proposal?.validated) return 1
  if (method === 'deterministic') return 2
  if (proposal?.validated) return 3
  if (confidence.level.key === 'medium') return 4
  return 5
}

const fileCount = (rows) => new Set(rows.map((finding) => finding?.file).filter(Boolean)).size

const findingCount = (row) => {
  const raw = Number(row?.finding_count ?? row?._raw?.finding_count ?? 1)
  return Number.isFinite(raw) && raw > 0 ? Math.round(raw) : 1
}

// A queue row is the durable review-card authority. Callers mark those rows explicitly; rows
// representing automatic work are forecast inputs, not cards that already exist in the queue.
const cardKey = (row, index) => row?.reviewCardId || row?._raw?.id || row?.id || `forecast:${index}`
const cards = (rows) => new Set(rows.map((row, index) => cardKey(row, index))).size
const findingTotal = (rows) => rows.reduce((sum, row) => sum + findingCount(row), 0)

const protectedReason = (finding) => {
  const sc = scOf(finding?.rule_id || finding?.ruleId)
  const proposal = proposalMeta(finding)
  if (finding?.rejectedFix) return 'rejected'
  if (!finding?.hasProposal) return 'authoring'
  if (methodForSc(sc) === 'human' || sc === '1.3.3' || proposal?.subjective) return 'judgement'
  return 'judgement'
}

const categorySummary = (key, rows) => {
  const criteria = new Map()
  rows.forEach((finding) => {
    const sc = scOf(finding?.rule_id || finding?.ruleId) || 'Other'
    criteria.set(sc, (criteria.get(sc) || 0) + 1)
  })
  return {
    key,
    findings: findingTotal(rows),
    cards: cards(rows),
    files: fileCount(rows),
    criteria: [...criteria.entries()]
      .map(([criterion, count]) => ({ criterion, count }))
      .sort((a, b) => b.count - a.count || a.criterion.localeCompare(b.criterion)),
    fileNames: [...new Set(rows.map((finding) => finding?.file).filter(Boolean))].sort(),
  }
}

export function automationForecast(findings = [], level = DEFAULT_AUTOMATION_LEVEL) {
  const rows = Array.isArray(findings) ? findings : []
  const buckets = { candidates: [], review: [], protected: [] }
  const humanBuckets = { threshold: [], authoring: [], judgement: [], rejected: [] }
  rows.forEach((finding) => {
    const threshold = requiredLevel(finding)
    if (threshold == null) {
      buckets.protected.push(finding)
      humanBuckets[protectedReason(finding)].push(finding)
    } else if (threshold <= level) buckets.candidates.push(finding)
    else {
      buckets.review.push(finding)
      humanBuckets.threshold.push(finding)
    }
  })
  return {
    total: findingTotal(rows),
    candidates: findingTotal(buckets.candidates),
    candidateFiles: fileCount(buckets.candidates),
    review: findingTotal(buckets.review),
    reviewFiles: fileCount(buckets.review),
    protected: findingTotal(buckets.protected),
    protectedFiles: fileCount(buckets.protected),
    humanCategories: Object.entries(humanBuckets)
      .map(([key, bucket]) => categorySummary(key, bucket))
      .filter((category) => category.findings > 0),
    reviewCards: cards([...buckets.review, ...buckets.protected]),
    currentReviewCards: cards(rows.filter((row) => row?.isCurrentReviewCard)),
  }
}

export function reviewCardImpact(findings = [], level = DEFAULT_AUTOMATION_LEVEL) {
  const forecast = automationForecast(findings, level)
  return {
    current: forecast.currentReviewCards,
    preview: forecast.reviewCards,
    delta: forecast.reviewCards - forecast.currentReviewCards,
  }
}

export function automationLevel(value) {
  return AUTOMATION_LEVELS.find((level) => level.value === Number(value)) || AUTOMATION_LEVELS[DEFAULT_AUTOMATION_LEVEL - 1]
}
