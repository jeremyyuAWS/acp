// ReactFlow measures its canvas with ResizeObserver. Modern browsers provide it, but embedded,
// hardened, and older enterprise browser runtimes may not. Without a fallback the entire Live
// Operations view throws before the first node renders. This intentionally implements only the
// observer contract ReactFlow needs: initial measurement plus remeasurement on window resize.
export function ensureResizeObserver(scope = globalThis) {
  // ReactFlow reads only m22 (the Y scale) from this matrix while measuring nodes. Enterprise
  // webviews that omit ResizeObserver can omit DOMMatrixReadOnly too, so install the equally
  // narrow companion fallback rather than fixing one missing platform API and throwing on the next.
  if (typeof scope.DOMMatrixReadOnly === 'undefined') {
    scope.DOMMatrixReadOnly = class DOMMatrixReadOnlyFallback {
      constructor(transform = '') {
        const values = String(transform).match(/matrix(?:3d)?\(([^)]+)\)/)?.[1]
          ?.split(',').map((value) => Number(value.trim())) || []
        this.m22 = values.length === 16 ? (values[5] || 1) : (values[3] || 1)
      }
    }
  }
  if (typeof scope.ResizeObserver !== 'undefined') return scope.ResizeObserver

  class ResizeObserverFallback {
    constructor(callback) {
      this.callback = callback
      this.elements = new Set()
      this.onResize = () => this.measure()
    }

    measure() {
      if (!this.elements.size) return
      const entries = [...this.elements].map((target) => ({
        target,
        contentRect: target.getBoundingClientRect(),
      }))
      this.callback(entries, this)
    }

    observe(target) {
      this.elements.add(target)
      scope.addEventListener?.('resize', this.onResize)
      scope.requestAnimationFrame?.(() => this.measure())
    }

    unobserve(target) {
      this.elements.delete(target)
      if (!this.elements.size) scope.removeEventListener?.('resize', this.onResize)
    }

    disconnect() {
      this.elements.clear()
      scope.removeEventListener?.('resize', this.onResize)
    }
  }

  scope.ResizeObserver = ResizeObserverFallback
  return ResizeObserverFallback
}
