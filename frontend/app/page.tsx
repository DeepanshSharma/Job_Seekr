"use client";

import { useEffect, useState, useCallback } from "react";

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

type Application = {
  id: string;
  status: string;
  priority_tier: number | null;
  edge_score: number;
  routing_reason: string;
  assigned_resume_id: string | null;
  jobs: {
    job_title: string;
    company_name: string;
    location: string;
    posted_at: string;
    sponsor_risk_flag: boolean;
    rejection_reason: string | null;
  };
  resumes: { role_type: string } | null;
};

const TIER_COLORS: Record<number, string> = {
  1: "bg-yellow-500 text-black",
  2: "bg-blue-600 text-white",
  3: "bg-gray-600 text-white",
};

const STATUS_COLORS: Record<string, string> = {
  Pending: "text-yellow-400",
  Auto_Apply_Ready: "text-green-400",
  "Auto-Apply_Ready": "text-green-400",
  Manual_Review: "text-blue-400",
  Rejected: "text-red-400",
};

function daysAgo(iso: string): string {
  const diff = Date.now() - new Date(iso).getTime();
  const d = Math.floor(diff / 86400000);
  return d === 0 ? "today" : `${d}d ago`;
}

export default function TriagePage() {
  const [apps, setApps] = useState<Application[]>([]);
  const [loading, setLoading] = useState(true);
  const [running, setRunning] = useState(false);
  const [clearing, setClearing] = useState(false);
  const [pipelineResult, setPipelineResult] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const fetchApps = useCallback(async () => {
    try {
      const res = await fetch(`${API_BASE}/api/jobs`);
      if (!res.ok) throw new Error(`Backend error: ${res.status}`);
      const data = await res.json();
      setApps(data);
      setError(null);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Failed to fetch jobs. Is the backend running?");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchApps();
  }, [fetchApps]);

  async function runPipeline() {
    setRunning(true);
    setPipelineResult(null);
    setError(null);
    try {
      const res = await fetch(`${API_BASE}/api/process-jobs`, { method: "POST" });
      if (!res.ok) throw new Error(`Pipeline error: ${res.status}`);
      const result = await res.json();
      setPipelineResult(
        `Done — ${result.passed?.length ?? 0} passed | ${result.dropped_too_old?.length ?? 0} too old | ${result.dropped_blocks_opt?.length ?? 0} blocks OPT`
      );
      await fetchApps();
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Pipeline failed.");
    } finally {
      setRunning(false);
    }
  }

  async function clearAll() {
    setClearing(true);
    setError(null);
    try {
      await fetch(`${API_BASE}/api/jobs/clear`, { method: "DELETE" });
      setPipelineResult(null);
      await fetchApps();
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Clear failed.");
    } finally {
      setClearing(false);
    }
  }

  const passed = apps.filter((a) => a.status !== "Rejected");
  const rejected = apps.filter((a) => a.status === "Rejected");

  return (
    <div className="max-w-7xl mx-auto space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-white">Triage Board</h1>
          <p className="text-sm text-gray-500 mt-1">
            {apps.length} total records · {passed.length} active · {rejected.length} rejected
          </p>
        </div>
        <div className="flex gap-3">
          <button
            onClick={clearAll}
            disabled={clearing || running}
            className="px-4 py-2 text-sm border border-gray-700 rounded hover:border-red-600 hover:text-red-400 transition-colors disabled:opacity-40"
          >
            {clearing ? "Clearing…" : "Clear All"}
          </button>
          <button
            onClick={runPipeline}
            disabled={running || clearing}
            className="px-4 py-2 text-sm bg-indigo-600 hover:bg-indigo-500 rounded font-semibold transition-colors disabled:opacity-40"
          >
            {running ? "Running pipeline…" : "Run Pipeline"}
          </button>
        </div>
      </div>

      {/* Status bar */}
      {pipelineResult && (
        <div className="text-sm text-green-400 border border-green-800 bg-green-950 rounded px-4 py-2">
          {pipelineResult}
        </div>
      )}
      {error && (
        <div className="text-sm text-red-400 border border-red-800 bg-red-950 rounded px-4 py-2">
          {error}
        </div>
      )}

      {/* Active jobs table */}
      <section>
        <h2 className="text-sm font-semibold text-gray-400 uppercase tracking-wider mb-3">
          Active Jobs
        </h2>
        {loading ? (
          <p className="text-gray-500 text-sm">Loading…</p>
        ) : passed.length === 0 ? (
          <p className="text-gray-600 text-sm">
            No active jobs yet. Click &ldquo;Run Pipeline&rdquo; to process the mock data.
          </p>
        ) : (
          <div className="overflow-x-auto rounded border border-gray-800">
            <table className="w-full text-sm">
              <thead className="bg-gray-900 text-gray-400 text-xs uppercase">
                <tr>
                  <th className="px-4 py-3 text-left">Job</th>
                  <th className="px-4 py-3 text-left">Company</th>
                  <th className="px-4 py-3 text-left">Location</th>
                  <th className="px-4 py-3 text-left">Posted</th>
                  <th className="px-4 py-3 text-left">Tier</th>
                  <th className="px-4 py-3 text-left">Sponsor OK</th>
                  <th className="px-4 py-3 text-left">Resume</th>
                  <th className="px-4 py-3 text-left">Status</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-800">
                {passed.map((app) => (
                  <tr key={app.id} className="hover:bg-gray-900 transition-colors">
                    <td className="px-4 py-3 text-white">{app.jobs?.job_title}</td>
                    <td className="px-4 py-3 text-gray-300">{app.jobs?.company_name}</td>
                    <td className="px-4 py-3 text-gray-400">{app.jobs?.location}</td>
                    <td className="px-4 py-3 text-gray-500">
                      {app.jobs?.posted_at ? daysAgo(app.jobs.posted_at) : "—"}
                    </td>
                    <td className="px-4 py-3">
                      {app.priority_tier ? (
                        <span className={`px-2 py-0.5 rounded text-xs font-bold ${TIER_COLORS[app.priority_tier]}`}>
                          T{app.priority_tier}
                        </span>
                      ) : "—"}
                    </td>
                    <td className="px-4 py-3">
                      {app.jobs?.sponsor_risk_flag ? (
                        <span className="text-red-400">✗</span>
                      ) : (
                        <span className="text-green-400">✓</span>
                      )}
                    </td>
                    <td className="px-4 py-3">
                      {app.resumes?.role_type ? (
                        <span className="px-2 py-0.5 rounded bg-gray-800 text-gray-300 text-xs">
                          {app.resumes.role_type}
                        </span>
                      ) : "—"}
                    </td>
                    <td className={`px-4 py-3 text-xs font-semibold ${STATUS_COLORS[app.status] ?? "text-gray-400"}`}>
                      {app.status}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      {/* Rejected jobs table */}
      {rejected.length > 0 && (
        <section>
          <h2 className="text-sm font-semibold text-gray-600 uppercase tracking-wider mb-3">
            Rejected ({rejected.length})
          </h2>
          <div className="overflow-x-auto rounded border border-gray-800 opacity-60">
            <table className="w-full text-sm">
              <thead className="bg-gray-900 text-gray-500 text-xs uppercase">
                <tr>
                  <th className="px-4 py-3 text-left">Job</th>
                  <th className="px-4 py-3 text-left">Company</th>
                  <th className="px-4 py-3 text-left">Reason</th>
                  <th className="px-4 py-3 text-left">Details</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-800">
                {rejected.map((app) => (
                  <tr key={app.id}>
                    <td className="px-4 py-3 text-gray-500">{app.jobs?.job_title}</td>
                    <td className="px-4 py-3 text-gray-500">{app.jobs?.company_name}</td>
                    <td className="px-4 py-3">
                      <span className="px-2 py-0.5 rounded bg-red-950 text-red-400 text-xs">
                        {app.jobs?.rejection_reason === "too_old" ? "Too Old" : "Blocks OPT"}
                      </span>
                    </td>
                    <td className="px-4 py-3 text-gray-600 text-xs">{app.routing_reason}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      )}
    </div>
  );
}
