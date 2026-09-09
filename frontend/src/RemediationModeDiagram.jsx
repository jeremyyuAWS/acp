import { useId } from 'react'
import './remediation-mode-diagram.css'

// Where a person stands in each remediation automation mode.
//
// The question this answers is "if I pick this mode, what will ACP ask me to do?" — and the one
// answer that matters is that the end-to-end mode does NOT ask a person to approve AI suggestions.
// Reading that off a diagram requires seeing all three modes against the same pipeline, so the
// content is genuinely a matrix: modes down, stages across. It is therefore a real <table> with a
// <caption>, column headers for the stages and row headers for the modes, not a decorative grid.
//
// ACCESSIBILITY. Colour never carries the meaning: every cell names its actor in words ("ACP",
// "You", "Not used") and the active mode is marked with visible text ("Your selection") as well as
// aria-current, so the emphasis survives a monochrome print, a forced-colours mode and a screen
// reader. The arrows between stage headers are ornament and are aria-hidden; the reading order of
// the stages is carried by the step number, which is text.
//
// Presentational only: no fetching, no app state, no defaults invented for data the caller did not
// supply. In particular, a count is rendered ONLY where `counts` names one — a placeholder figure
// in an accessibility product's planning screen is a number somebody will quote.

/** The pipeline, left to right. Stage ids are the keys used by `mode.stages` and by `counts`. */
export const REMEDIATION_STAGES = [
  { id: 'scan', label: 'Scan' },
  { id: 'rule-fixes', label: 'Rule fixes' },
  { id: 'ai-draft', label: 'AI draft' },
  { id: 'ai-review', label: 'AI review' },
  { id: 'write', label: 'Write' },
  { id: 'verify', label: 'Verify' },
  { id: 'publish', label: 'Publish' },
]

const SCAN = { actor: 'acp', text: 'Finds the issues' }
const DRAFT = { actor: 'acp', text: 'Writes a suggestion' }
const WRITE = { actor: 'acp', text: 'Writes the file' }
const VERIFY = { actor: 'acp', text: 'Checks the result' }
const PUBLISH = { actor: 'person', text: 'Publish when ready' }

/** The three modes as approved. A caller may pass its own `modes` in the same shape. */
export const REMEDIATION_MODES = [
  {
    id: 'review-every-change',
    label: 'Review every change',
    description: 'You approve every rule-based fix and every AI suggestion before it is applied.',
    stages: {
      scan: SCAN,
      'rule-fixes': { actor: 'person', text: 'Approve each fix' },
      'ai-draft': DRAFT,
      'ai-review': { actor: 'person', text: 'Approve each suggestion' },
      write: WRITE,
      verify: VERIFY,
      publish: PUBLISH,
    },
  },
  {
    id: 'rule-based-auto',
    label: 'Apply rule-based fixes',
    description: 'ACP applies rule-based fixes on its own. You still approve every AI suggestion.',
    stages: {
      scan: SCAN,
      'rule-fixes': { actor: 'acp', text: 'Applies them for you' },
      'ai-draft': DRAFT,
      'ai-review': { actor: 'person', text: 'Approve each suggestion' },
      write: WRITE,
      verify: VERIFY,
      publish: PUBLISH,
    },
  },
  {
    id: 'end-to-end',
    label: 'Run end to end',
    recommended: true,
    description: 'ACP applies the fixes and has a second AI check its own suggestions. It does not ask you to approve them.',
    note: 'Anything the AI reviewer rejects comes back to you.',
    stages: {
      scan: SCAN,
      'rule-fixes': { actor: 'acp', text: 'Applies them for you' },
      'ai-draft': DRAFT,
      'ai-review': { actor: 'acp', text: 'A second AI checks it' },
      write: WRITE,
      verify: VERIFY,
      publish: PUBLISH,
    },
  },
]

// The actor word. This is the text equivalent of the cell's colour, so it is never omitted.
const ACTOR_WORD = { acp: 'ACP', person: 'You', none: 'Not used' }

/** A finite number, or null. Strings are accepted; anything else is treated as "not supplied". */
function figure(value) {
  if (typeof value === 'number') return Number.isFinite(value) ? value : null
  if (typeof value === 'string' && value.trim() !== '') {
    const parsed = Number(value)
    return Number.isFinite(parsed) ? parsed : null
  }
  return null
}

/**
 * The phrases for one cell's count, or null when the caller supplied nothing usable.
 * `{ auto: 31, approve: 554 }` -> ['31 auto', '554 to approve']; a string passes through verbatim.
 */
function countPhrases(value) {
  if (typeof value === 'string') return value.trim() ? [value.trim()] : null
  if (!value || typeof value !== 'object') return null
  const phrases = []
  const auto = figure(value.auto)
  const approve = figure(value.approve)
  if (auto !== null) phrases.push(`${auto.toLocaleString('en-US')} auto`)
  if (approve !== null) phrases.push(`${approve.toLocaleString('en-US')} to approve`)
  return phrases.length ? phrases : null
}

