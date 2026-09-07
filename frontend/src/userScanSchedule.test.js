import { describe, expect, it } from 'vitest'
import { readFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'

const here = dirname(fileURLToPath(import.meta.url))
const monitor = readFileSync(join(here, 'Monitor.jsx'), 'utf8')

describe('per-user local-time scan schedule', () => {
  it('sends the wall-clock schedule contract without the retired interval cadence', () => {
    expect(monitor).toMatch(/putSchedule\(\{[\s\S]*enabled: schedule\.enabled, timezone: schedule\.timezone, local_time: schedule\.local_time, days: schedule\.days/)
    expect(monitor).toMatch(/enabled: false, timezone: browserTimezone\(\), local_time: '09:00', days:/)
    expect(monitor).not.toMatch(/minMap|setAllCad/)
  })

  it('defaults an absent server timezone to the browser timezone', () => {
    expect(monitor).toMatch(/Intl\.DateTimeFormat\(\)\.resolvedOptions\(\)\.timeZone/)
    expect(monitor).toMatch(/timezone: s\.updated_at \? \(s\.timezone \|\| browserTimezone\(\)\) : browserTimezone\(\)/)
  })

  it('lets users choose local time, timezone, and weekdays accessibly', () => {
    expect(monitor).toMatch(/type="time" value=\{schedule\.local_time\}/)
    expect(monitor).toMatch(/list="scan-timezones" value=\{schedule\.timezone\}/)
    expect(monitor).toMatch(/aria-pressed=\{selected\}/)
    expect(monitor).toMatch(/Choose at least one day/)
  })

  it('explains that daylight-saving clock changes are followed', () => {
    expect(monitor).toMatch(/schedule follows local clock changes automatically/)
  })

  it('formats the next run in the schedule timezone', () => {
    expect(monitor).toMatch(/scheduleTimeLabel\(schedNext, schedule\.timezone\)/)
    expect(monitor).toMatch(/timeZone: timezone/)
  })

  it('validates the timezone and explains its current UTC offset', () => {
    expect(monitor).toMatch(/new Intl\.DateTimeFormat\(\[\], \{ timeZone: timezone \}\)/)
    expect(monitor).toMatch(/Enter a valid IANA time zone/)
    expect(monitor).toMatch(/aria-invalid=\{schedule\.enabled && !schedTimezoneValid\}/)
    expect(monitor).toMatch(/Current offset/)
    expect(monitor).toMatch(/replace\('GMT', 'UTC'\)/)
  })

  it('makes save state available to assistive technology', () => {
    expect(monitor).toMatch(/role="status" aria-live="polite"/)
    expect(monitor).toMatch(/'✓ Saved'/)
    expect(monitor).toMatch(/'Unsaved changes'/)
    expect(monitor).toMatch(/setSavedSchedule\(nextSchedule\)/)
  })

  it('offers weekday and daily nine o’clock presets', () => {
    expect(monitor).toMatch(/Weekdays at 9:00/)
    expect(monitor).toMatch(/Daily at 9:00/)
    expect(monitor).toMatch(/applySchedulePreset\(\[0, 1, 2, 3, 4\]\)/)
    expect(monitor).toMatch(/applySchedulePreset\(\[0, 1, 2, 3, 4, 5, 6\]\)/)
  })

  it('explains that scheduled work uses the organization background connection', () => {
    expect(monitor).toMatch(/organization’s configured background connection/)
    expect(monitor).toMatch(/do not depend on this browser session remaining signed in/)
    expect(monitor).not.toMatch(/server-side via the service account/)
  })

  it('renders optional run metrics as an accessible compact definition list', () => {
    expect(monitor).toMatch(/normalizeScheduleMetrics\(s\.metrics\)/)
    expect(monitor).toMatch(/aria-label="Scheduled scan run totals"/)
    for (const label of ['Scheduled', 'Delayed', 'Skipped', 'Failed']) {
      expect(monitor).toContain(`'${label}'`)
    }
    expect(monitor).toMatch(/if \(!metrics \|\| typeof metrics !== 'object'\) return null/)
    expect(monitor).toMatch(/Number\.isFinite\(value\) && value > 0 \? Math\.floor\(value\) : 0/)
  })
})
