// Single source of truth for severity colours across the application.
// Import from here; do NOT define inline palettes in individual components.

export const SEV_DOT   = { CRITICAL: '#B42318', SERIOUS: '#B45309', MODERATE: '#B07A00', MINOR: '#6B7280' }
export const SEV_BG    = { CRITICAL: '#FEF3F2', SERIOUS: '#FFF7ED', MODERATE: '#FFFBEB', MINOR: '#F9FAFB' }
export const SEV_FG    = { CRITICAL: '#7A271A', SERIOUS: '#7C2D12', MODERATE: '#78350F', MINOR: '#374151' }
export const SEV_LABEL = { CRITICAL: 'Critical', SERIOUS: 'Serious', MODERATE: 'Moderate', MINOR: 'Minor' }
export const SEV_TIP   = {
  CRITICAL: 'Prevents task completion for users with disabilities',
  SERIOUS:  'Major barrier — a difficult workaround may exist',
  MODERATE: 'Causes meaningful difficulty or additional effort',
  MINOR:    'Limited inconvenience with little effect on task completion',
}
