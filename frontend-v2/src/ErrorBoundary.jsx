import { Component } from 'react'

// Keeps one throwing view from white-screening the whole app. Give it key={view}
// so switching tabs remounts it and clears the error.
export default class ErrorBoundary extends Component {
  constructor(props) { super(props); this.state = { err: null } }
  static getDerivedStateFromError(err) { return { err } }
  componentDidCatch(err, info) { console.error('UI error:', err, info) }
  render() {
    if (!this.state.err) return this.props.children
    return (
      <div className="empty" role="alert">
        <div className="emptyicon" aria-hidden="true">⚠</div>
        <h3 className="emptytitle">Something went wrong</h3>
        <p className="muted emptysub">This view hit an unexpected error. Reloading usually clears it; your scan data is safe.</p>
        <div className="emptyactions">
          <button onClick={() => window.location.reload()}>Reload</button>
        </div>
      </div>
    )
  }
}
