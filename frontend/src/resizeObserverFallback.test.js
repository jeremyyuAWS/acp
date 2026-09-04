import { describe, expect, it, vi } from 'vitest'
import { ensureResizeObserver } from './resizeObserverFallback.js'

describe('Live Operations ResizeObserver fallback', () => {
  it('measures observed elements in browser environments without ResizeObserver', () => {
    const frame = []
    const scope = {
      requestAnimationFrame: (fn) => frame.push(fn),
      addEventListener: vi.fn(), removeEventListener: vi.fn(),
    }
    const Observer = ensureResizeObserver(scope)
    expect(new scope.DOMMatrixReadOnly('matrix(1, 0, 0, 0.75, 0, 0)').m22).toBe(0.75)
    const callback = vi.fn()
    const observer = new Observer(callback)
    const target = { getBoundingClientRect: () => ({ width: 900, height: 430 }) }
    observer.observe(target)
    frame[0]()
    expect(callback).toHaveBeenCalledWith([
      { target, contentRect: { width: 900, height: 430 } },
    ], observer)
    observer.disconnect()
    expect(scope.removeEventListener).toHaveBeenCalledWith('resize', observer.onResize)
  })

  it('leaves a native implementation untouched', () => {
    class NativeObserver {}
    class NativeMatrix {}
    const scope = { ResizeObserver: NativeObserver, DOMMatrixReadOnly: NativeMatrix }
    expect(ensureResizeObserver(scope)).toBe(NativeObserver)
    expect(scope.ResizeObserver).toBe(NativeObserver)
    expect(scope.DOMMatrixReadOnly).toBe(NativeMatrix)
  })
})