/**
 * @param {object}   props
 * @param {Array}    [props.modes]        Modes, in display order. Defaults to REMEDIATION_MODES.
 * @param {Array}    [props.stages]       Stages, left to right. Defaults to REMEDIATION_STAGES.
 * @param {string}   [props.activeModeId] Which mode the user currently has selected, if any.
 * @param {object}   [props.counts]       counts[modeId][stageId] = { auto, approve } | string.
 * @param {string}   [props.title]        Table caption.
 * @param {string}   [props.className]    Extra class on the wrapping <section>.
 */
export default function RemediationModeDiagram({
  modes = REMEDIATION_MODES,
  stages = REMEDIATION_STAGES,
  activeModeId = null,
  counts = null,
  title = 'Who does what, in each mode',
  className = '',
}) {
  const id = useId()
  if (!Array.isArray(modes) || !modes.length || !Array.isArray(stages) || !stages.length) return null
  const titleId = `${id}-title`
  // The wrapper below is a plain <div>, deliberately NOT a landmark. It and the scrollable region
  // were both labelled by `titleId`, which is two landmarks sharing one accessible name — axe's
  // `landmark-unique`, caught by RemediationImpactCard's axe check rather than by this component's
  // own tests. The scroll container keeps the name, because it is the thing a keyboard user lands
  // on and must hear named; the table's <caption> carries the title visually either way.
  return (
    <div className={`rmd${className ? ` ${className}` : ''}`}>
      {/* tabIndex makes the horizontally scrolling area reachable by keyboard (WCAG 2.1.1); the
          page itself never scrolls sideways because the scroller, not the table, is the wide box. */}
      <div className="rmd__scroll" role="region" aria-labelledby={titleId} tabIndex={0}>
        <table className="rmd__table">
          <caption className="rmd__caption">
            <span className="rmd__title" id={titleId}>{title}</span>
            <span className="rmd__subtitle">
              Each row is one mode. Read left to right: “You” marks a step that waits for a person,
              “ACP” a step ACP completes on its own.
            </span>
          </caption>
          <thead>
            <tr>
              <th scope="col" className="rmd__corner">Mode</th>
              {stages.map((stage, index) => (
                <th scope="col" key={stage.id} data-stage={stage.id}
                  className={index > 0 ? 'rmd__stage rmd__stage--after' : 'rmd__stage'}>
                  {index > 0 && <span className="rmd__arrow" aria-hidden="true">→</span>}
                  <span className="rmd__step">{index + 1}</span>
                  <span className="rmd__stage-label">{stage.label}</span>
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {modes.map((mode) => {
              const active = activeModeId != null && mode.id === activeModeId
              return (
                <tr key={mode.id} className={active ? 'rmd__row rmd__row--active' : 'rmd__row'} data-mode={mode.id}>
                  <th scope="row" className="rmd__mode" aria-current={active ? 'true' : undefined}>
                    <span className="rmd__mode-name">{mode.label}</span>
                    {/* Text, not a colour: the selection survives monochrome and forced colours. */}
                    {active && <span className="rmd__selected">Your selection</span>}
                    {mode.recommended && <span className="rmd__recommended">Recommended</span>}
                    {mode.description && <span className="rmd__mode-desc">{mode.description}</span>}
                    {mode.note && <span className="rmd__note">{mode.note}</span>}
                  </th>
                  {stages.map((stage) => {
                    const cell = (mode.stages && mode.stages[stage.id]) || { actor: 'none' }
                    const actor = ACTOR_WORD[cell.actor] ? cell.actor : 'none'
                    const phrases = countPhrases(counts && counts[mode.id] && counts[mode.id][stage.id])
                    return (
                      <td key={stage.id} className="rmd__cell" data-actor={actor} data-stage={stage.id}>
                        <span className="rmd__actor">{ACTOR_WORD[actor]}</span>
                        {actor !== 'none' && cell.text && <span className="rmd__what">{cell.text}</span>}
                        {phrases && (
                          <span className="rmd__count">
                            {phrases.map((phrase, index) => (
                              <span className="rmd__count-part" key={phrase}>
                                {index > 0 && <span className="rmd__count-sep" aria-hidden="true"> / </span>}
                                {phrase}
                              </span>
                            ))}
                          </span>
                        )}
                      </td>
                    )
                  })}
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
      <p className="rmd__legend">
        <span className="rmd__legend-item"><span className="rmd__actor" data-actor="person">You</span> a person acts, and the run waits</span>
        <span className="rmd__legend-item"><span className="rmd__actor" data-actor="acp">ACP</span> ACP does this on its own</span>
      </p>
    </div>
  )
}
