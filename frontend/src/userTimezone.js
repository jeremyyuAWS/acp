const TIMEZONES = {
  UTC: { short: 'UTC', name: 'UTC' },
  'America/Los_Angeles': { short: 'PT', name: 'US Pacific' },
  'America/Denver': { short: 'MT', name: 'US Mountain' },
  'America/Chicago': { short: 'CT', name: 'US Central' },
  'America/New_York': { short: 'ET', name: 'US Eastern' },
  'Asia/Kolkata': { short: 'IST', name: 'India' },
}

export function timezoneBadge(timezone) {
  return TIMEZONES[timezone] || { short: 'TZ', name: timezone || 'US Central' }
}
