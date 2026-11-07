import React, { useState } from 'react';
import { useHealthQuery, useExampleQuery } from './api/hooks';

export default function App() {
  const [search, setSearch] = useState('smarthack');
  const [activeQuery, setActiveQuery] = useState('smarthack');

  const health = useHealthQuery();
  const example = useExampleQuery(activeQuery);

  const handleSearch = (e: React.FormEvent) => {
    e.preventDefault();
    setActiveQuery(search);
  };

  return (
    <div className="max-w-4xl mx-auto px-4 py-12">
      {/* Header */}
      <header className="flex items-center justify-between border-b border-slate-800 pb-6 mb-8">
        <div>
          <h1 className="text-3xl font-extrabold tracking-tight bg-gradient-to-r from-blue-400 to-emerald-400 bg-clip-text text-transparent">
            Smarthack
          </h1>
          <p className="text-sm text-slate-400 mt-1">
            FastAPI + React Monorepo (24h Hackathon Edition)
          </p>
        </div>

        {/* Health status badge */}
        <div className="flex items-center gap-2 px-3 py-1.5 rounded-full border border-slate-700 bg-slate-800/60">
          <span
            className={`w-2.5 h-2.5 rounded-full ${
              health.isLoading
                ? 'bg-amber-400 animate-pulse'
                : health.isSuccess
                ? 'bg-emerald-400 shadow-[0_0_8px_rgba(52,211,153,0.6)]'
                : 'bg-rose-400'
            }`}
          />
          <span className="text-xs font-mono text-slate-300">
            {health.isLoading
              ? 'Checking backend...'
              : health.isSuccess
              ? 'API Online'
              : 'API Offline'}
          </span>
        </div>
      </header>

      {/* Main Content */}
      <main className="space-y-8">
        {/* Endpoint demonstration card */}
        <div className="bg-slate-800/50 border border-slate-700/80 rounded-xl p-6 shadow-xl">
          <h2 className="text-lg font-semibold text-slate-200 mb-2">
            Example Feature Endpoint
          </h2>
          <p className="text-sm text-slate-400 mb-6">
            Demonstrates end-to-end typed query flow through TanStack Query to{' '}
            <code className="text-xs bg-slate-900 px-1.5 py-0.5 rounded text-blue-300">
              GET /api/example?q=...
            </code>
          </p>

          <form onSubmit={handleSearch} className="flex gap-3 mb-6">
            <input
              type="text"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Enter search query..."
              className="flex-1 bg-slate-900 border border-slate-700 rounded-lg px-4 py-2.5 text-sm text-slate-100 placeholder-slate-500 focus:outline-none focus:ring-2 focus:ring-blue-500/50"
            />
            <button
              type="submit"
              className="bg-blue-600 hover:bg-blue-500 text-white font-medium px-5 py-2.5 rounded-lg text-sm transition-colors cursor-pointer"
            >
              Search
            </button>
          </form>

          {/* Results section */}
          <div className="bg-slate-900/80 rounded-lg border border-slate-800 p-4">
            {example.isLoading && (
              <p className="text-sm text-slate-400">Loading results from upstream...</p>
            )}

            {example.isError && (
              <div className="text-sm text-rose-400">
                <span className="font-semibold">Query failed: </span>
                {example.error instanceof Error
                  ? example.error.message
                  : 'An error occurred'}
                <p className="text-xs text-slate-500 mt-1">
                  (Note: in development, configure <code>SMARTHACK_EXAMPLE_SERVICE_URL</code> or test with a mock upstream)
                </p>
              </div>
            )}

            {example.isSuccess && (
              <div>
                <div className="flex items-center justify-between mb-3">
                  <span className="text-xs font-mono text-emerald-400">
                    Query: "{example.data.query}"
                  </span>
                  <span className="text-xs text-slate-500">
                    {example.data.items?.length ?? 0} items returned
                  </span>
                </div>
                <ul className="space-y-1 text-sm text-slate-300">
                  {example.data.items && example.data.items.length > 0 ? (
                    example.data.items.map((item, idx) => (
                      <li
                        key={idx}
                        className="bg-slate-800/40 px-3 py-1.5 rounded text-xs font-mono"
                      >
                        {item}
                      </li>
                    ))
                  ) : (
                    <li className="text-slate-500 italic text-xs">No items returned.</li>
                  )}
                </ul>
              </div>
            )}
          </div>
        </div>

        {/* Architecture summary */}
        <section className="grid grid-cols-1 md:grid-cols-2 gap-4">
          <div className="p-5 rounded-lg border border-slate-800 bg-slate-800/30">
            <h3 className="text-sm font-semibold text-blue-400 mb-1">
              Backend (FastAPI)
            </h3>
            <p className="text-xs text-slate-400 leading-relaxed">
              Thin routes under <code>/api</code>, typed Pydantic models in{' '}
              <code>smarthack/schemas</code>, and strict layer enforcement via AST guard.
            </p>
          </div>
          <div className="p-5 rounded-lg border border-slate-800 bg-slate-800/30">
            <h3 className="text-sm font-semibold text-emerald-400 mb-1">
              Frontend (Vite + React)
            </h3>
            <p className="text-xs text-slate-400 leading-relaxed">
              Auto-generated types from <code>openapi.json</code>, Tailwind CSS v4,
              and TanStack Query for cache & loading states.
            </p>
          </div>
        </section>
      </main>
    </div>
  );
}
