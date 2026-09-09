import { useEffect, useState } from 'react'
import { waterfallMotion } from './waterfallMotion.js'

export default function useWaterfallMotion(snapshot, view, options) {
  const [now, setNow] = useState(Date.now)
  const [hidden, setHidden] = useState(() => document.hidden)
  useEffect(() => {
    const visibility = () => { setHidden(document.hidden); setNow(Date.now()) }
    document.addEventListener('visibilitychange', visibility)
    return () => document.removeEventListener('visibilitychange', visibility)
  }, [])
  useEffect(() => {
    if (options.paused || hidden || snapshot.terminal) return undefined
    const timer = setInterval(() => setNow(Date.now()), 5_000)
    return () => clearInterval(timer)
  }, [options.paused, hidden, snapshot.terminal])
  return { ...waterfallMotion(snapshot, view, { ...options, now: Math.max(now, Date.now()), paused: options.paused || hidden }), hidden }
}
