import { useState, useRef, useEffect } from 'react'
import { prefersReducedMotion } from './a11y.js'

// Makes the invisible value tangible: what a blind user's screen reader actually
// announces, as-uploaded vs. remediated. Optional real speech via the Web Speech
// API. Only AT-relevant criteria appear (contrast, e.g., is a low-vision issue,
// not a screen-reader one — so it's intentionally excluded).
function passFor(issues, docTitle) {
  const has = (sc) => issues.some((i) => (i.wcag || '').includes(sc))
  const title = docTitle || 'Open enrollment 2026 — UT Southwestern'
  const lines = [{ before: 'document, no title', after: title }, { before: title, after: `heading level 1, ${title}` }]
  if (has('1.1.1')) lines.push({ before: 'graphic', after: 'graphic — bar chart, enrollment by region, West highest at 38 percent' })
  if (has('1.3.1')) lines.push({ before: 'table, eight cells', after: 'table, Region by enrollment, 2 columns, 5 rows. Column one, Region. Column two, Enrollment' })
  if (has('1.3.2')) lines.push({ before: 'footnote 4. Continued from. The plan covers', after: 'The plan covers preventive visits. Footnote 4.' })
  if (has('2.4.4')) lines.push({ before: 'link, click here', after: 'link, view ' + (docTitle ? 'the ' + docTitle.toLowerCase() : 'the full document') })
  lines.push({ before: 'edit text, blank', after: 'Email address, required, edit text' })
  if (has('3.1.1')) lines.push({ before: '(read with the wrong pronunciation)', after: 'language, English' })
  return lines
}

export default function ScreenReaderDemo({ issues = [], docTitle = null }) {
  const lines = passFor(issues, docTitle)
  const [cursor, setCursor] = useState(-1)
  const [mode, setMode] = useState(null)
  const [sound, setSound] = useState(false)
  const timer = useRef(null)
  const stop = () => { clearTimeout(timer.current); window.speechSynthesis?.cancel(); setCursor(-1); setMode(null) }
  useEffect(() => () => stop(), []) // eslint-disable-line react-hooks/exhaustive-deps

  const play = (m) => {
    stop(); setMode(m)
    const useVoice = sound && typeof window !== 'undefined' && window.speechSynthesis
    let i = 0
    const step = () => {
      if (i >= lines.length) { setCursor(-1); setMode(null); return }
      setCursor(i)
      if (useVoice) {
        const u = new SpeechSynthesisUtterance(lines[i][m]); u.rate = 1.06
        u.onend = () => { i += 1; step() }; u.onerror = () => { i += 1; timer.current = setTimeout(step, 700) }
        window.speechSynthesis.speak(u)
      } else { i += 1; timer.current = setTimeout(step, prefersReducedMotion() ? 250 : 950) }
    }
    step()
  }

  return (
    <section className="srdemo">
      <div className="bahd"><b>What a screen reader announces</b><span className="muted"> — a blind user’s experience, as-uploaded → remediated</span></div>
      <div className="srlist">
        {lines.map((l, i) => (
          <div className={`srrow${cursor === i ? ` cur-${mode}` : ''}`} key={i}>
            <span className="srbefore">{l.before}</span>
            <span className="srarrow" aria-hidden="true">→</span>
            <span className="srafter">{l.after}</span>
          </div>
        ))}
      </div>
      <div className="srctl">
        <button className="ghost small" onClick={() => play('before')}>▶ Play as uploaded</button>
        <button className="srplay-good" onClick={() => play('after')}>▶ Play remediated</button>
        {(cursor >= 0) && <button className="ghost small" onClick={stop}>■ Stop</button>}
        <label className="srsound"><input type="checkbox" checked={sound} onChange={(e) => setSound(e.target.checked)} /> read aloud</label>
      </div>
    </section>
  )
}
