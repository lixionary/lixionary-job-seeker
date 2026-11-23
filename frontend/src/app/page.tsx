"use client";

import React, { useCallback, useEffect, useMemo, useState } from "react";
import {
  AlertTriangle,
  Briefcase,
  CheckCircle2,
  Clock,
  Copy,
  ExternalLink,
  FileText,
  Filter,
  Loader2,
  MapPin,
  Plus,
  RefreshCw,
  Search,
  Send,
  Settings,
  Sparkles,
  X,
} from "lucide-react";

type JobStatus =
  | "new"
  | "shortlisted"
  | "applied"
  | "interviewing"
  | "archived"
  | "filtered_out";

interface SourceUrl {
  source: string;
  url: string;
}

interface LLMAnalysis {
  match_score: number;
  role_track: string;
  location_policy: string;
  relocation_or_visa_note: string;
  summary: string;
  match_reasons: string[];
  red_flags: string[];
  tailoring_angle: string;
  scored_by?: string;
}

interface TailoredPitch {
  cv_summary: string;
  emphasized_bullets: string[];
  outreach_message: string;
  generated_by: string;
  generated_at: string;
}

interface JobItem {
  id: string;
  dedup_hash: string;
  company: string;
  title: string;
  location_raw: string;
  description: string;
  source_urls: SourceUrl[];
  status: JobStatus;
  match_score: number | null;
  role_track: string | null;
  location_policy: string | null;
  llm_analysis: LLMAnalysis | null;
  tailored_pitch: TailoredPitch | null;
  notes: string;
  filter_reason?: string | null;
  first_seen_at: string;
  last_seen_at: string;
  updated_at: string;
}

interface ScrapeRun {
  id: string;
  connector_name: string;
  started_at: string;
  finished_at?: string;
  status: string;
  jobs_fetched: number;
  jobs_new: number;
  jobs_scored: number;
  jobs_filtered: number;
  tokens_used: number;
  error_message?: string | null;
}

interface HealthInfo {
  status: string;
  total_jobs: number;
  ingest_running: boolean;
  llm_enabled: boolean;
  llm_model: string;
  telegram_enabled: boolean;
}

const COLUMNS: { key: JobStatus; label: string; accent: string }[] = [
  { key: "new", label: "New Matches", accent: "border-emerald-500/40" },
  { key: "shortlisted", label: "Shortlisted", accent: "border-sky-500/40" },
  { key: "applied", label: "Applied", accent: "border-indigo-500/40" },
  { key: "interviewing", label: "Interviewing", accent: "border-amber-500/40" },
  { key: "archived", label: "Archived / Rejected", accent: "border-slate-700" },
];

function scoreBadgeClass(score: number | null): string {
  if (score === null || score === undefined) {
    return "bg-slate-800 text-slate-400 border-slate-700";
  }
  if (score >= 8) {
    return "bg-emerald-500/20 text-emerald-300 border-emerald-500/40";
  }
  if (score >= 7) {
    return "bg-sky-500/20 text-sky-300 border-sky-500/40";
  }
  if (score >= 5) {
    return "bg-amber-500/20 text-amber-300 border-amber-500/40";
  }
  return "bg-rose-500/20 text-rose-300 border-rose-500/40";
}

function formatAge(iso: string): string {
  if (!iso) return "";
  const diffMs = Date.now() - new Date(iso).getTime();
  const mins = Math.max(1, Math.floor(diffMs / 60000));
  if (mins < 60) return `${mins}m ago`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return `${hrs}h ago`;
  const days = Math.floor(hrs / 24);
  return `${days}d ago`;
}

