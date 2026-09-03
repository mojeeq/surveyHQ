/**
 * Keeps one broken panel from taking the page with it.
 *
 * React unmounts the whole tree when a render throws, so a single card that
 * cannot draw its data leaves a blank white screen with no way back - which is
 * what a saved cross-tab handed to the chart renderer used to do to the whole
 * Dashboards page. Wrapping the panels means the failure stays the size of the
 * thing that failed.
 */
import { Component, type ErrorInfo, type ReactNode } from 'react'

interface Props {
  children: ReactNode
  /** What could not be shown, e.g. "this chart". Used in the message. */
  what?: string
}

interface State {
  error: Error | null
}

export default class ErrorBoundary extends Component<Props, State> {
  state: State = { error: null }

  static getDerivedStateFromError(error: Error): State {
    return { error }
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    // The console is where a developer looks after a user reports a panel that
    // will not draw; the message on screen is deliberately not a stack trace.
    console.error('Panel failed to render:', error, info.componentStack)
  }

  render() {
    if (!this.state.error) return this.props.children
    return (
      <div className="rounded-lg border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-900">
        <p className="font-medium">Could not show {this.props.what ?? 'this panel'}</p>
        <p className="mt-1 text-xs text-amber-800">{this.state.error.message}</p>
        <button
          className="mt-2 text-xs font-semibold underline"
          onClick={() => this.setState({ error: null })}
        >
          Try again
        </button>
      </div>
    )
  }
}
