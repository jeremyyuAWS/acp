import { describe, expect, it } from 'vitest'
import { readFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'

const here = dirname(fileURLToPath(import.meta.url))
const monitor = readFileSync(join(here, 'Monitor.jsx'), 'utf8')

describe('per-user local-time scan schedule', () => {
  it('sends the wall-clock schedule contract without the retired interval cadence', () => {
    expect(monitor).toMatch(/putSchedule\(\{ enabled: schedule\.enabled, timezone: schedule\.timezone, local_time: schedule\.local_time, days: schedule\.days \}\)/)
    expect(monitor).toMatch(/enabled: false, timezone: browserTimezone\(\), local_time: '09:00', days:/)
    expect(monitor).not.toMatch(/interval_minutes|minMap|setAllCad/)
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
})