export default function JobRadarDashboard() {
  const [jobs, setJobs] = useState<JobItem[]>([]);
  const [counts, setCounts] = useState<Record<string, number>>({});
  const [health, setHealth] = useState<HealthInfo | null>(null);
  const [loading, setLoading] = useState<boolean>(true);

  // Filters
  const [highSignalOnly, setHighSignalOnly] = useState<boolean>(true);
  const [searchQuery, setSearchQuery] = useState<string>("");
  const [trackFilter, setTrackFilter] = useState<string>("");

  // Active drawer / modals
  const [selectedJob, setSelectedJob] = useState<JobItem | null>(null);
  const [notesDraft, setNotesDraft] = useState<string>("");
  const [savingNotes, setSavingNotes] = useState<boolean>(false);
  const [tailoring, setTailoring] = useState<boolean>(false);
  const [rescoring, setRescoring] = useState<boolean>(false);
  const [copiedKey, setCopiedKey] = useState<string>("");

  // Manual Entry Modal
  const [showManualModal, setShowManualModal] = useState<boolean>(false);
  const [manualCompany, setManualCompany] = useState<string>("");
  const [manualTitle, setManualTitle] = useState<string>("");
  const [manualLocation, setManualLocation] = useState<string>("Jakarta, Indonesia");
  const [manualUrl, setManualUrl] = useState<string>("");
  const [manualDesc, setManualDesc] = useState<string>("");
  const [submittingManual, setSubmittingManual] = useState<boolean>(false);

  // Scrape Runs Modal
  const [showRunsModal, setShowRunsModal] = useState<boolean>(false);
  const [runs, setRuns] = useState<ScrapeRun[]>([]);
  const [isScraping, setIsScraping] = useState<boolean>(false);

  // Digest Modal
  const [showDigestModal, setShowDigestModal] = useState<boolean>(false);
  const [digestPreview, setDigestPreview] = useState<string>("");
  const [digestSending, setDigestSending] = useState<boolean>(false);
  const [digestNote, setDigestNote] = useState<string>("");

  // Config Editor Modal
  const [showConfigModal, setShowConfigModal] = useState<boolean>(false);
  const [activeConfigTab, setActiveConfigTab] = useState<"cv" | "preferences" | "companies">("cv");
  const [cvDraft, setCvDraft] = useState<string>("");
  const [prefDraft, setPrefDraft] = useState<string>("");
  const [compDraft, setCompDraft] = useState<string>("");
  const [savingConfig, setSavingConfig] = useState<boolean>(false);
  const [configStatus, setConfigStatus] = useState<string>("");

  const fetchDashboardData = useCallback(async () => {
    try {
      const params = new URLSearchParams();
      if (highSignalOnly) {
        params.set("min_score", "7");
      }
      if (trackFilter) {
        params.set("role_track", trackFilter);
      }
      if (searchQuery.trim()) {
        params.set("search", searchQuery.trim());
      }
      const [jobsRes, healthRes] = await Promise.all([
        fetch(`/api/jobs?${params.toString()}`),
        fetch("/api/health"),
      ]);
      if (jobsRes.ok) {
        const data = await jobsRes.json();
        setJobs(data.items || []);
        setCounts(data.counts || {});
      }
      if (healthRes.ok) {
        const h = await healthRes.json();
        setHealth(h);
        setIsScraping(Boolean(h.ingest_running));
      }
    } finally {
      setLoading(false);
    }
  }, [highSignalOnly, trackFilter, searchQuery]);

  useEffect(() => {
    fetchDashboardData();
  }, [fetchDashboardData]);

  // Poll while scrape is running
  useEffect(() => {
    if (!isScraping) return;
    const timer = setInterval(async () => {
      await fetchDashboardData();
      const res = await fetch("/api/runs");
      if (res.ok) {
        const data = await res.json();
        setRuns(data.items || []);
        if (!data.is_running) {
          setIsScraping(false);
        }
      }
    }, 3000);
    return () => clearInterval(timer);
  }, [isScraping, fetchDashboardData]);

  const handleSelectJob = (job: JobItem) => {
    setSelectedJob(job);
    setNotesDraft(job.notes || "");
  };

  const handleStatusChange = async (jobId: string, newStatus: JobStatus) => {
    const res = await fetch(`/api/jobs/${jobId}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ status: newStatus }),
    });
    if (res.ok) {
      const updated = await res.json();
      setJobs((prev) => prev.map((j) => (j.id === jobId ? updated : j)));
      if (selectedJob?.id === jobId) {
        setSelectedJob(updated);
      }
      fetchDashboardData();
    }
  };

  const handleSaveNotes = async () => {
    if (!selectedJob) return;
    setSavingNotes(true);
    try {
      const res = await fetch(`/api/jobs/${selectedJob.id}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ notes: notesDraft }),
      });
      if (res.ok) {
        const updated = await res.json();
        setSelectedJob(updated);
        setJobs((prev) => prev.map((j) => (j.id === updated.id ? updated : j)));
      }
    } finally {
      setSavingNotes(false);
    }
  };

  const handleGeneratePitch = async () => {
    if (!selectedJob) return;
    setTailoring(true);
    try {
      const res = await fetch(`/api/jobs/${selectedJob.id}/tailor`, {
        method: "POST",
      });
      if (res.ok) {
        const updated = await res.json();
        setSelectedJob(updated);
        setJobs((prev) => prev.map((j) => (j.id === updated.id ? updated : j)));
      }
    } finally {
      setTailoring(false);
    }
  };

  const handleRescoreJob = async () => {
    if (!selectedJob) return;
    setRescoring(true);
    try {
      const res = await fetch(`/api/jobs/${selectedJob.id}/rescore`, {
        method: "POST",
      });
      if (res.ok) {
        const updated = await res.json();
        setSelectedJob(updated);
        setJobs((prev) => prev.map((j) => (j.id === updated.id ? updated : j)));
        fetchDashboardData();
      }
    } finally {
      setRescoring(false);
    }
  };

  const handleTriggerScrape = async () => {
    setIsScraping(true);
    await fetch("/api/runs/trigger", { method: "POST" });
    const runsRes = await fetch("/api/runs");
    if (runsRes.ok) {
      const data = await runsRes.json();
      setRuns(data.items || []);
    }
  };

  const handleOpenRuns = async () => {
    setShowRunsModal(true);
    const res = await fetch("/api/runs");
    if (res.ok) {
      const data = await res.json();
      setRuns(data.items || []);
      setIsScraping(Boolean(data.is_running));
    }
  };

  const handleOpenDigest = async () => {
    setShowDigestModal(true);
    setDigestNote("");
    const res = await fetch("/api/digest/preview");
    if (res.ok) {
      const data = await res.json();
      setDigestPreview(data.message || "");
    }
  };

  const handleSendDigest = async () => {
    setDigestSending(true);
    try {
      const res = await fetch("/api/digest/send", { method: "POST" });
      if (res.ok) {
        const data = await res.json();
        setDigestNote(
          data.sent
            ? "Daily digest sent to Telegram!"
            : data.note || data.error || "Telegram not configured in .env; preview shown above."
        );
      }
    } finally {
      setDigestSending(false);
    }
  };

  const handleOpenConfig = async () => {
    setShowConfigModal(true);
    setConfigStatus("");
    const res = await fetch("/api/config");
    if (res.ok) {
      const data = await res.json();
      setCvDraft(data.cv_markdown || "");
      setPrefDraft(data.preferences_yaml || "");
      setCompDraft(data.companies_yaml || "");
    }
  };

  const handleSaveConfig = async () => {
    setSavingConfig(true);
    setConfigStatus("");
    try {
      const res = await fetch("/api/config", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          cv_markdown: cvDraft,
          preferences_yaml: prefDraft,
          companies_yaml: compDraft,
        }),
      });
      if (res.ok) {
        setConfigStatus("Saved to MongoDB & synced to config/ files on disk.");
      } else {
        const err = await res.json();
        setConfigStatus(`Error: ${err.detail || "Failed to save config"}`);
      }
    } finally {
      setSavingConfig(false);
    }
  };

  const handleManualSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setSubmittingManual(true);
    try {
      const res = await fetch("/api/jobs/manual", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          company: manualCompany,
          title: manualTitle,
          location_raw: manualLocation,
          url: manualUrl,
          description: manualDesc,
        }),
      });
      if (res.ok) {
        const data = await res.json();
        setShowManualModal(false);
        setManualCompany("");
        setManualTitle("");
        setManualUrl("");
        setManualDesc("");
        await fetchDashboardData();
        if (data.job) {
          handleSelectJob(data.job);
        }
      }
    } finally {
      setSubmittingManual(false);
    }
  };

  const copyText = (key: string, text: string) => {
    navigator.clipboard.writeText(text);
    setCopiedKey(key);
    setTimeout(() => setCopiedKey(""), 2000);
  };

  const jobsByColumn = useMemo(() => {
    const grouped: Record<JobStatus, JobItem[]> = {
      new: [],
      shortlisted: [],
      applied: [],
      interviewing: [],
      archived: [],
      filtered_out: [],
    };
    for (const job of jobs) {
      if (grouped[job.status]) {
        grouped[job.status].push(job);
      }
    }
    return grouped;
  }, [jobs]);

  return (
    <div className="min-h-screen flex flex-col bg-slate-950 text-slate-100">
      {/* Top Header */}
      <header className="sticky top-0 z-20 border-b border-slate-800 bg-slate-950/90 backdrop-blur px-6 py-4">
        <div className="max-w-[1800px] mx-auto flex flex-wrap items-center justify-between gap-4">
          <div className="flex items-center gap-3">
            <div className="h-10 w-10 rounded-xl bg-emerald-500/15 border border-emerald-500/40 flex items-center justify-center text-emerald-400">
              <Briefcase className="h-5 w-5" />
            </div>
            <div>
              <div className="flex items-center gap-2.5">
                <h1 className="text-lg font-bold tracking-tight text-white">
                  Lixionary Job Radar & Triage
                </h1>
                <span
                  className={`text-xs px-2.5 py-0.5 rounded-full border ${
                    health?.llm_enabled
                      ? "bg-emerald-500/15 text-emerald-300 border-emerald-500/30"
                      : "bg-amber-500/15 text-amber-300 border-amber-500/30"
                  }`}
                >
                  {health?.llm_enabled
                    ? `LLM: ${health.llm_model}`
                    : "Scorer: Heuristic Fallback (Set LLM_API_KEY for MiniMax)"}
                </span>
              </div>
              <p className="text-xs text-slate-400">
                Engineering Leadership · Quality Engineering Leadership · Strategic IC ({health?.total_jobs ?? 0} total tracked,{" "}
                {counts.filtered_out ?? 0} pre-filtered)
              </p>
            </div>
          </div>

          {/* Action Buttons */}
          <div className="flex flex-wrap items-center gap-2.5">
            <button
              onClick={() => setShowManualModal(true)}
              className="inline-flex items-center gap-1.5 px-3.5 py-2 rounded-lg text-xs font-medium bg-slate-800 hover:bg-slate-700 text-slate-100 border border-slate-700 transition"
            >
              <Plus className="h-4 w-4 text-emerald-400" />
              Add Manual Job
            </button>

            <button
              onClick={handleTriggerScrape}
              disabled={isScraping}
              className="inline-flex items-center gap-1.5 px-3.5 py-2 rounded-lg text-xs font-medium bg-emerald-600 hover:bg-emerald-500 disabled:opacity-60 text-white transition"
            >
              <RefreshCw className={`h-4 w-4 ${isScraping ? "animate-spin" : ""}`} />
              {isScraping ? "Scraping Boards..." : "Trigger Scrape"}
            </button>

            <button
              onClick={handleOpenRuns}
              className="inline-flex items-center gap-1.5 px-3 py-2 rounded-lg text-xs font-medium bg-slate-900 hover:bg-slate-800 text-slate-300 border border-slate-800 transition"
            >
              <Clock className="h-4 w-4 text-sky-400" />
              Runs
            </button>

            <button
              onClick={handleOpenDigest}
              className="inline-flex items-center gap-1.5 px-3 py-2 rounded-lg text-xs font-medium bg-slate-900 hover:bg-slate-800 text-slate-300 border border-slate-800 transition"
            >
              <Send className="h-4 w-4 text-indigo-400" />
              Daily Digest
            </button>

            <button
              onClick={handleOpenConfig}
              className="inline-flex items-center gap-1.5 px-3 py-2 rounded-lg text-xs font-medium bg-slate-900 hover:bg-slate-800 text-slate-300 border border-slate-800 transition"
            >
              <Settings className="h-4 w-4 text-amber-400" />
              CV & Config
            </button>
          </div>
        </div>

        {/* Filter Bar */}
        <div className="max-w-[1800px] mx-auto mt-3 pt-3 border-t border-slate-800/80 flex flex-wrap items-center justify-between gap-3">
          <div className="flex flex-wrap items-center gap-3">
            <div className="relative">
              <Search className="h-4 w-4 text-slate-500 absolute left-3 top-1/2 -translate-y-1/2" />
              <input
                type="text"
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                placeholder="Search company, title, location, notes..."
                className="pl-9 pr-4 py-1.5 bg-slate-900 border border-slate-800 rounded-lg text-xs text-slate-100 placeholder-slate-500 focus:outline-none focus:border-emerald-500 w-72"
              />
            </div>

            <select
              value={trackFilter}
              onChange={(e) => setTrackFilter(e.target.value)}
              className="px-3 py-1.5 bg-slate-900 border border-slate-800 rounded-lg text-xs text-slate-200 focus:outline-none focus:border-emerald-500"
            >
              <option value="">All Target Role Tracks</option>
              <option value="Engineering Leadership">Engineering Leadership</option>
              <option value="Quality Engineering Leadership">Quality Engineering Leadership</option>
              <option value="Hands-on Strategic IC">Hands-on Strategic IC</option>
            </select>
          </div>

          <div className="flex items-center gap-3">
            <button
              onClick={() => setHighSignalOnly(!highSignalOnly)}
              className={`inline-flex items-center gap-2 px-3 py-1.5 rounded-lg text-xs font-medium border transition ${
                highSignalOnly
                  ? "bg-emerald-500/15 text-emerald-300 border-emerald-500/40"
                  : "bg-slate-900 text-slate-400 border-slate-800"
              }`}
            >
              <Filter className="h-3.5 w-3.5" />
              {highSignalOnly ? "Showing High-Signal Only (Score ≥ 7)" : "Showing All Scores (1–10)"}
            </button>
          </div>
        </div>
      </header>

      {/* Main Kanban Board */}
      <main className="flex-1 p-6 overflow-x-auto">
        {loading ? (
          <div className="h-96 flex items-center justify-center text-slate-400 gap-2">
            <Loader2 className="h-5 w-5 animate-spin text-emerald-400" />
            Loading Job Radar Kanban Board...
          </div>
        ) : (
          <div className="max-w-[1800px] mx-auto grid grid-cols-1 md:grid-cols-3 lg:grid-cols-5 gap-4 min-w-[1100px]">
            {COLUMNS.map((col) => {
              const colJobs = jobsByColumn[col.key] || [];
              return (
                <div
                  key={col.key}
                  className={`flex flex-col rounded-xl bg-slate-900/70 border ${col.accent} min-h-[72vh] max-h-[82vh]`}
                >
                  <div className="px-4 py-3 border-b border-slate-800 flex items-center justify-between">
                    <span className="text-xs font-semibold uppercase tracking-wider text-slate-300">
                      {col.label}
                    </span>
                    <span className="text-xs px-2 py-0.5 rounded-full bg-slate-800 text-slate-300 font-medium">
                      {colJobs.length}
                    </span>
                  </div>

                  <div className="p-3 space-y-2.5 overflow-y-auto flex-1">
                    {colJobs.length === 0 ? (
                      <div className="h-36 flex flex-col items-center justify-center text-center px-4 text-xs text-slate-500 border border-dashed border-slate-800 rounded-lg">
                        No roles in {col.label}
                      </div>
                    ) : (
                      colJobs.map((job) => (
                        <div
                          key={job.id}
                          onClick={() => handleSelectJob(job)}
                          className={`group p-3.5 rounded-lg bg-slate-950/90 hover:bg-slate-900 border transition cursor-pointer ${
                            selectedJob?.id === job.id
                              ? "border-emerald-500 ring-1 ring-emerald-500/30"
                              : "border-slate-800/90 hover:border-slate-700"
                          }`}
                        >
                          <div className="flex items-start justify-between gap-2">
                            <span className="text-xs font-semibold text-emerald-400 truncate">
                              {job.company}
                            </span>
                            <span
                              className={`text-xs font-bold px-2 py-0.5 rounded-md border shrink-0 ${scoreBadgeClass(
                                job.match_score
                              )}`}
                            >
                              {job.match_score ?? "?"}/10
                            </span>
                          </div>

                          <h3 className="mt-1 text-sm font-semibold text-slate-100 group-hover:text-white leading-snug">
                            {job.title}
                          </h3>

                          <div className="mt-2 flex flex-wrap items-center gap-1.5 text-[11px] text-slate-400">
                            {job.role_track && (
                              <span className="px-2 py-0.5 rounded bg-slate-900 border border-slate-800 text-slate-300">
                                {job.role_track}
                              </span>
                            )}
                            {(job.location_policy || job.location_raw) && (
                              <span className="inline-flex items-center gap-1 text-slate-400 truncate max-w-full">
                                <MapPin className="h-3 w-3 text-slate-500 shrink-0" />
                                <span className="truncate">
                                  {job.location_policy || job.location_raw}
                                </span>
                              </span>
                            )}
                          </div>

                          {job.llm_analysis?.summary && (
                            <p className="mt-2 text-xs text-slate-400 line-clamp-2">
                              {job.llm_analysis.summary}
                            </p>
                          )}

                          <div className="mt-3 pt-2 border-t border-slate-900 flex items-center justify-between text-[11px] text-slate-500">
                            <div className="flex items-center gap-1 flex-wrap">
                              {(job.source_urls || []).map((s, i) => (
                                <span
                                  key={i}
                                  className="px-1.5 py-0.5 rounded bg-slate-900 text-slate-400 border border-slate-800"
                                >
                                  {s.source}
                                </span>
                              ))}
                            </div>
                            <span>{formatAge(job.first_seen_at)}</span>
                          </div>
                        </div>
                      ))
                    )}
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </main>

      {/* Job Detail Drawer */}
      {selectedJob && (
        <div className="fixed inset-0 z-40 flex justify-end bg-black/60 backdrop-blur-sm">
          <div className="w-full max-w-2xl bg-slate-950 border-l border-slate-800 h-full flex flex-col overflow-hidden shadow-2xl">
            {/* Drawer Header */}
            <div className="px-6 py-4 border-b border-slate-800 flex items-start justify-between gap-4 bg-slate-900/60">
              <div>
                <div className="flex items-center gap-2">
                  <span className="text-xs font-bold uppercase tracking-wider text-emerald-400">
                    {selectedJob.company}
                  </span>
                  <span
                    className={`text-xs font-bold px-2 py-0.5 rounded border ${scoreBadgeClass(
                      selectedJob.match_score
                    )}`}
                  >
                    Match Score: {selectedJob.match_score ?? "?"}/10
                  </span>
                  {selectedJob.llm_analysis?.scored_by && (
                    <span className="text-[11px] px-2 py-0.5 rounded bg-slate-800 text-slate-400">
                      via {selectedJob.llm_analysis.scored_by}
                    </span>
                  )}
                </div>
                <h2 className="mt-1 text-lg font-bold text-white">
                  {selectedJob.title}
                </h2>
                <p className="text-xs text-slate-400 mt-0.5">
                  {selectedJob.location_policy || selectedJob.location_raw || "Location Unspecified"} ·{" "}
                  {selectedJob.role_track || "General"}
                </p>
              </div>
              <button
                onClick={() => setSelectedJob(null)}
                className="p-1.5 rounded-lg bg-slate-900 hover:bg-slate-800 text-slate-400 hover:text-white"
              >
                <X className="h-5 w-5" />
              </button>
            </div>

            {/* Drawer Body */}
            <div className="flex-1 overflow-y-auto p-6 space-y-6">
              {/* Status & Quick Actions Bar */}
              <div className="flex flex-wrap items-center justify-between gap-3 p-3.5 rounded-xl bg-slate-900 border border-slate-800">
                <div className="flex items-center gap-2">
                  <span className="text-xs font-medium text-slate-400">Stage:</span>
                  <select
                    value={selectedJob.status}
                    onChange={(e) =>
                      handleStatusChange(selectedJob.id, e.target.value as JobStatus)
                    }
                    className="px-3 py-1.5 rounded-lg bg-slate-950 border border-slate-700 text-xs font-semibold text-white focus:outline-none focus:border-emerald-500"
                  >
                    <option value="new">New</option>
                    <option value="shortlisted">Shortlisted</option>
                    <option value="applied">Applied</option>
                    <option value="interviewing">Interviewing</option>
                    <option value="archived">Archived / Rejected</option>
                  </select>
                </div>

                <div className="flex items-center gap-2">
                  <button
                    onClick={handleRescoreJob}
                    disabled={rescoring}
                    className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium bg-slate-800 hover:bg-slate-700 text-slate-200 border border-slate-700 transition"
                  >
                    <RefreshCw className={`h-3.5 w-3.5 ${rescoring ? "animate-spin" : ""}`} />
                    {rescoring ? "Scoring..." : "Re-Score"}
                  </button>

                  {(selectedJob.source_urls || []).map((s, idx) =>
                    s.url ? (
                      <a
                        key={idx}
                        href={s.url}
                        target="_blank"
                        rel="noreferrer"
                        className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium bg-emerald-600 hover:bg-emerald-500 text-white transition"
                      >
                        Apply ({s.source})
                        <ExternalLink className="h-3.5 w-3.5" />
                      </a>
                    ) : null
                  )}
                </div>
              </div>

              {/* LLM Fit Breakdown */}
              {selectedJob.llm_analysis && (
                <div className="p-4 rounded-xl bg-slate-900/80 border border-slate-800 space-y-4">
                  <div className="flex items-center justify-between">
                    <h3 className="text-xs font-bold uppercase tracking-wider text-slate-300 flex items-center gap-1.5">
                      <Sparkles className="h-4 w-4 text-emerald-400" />
                      Candidate Fit Analysis (vs. config/cv.md)
                    </h3>
                    {selectedJob.llm_analysis.relocation_or_visa_note && (
                      <span className="text-[11px] text-sky-300 bg-sky-500/10 border border-sky-500/30 px-2 py-0.5 rounded">
                        {selectedJob.llm_analysis.relocation_or_visa_note}
                      </span>
                    )}
                  </div>

                  <p className="text-sm text-slate-200 leading-relaxed">
                    {selectedJob.llm_analysis.summary}
                  </p>

                  {selectedJob.llm_analysis.match_reasons?.length > 0 && (
                    <div>
                      <h4 className="text-xs font-semibold text-emerald-400 mb-1.5">
                        Why It Matches Your Profile
                      </h4>
                      <ul className="space-y-1">
                        {selectedJob.llm_analysis.match_reasons.map((r, i) => (
                          <li
                            key={i}
                            className="text-xs text-slate-300 flex items-start gap-2"
                          >
                            <CheckCircle2 className="h-3.5 w-3.5 text-emerald-400 shrink-0 mt-0.5" />
                            <span>{r}</span>
                          </li>
                        ))}
                      </ul>
                    </div>
                  )}

                  {selectedJob.llm_analysis.red_flags?.length > 0 && (
                    <div>
                      <h4 className="text-xs font-semibold text-amber-400 mb-1.5">
                        Watchouts / Red Flags
                      </h4>
                      <ul className="space-y-1">
                        {selectedJob.llm_analysis.red_flags.map((rf, i) => (
                          <li
                            key={i}
                            className="text-xs text-slate-300 flex items-start gap-2"
                          >
                            <AlertTriangle className="h-3.5 w-3.5 text-amber-400 shrink-0 mt-0.5" />
                            <span>{rf}</span>
                          </li>
                        ))}
                      </ul>
                    </div>
                  )}

                  {selectedJob.llm_analysis.tailoring_angle && (
                    <div className="p-3 rounded-lg bg-slate-950 border border-slate-800 text-xs text-slate-300">
                      <span className="font-semibold text-indigo-400">
                        Recommended Tailoring Angle:{" "}
                      </span>
                      {selectedJob.llm_analysis.tailoring_angle}
                    </div>
                  )}
                </div>
              )}

              {/* On-Demand Tailored Pitch Generator */}
              <div className="p-4 rounded-xl bg-indigo-950/20 border border-indigo-500/30 space-y-4">
                <div className="flex items-center justify-between">
                  <div>
                    <h3 className="text-xs font-bold uppercase tracking-wider text-indigo-300 flex items-center gap-1.5">
                      <Sparkles className="h-4 w-4 text-indigo-400" />
                      Tailored CV Pitch & Hiring Manager Outreach
                    </h3>
                    <p className="text-[11px] text-slate-400">
                      Generates a role-aligned CV summary, top 3 metrics bullets, and outreach note.
                    </p>
                  </div>
                  <button
                    onClick={handleGeneratePitch}
                    disabled={tailoring}
                    className="inline-flex items-center gap-1.5 px-3.5 py-2 rounded-lg text-xs font-semibold bg-indigo-600 hover:bg-indigo-500 disabled:opacity-60 text-white transition"
                  >
                    {tailoring ? (
                      <>
                        <Loader2 className="h-3.5 w-3.5 animate-spin" />
                        Generating...
                      </>
                    ) : (
                      <>
                        <Sparkles className="h-3.5 w-3.5" />
                        {selectedJob.tailored_pitch
                          ? "Regenerate Tailored Pitch"
                          : "Generate Tailored Pitch"}
                      </>
                    )}
                  </button>
                </div>

                {selectedJob.tailored_pitch && (
                  <div className="space-y-3 pt-2 border-t border-indigo-500/20">
                    <div className="p-3 rounded-lg bg-slate-950 border border-slate-800">
                      <div className="flex items-center justify-between mb-1">
                        <span className="text-xs font-semibold text-indigo-300">
                          1. Tailored 3–4 Line CV Summary
                        </span>
                        <button
                          onClick={() =>
                            copyText("summary", selectedJob.tailored_pitch!.cv_summary)
                          }
                          className="text-[11px] text-slate-400 hover:text-white inline-flex items-center gap-1"
                        >
                          <Copy className="h-3 w-3" />
                          {copiedKey === "summary" ? "Copied!" : "Copy"}
                        </button>
                      </div>
                      <p className="text-xs text-slate-200 leading-relaxed">
                        {selectedJob.tailored_pitch.cv_summary}
                      </p>
                    </div>

                    <div className="p-3 rounded-lg bg-slate-950 border border-slate-800">
                      <div className="flex items-center justify-between mb-1">
                        <span className="text-xs font-semibold text-indigo-300">
                          2. Top 3 CV Bullet Points to Emphasize
                        </span>
                        <button
                          onClick={() =>
                            copyText(
                              "bullets",
                              selectedJob.tailored_pitch!.emphasized_bullets
                                .map((b) => `• ${b}`)
                                .join("\n")
                            )
                          }
                          className="text-[11px] text-slate-400 hover:text-white inline-flex items-center gap-1"
                        >
                          <Copy className="h-3 w-3" />
                          {copiedKey === "bullets" ? "Copied!" : "Copy"}
                        </button>
                      </div>
                      <ul className="list-disc list-inside space-y-1 text-xs text-slate-200">
                        {selectedJob.tailored_pitch.emphasized_bullets.map((b, i) => (
                          <li key={i}>{b}</li>
                        ))}
                      </ul>
                    </div>

                    <div className="p-3 rounded-lg bg-slate-950 border border-slate-800">
                      <div className="flex items-center justify-between mb-1">
                        <span className="text-xs font-semibold text-indigo-300">
                          3. LinkedIn / Email Hiring Manager Outreach
                        </span>
                        <button
                          onClick={() =>
                            copyText(
                              "outreach",
                              selectedJob.tailored_pitch!.outreach_message
                            )
                          }
                          className="text-[11px] text-slate-400 hover:text-white inline-flex items-center gap-1"
                        >
                          <Copy className="h-3 w-3" />
                          {copiedKey === "outreach" ? "Copied!" : "Copy"}
                        </button>
                      </div>
                      <pre className="text-xs text-slate-200 whitespace-pre-wrap font-sans leading-relaxed">
                        {selectedJob.tailored_pitch.outreach_message}
                      </pre>
                    </div>
                  </div>
                )}
              </div>

              {/* Triage Notes */}
              <div className="p-4 rounded-xl bg-slate-900 border border-slate-800 space-y-2.5">
                <div className="flex items-center justify-between">
                  <label className="text-xs font-bold uppercase tracking-wider text-slate-300">
                    Recruiter Contacts, Salary & Interview Notes (Markdown)
                  </label>
                  <button
                    onClick={handleSaveNotes}
                    disabled={savingNotes}
                    className="px-3 py-1 rounded-md text-xs font-medium bg-emerald-600 hover:bg-emerald-500 text-white transition"
                  >
                    {savingNotes ? "Saving..." : "Save Notes"}
                  </button>
                </div>
                <textarea
                  rows={4}
                  value={notesDraft}
                  onChange={(e) => setNotesDraft(e.target.value)}
                  placeholder="Add recruiter contact, compensation band, or interview takeaways..."
                  className="w-full p-3 rounded-lg bg-slate-950 border border-slate-800 text-xs text-slate-100 placeholder-slate-500 focus:outline-none focus:border-emerald-500"
                />
              </div>

              {/* Cleaned Job Description */}
              <div className="p-4 rounded-xl bg-slate-900/60 border border-slate-800 space-y-2">
                <h3 className="text-xs font-bold uppercase tracking-wider text-slate-400 flex items-center gap-1.5">
                  <FileText className="h-4 w-4" />
                  Full Cleaned Job Description
                </h3>
                <div className="text-xs text-slate-300 whitespace-pre-wrap leading-relaxed max-h-96 overflow-y-auto pr-2">
                  {selectedJob.description || "No description provided."}
                </div>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Manual Job Entry Modal */}
      {showManualModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 backdrop-blur-sm p-4">
          <div className="w-full max-w-lg rounded-2xl bg-slate-900 border border-slate-800 p-6 space-y-4 shadow-2xl">
            <div className="flex items-center justify-between">
              <h2 className="text-base font-bold text-white">
                Add & Score Manual Job Posting
              </h2>
              <button
                onClick={() => setShowManualModal(false)}
                className="text-slate-400 hover:text-white"
              >
                <X className="h-5 w-5" />
              </button>
            </div>
            <p className="text-xs text-slate-400">
              Paste a job URL or raw JD text shared via WhatsApp/LinkedIn/Recruiters. It will be scored against your CV immediately.
            </p>
            <form onSubmit={handleManualSubmit} className="space-y-3">
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="text-xs text-slate-300 block mb-1">Company *</label>
                  <input
                    type="text"
                    required
                    value={manualCompany}
                    onChange={(e) => setManualCompany(e.target.value)}
                    placeholder="e.g. GoTo / Grab / Traveloka"
                    className="w-full px-3 py-2 rounded-lg bg-slate-950 border border-slate-800 text-xs text-white"
                  />
                </div>
                <div>
                  <label className="text-xs text-slate-300 block mb-1">Role Title *</label>
                  <input
                    type="text"
                    required
                    value={manualTitle}
                    onChange={(e) => setManualTitle(e.target.value)}
                    placeholder="e.g. Head of Quality Engineering"
                    className="w-full px-3 py-2 rounded-lg bg-slate-950 border border-slate-800 text-xs text-white"
                  />
                </div>
              </div>
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="text-xs text-slate-300 block mb-1">Location</label>
                  <input
                    type="text"
                    value={manualLocation}
                    onChange={(e) => setManualLocation(e.target.value)}
                    placeholder="Jakarta, Indonesia (Hybrid)"
                    className="w-full px-3 py-2 rounded-lg bg-slate-950 border border-slate-800 text-xs text-white"
                  />
                </div>
                <div>
                  <label className="text-xs text-slate-300 block mb-1">Job Posting URL</label>
                  <input
                    type="url"
                    value={manualUrl}
                    onChange={(e) => setManualUrl(e.target.value)}
                    placeholder="https://..."
                    className="w-full px-3 py-2 rounded-lg bg-slate-950 border border-slate-800 text-xs text-white"
                  />
                </div>
              </div>
              <div>
                <label className="text-xs text-slate-300 block mb-1">
                  Job Description (or leave blank to auto-fetch from URL)
                </label>
                <textarea
                  rows={6}
                  value={manualDesc}
                  onChange={(e) => setManualDesc(e.target.value)}
                  placeholder="Paste the job requirements and responsibilities..."
                  className="w-full p-3 rounded-lg bg-slate-950 border border-slate-800 text-xs text-white"
                />
              </div>
              <div className="flex justify-end gap-2 pt-2">
                <button
                  type="button"
                  onClick={() => setShowManualModal(false)}
                  className="px-4 py-2 rounded-lg text-xs bg-slate-800 text-slate-300"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={submittingManual}
                  className="px-4 py-2 rounded-lg text-xs font-semibold bg-emerald-600 hover:bg-emerald-500 text-white"
                >
                  {submittingManual ? "Scoring & Adding..." : "Score & Add to Board"}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* Scrape Runs History Modal */}
      {showRunsModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 backdrop-blur-sm p-4">
          <div className="w-full max-w-3xl rounded-2xl bg-slate-900 border border-slate-800 p-6 space-y-4 shadow-2xl max-h-[85vh] flex flex-col">
            <div className="flex items-center justify-between">
              <h2 className="text-base font-bold text-white">
                Connector Ingestion Runs
              </h2>
              <button
                onClick={() => setShowRunsModal(false)}
                className="text-slate-400 hover:text-white"
              >
                <X className="h-5 w-5" />
              </button>
            </div>
            <div className="overflow-y-auto flex-1">
              <table className="w-full text-left text-xs">
                <thead className="text-slate-400 border-b border-slate-800">
                  <tr>
                    <th className="py-2">Connector</th>
                    <th className="py-2">Status</th>
                    <th className="py-2">Fetched</th>
                    <th className="py-2">New Scored</th>
                    <th className="py-2">Pre-Filtered</th>
                    <th className="py-2">Started</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-800/70">
                  {runs.map((r) => (
                    <tr key={r.id}>
                      <td className="py-2.5 font-medium text-slate-200">
                        {r.connector_name}
                      </td>
                      <td className="py-2.5">
                        <span
                          className={`px-2 py-0.5 rounded text-[11px] ${
                            r.status === "success"
                              ? "bg-emerald-500/15 text-emerald-300"
                              : r.status === "running"
                              ? "bg-sky-500/15 text-sky-300"
                              : r.status === "skipped"
                              ? "bg-slate-800 text-slate-400"
                              : "bg-rose-500/15 text-rose-300"
                          }`}
                        >
                          {r.status}
                        </span>
                      </td>
                      <td className="py-2.5 text-slate-300">{r.jobs_fetched}</td>
                      <td className="py-2.5 text-emerald-400 font-semibold">
                        {r.jobs_scored}
                      </td>
                      <td className="py-2.5 text-slate-400">{r.jobs_filtered}</td>
                      <td className="py-2.5 text-slate-400">
                        {formatAge(r.started_at)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        </div>
      )}

      {/* Daily Digest Modal */}
      {showDigestModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 backdrop-blur-sm p-4">
          <div className="w-full max-w-2xl rounded-2xl bg-slate-900 border border-slate-800 p-6 space-y-4 shadow-2xl">
            <div className="flex items-center justify-between">
              <h2 className="text-base font-bold text-white">
                Daily High-Signal Digest (08:30 WIB)
              </h2>
              <button
                onClick={() => setShowDigestModal(false)}
                className="text-slate-400 hover:text-white"
              >
                <X className="h-5 w-5" />
              </button>
            </div>
            <pre className="p-4 rounded-xl bg-slate-950 border border-slate-800 text-xs text-slate-200 whitespace-pre-wrap font-mono max-h-96 overflow-y-auto">
              {digestPreview || "Loading digest preview..."}
            </pre>
            {digestNote && (
              <p className="text-xs text-amber-300 bg-amber-500/10 border border-amber-500/30 p-2.5 rounded-lg">
                {digestNote}
              </p>
            )}
            <div className="flex justify-end gap-2">
              <button
                onClick={() => copyText("digest", digestPreview)}
                className="px-3.5 py-2 rounded-lg text-xs bg-slate-800 hover:bg-slate-700 text-slate-200"
              >
                {copiedKey === "digest" ? "Copied Markdown!" : "Copy Digest Markdown"}
              </button>
              <button
                onClick={handleSendDigest}
                disabled={digestSending}
                className="px-4 py-2 rounded-lg text-xs font-semibold bg-indigo-600 hover:bg-indigo-500 text-white"
              >
                {digestSending ? "Sending..." : "Send via Telegram Now"}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* In-App CV & Config Editor Modal */}
      {showConfigModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 backdrop-blur-sm p-4">
          <div className="w-full max-w-4xl rounded-2xl bg-slate-900 border border-slate-800 p-6 space-y-4 shadow-2xl max-h-[90vh] flex flex-col">
            <div className="flex items-center justify-between">
              <div>
                <h2 className="text-base font-bold text-white">
                  Candidate CV, Preferences & Company Watchlist
                </h2>
                <p className="text-xs text-slate-400">
                  Changes are persisted to MongoDB and synced directly to config/cv.md, config/preferences.yaml, and config/companies.yaml.
                </p>
              </div>
              <button
                onClick={() => setShowConfigModal(false)}
                className="text-slate-400 hover:text-white"
              >
                <X className="h-5 w-5" />
              </button>
            </div>

            <div className="flex gap-2 border-b border-slate-800 pb-2">
              <button
                onClick={() => setActiveConfigTab("cv")}
                className={`px-3 py-1.5 rounded-lg text-xs font-medium ${
                  activeConfigTab === "cv"
                    ? "bg-emerald-500/20 text-emerald-300 border border-emerald-500/40"
                    : "text-slate-400 hover:text-white"
                }`}
              >
                config/cv.md
              </button>
              <button
                onClick={() => setActiveConfigTab("preferences")}
                className={`px-3 py-1.5 rounded-lg text-xs font-medium ${
                  activeConfigTab === "preferences"
                    ? "bg-emerald-500/20 text-emerald-300 border border-emerald-500/40"
                    : "text-slate-400 hover:text-white"
                }`}
              >
                config/preferences.yaml
              </button>
              <button
                onClick={() => setActiveConfigTab("companies")}
                className={`px-3 py-1.5 rounded-lg text-xs font-medium ${
                  activeConfigTab === "companies"
                    ? "bg-emerald-500/20 text-emerald-300 border border-emerald-500/40"
                    : "text-slate-400 hover:text-white"
                }`}
              >
                config/companies.yaml
              </button>
            </div>

            <div className="flex-1 overflow-hidden">
              {activeConfigTab === "cv" && (
                <textarea
                  value={cvDraft}
                  onChange={(e) => setCvDraft(e.target.value)}
                  className="w-full h-96 p-4 rounded-xl bg-slate-950 border border-slate-800 text-xs font-mono text-slate-100 focus:outline-none focus:border-emerald-500"
                />
              )}
              {activeConfigTab === "preferences" && (
                <textarea
                  value={prefDraft}
                  onChange={(e) => setPrefDraft(e.target.value)}
                  className="w-full h-96 p-4 rounded-xl bg-slate-950 border border-slate-800 text-xs font-mono text-slate-100 focus:outline-none focus:border-emerald-500"
                />
              )}
              {activeConfigTab === "companies" && (
                <textarea
                  value={compDraft}
                  onChange={(e) => setCompDraft(e.target.value)}
                  className="w-full h-96 p-4 rounded-xl bg-slate-950 border border-slate-800 text-xs font-mono text-slate-100 focus:outline-none focus:border-emerald-500"
                />
              )}
            </div>

            {configStatus && (
              <p className="text-xs text-emerald-300 bg-emerald-500/10 border border-emerald-500/30 p-2.5 rounded-lg">
                {configStatus}
              </p>
            )}

            <div className="flex justify-end gap-2">
              <button
                onClick={() => setShowConfigModal(false)}
                className="px-4 py-2 rounded-lg text-xs bg-slate-800 text-slate-300"
              >
                Close
              </button>
              <button
                onClick={handleSaveConfig}
                disabled={savingConfig}
                className="px-4 py-2 rounded-lg text-xs font-semibold bg-emerald-600 hover:bg-emerald-500 text-white"
              >
                {savingConfig ? "Saving..." : "Save Configuration"}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
