import { Link } from 'react-router-dom'

export default function NotFound() {
  return (
    <div className="flex min-h-[60vh] flex-col items-center justify-center gap-3 text-center">
      <p className="text-5xl">🧭</p>
      <h1 className="text-xl font-semibold text-ink-900">Page not found</h1>
      <p className="max-w-sm text-sm text-ink-500">
        The page you were looking for does not exist or has been moved.
      </p>
      <Link to="/" className="btn-primary btn-sm mt-2">
        Back to the overview
      </Link>
    </div>
  )
}
