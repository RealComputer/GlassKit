function App() {
  return (
    <main className="min-h-screen bg-slate-950 text-slate-100">
      <div className="mx-auto flex w-full max-w-4xl flex-col gap-6 px-6 py-16">
        <span className="inline-flex w-fit rounded-full border border-slate-700 bg-slate-900 px-3 py-1 text-xs font-semibold uppercase tracking-wider text-slate-300">
          Tailwind Native Baseline
        </span>
        <h1 className="text-4xl font-semibold tracking-tight sm:text-5xl">
          Rokid Remember Web UI
        </h1>
        <p className="max-w-2xl text-base text-slate-300 sm:text-lg">
          Starter screen is intentionally built with Tailwind utilities only.
          Keep new UI work utility-first so we do not mix in legacy CSS
          patterns.
        </p>
        <div className="w-fit rounded-lg border border-slate-800 bg-slate-900/70 px-4 py-3 text-sm text-slate-300">
          Start building from{' '}
          <code className="rounded bg-slate-800 px-1.5 py-0.5 text-slate-100">
            src/App.tsx
          </code>
          .
        </div>
      </div>
    </main>
  )
}

export default App
