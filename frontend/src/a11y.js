// True when the user has asked the OS for reduced motion. Used to stop auto-
// advancing carousels/feeds (WCAG 2.2.2 Pause, Stop, Hide / 2.3.3 Animation).
export const prefersReducedMotion = () =>
  typeof window !== 'undefined' && !!window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches
