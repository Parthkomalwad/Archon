import { useState, useEffect, useCallback } from "react";
import { motion } from "framer-motion";
import {
  getStatus,
  getBackups,
  triggerBackup,
  reloadConfig,
  getJob,
  type StatusResponse,
  type BackupsResponse,
  type Job,
} from "../api/client";

// ── Countdown timer ───────────────────────────────────────────────────────────
function useCountdown(targetISO: string | null) {
  const [display, setDisplay] = useState("—");
  useEffect(() => {
    if (!targetISO) { setDisplay("—"); return; }
    const tick = () => {
      const diff = new Date(targetISO).getTime() - Date.now();
      if (diff <= 0) { setDisplay("now"); return; }
      const h = Math.floor(diff / 3600000);
      const m = Math.floor((diff % 3600000) / 60000);
      const s = Math.floor((diff % 60000) / 1000);
      if (h > 0) setDisplay(`${h}h ${m}m`);
      else if (m > 0) setDisplay(`${m}m ${s}s`);
      else setDisplay(`${s}s`);
    };
    tick();
    const id = setInterval(tick, 1000);
    return () => clearInterval(id);
  }, [targetISO]);
  return display;
}

// ── Time ago ──────────────────────────────────────────────────────────────────
function timeAgo(iso: string | null): string {
  if (!iso) return "never";
  const diff = Date.now() - new Date(iso).getTime();
  const m = Math.floor(diff / 60000);
  const h = Math.floor(m / 60);
  const d = Math.floor(h / 24);
  if (d > 0) return `${d}d ago`;
  if (h > 0) return `${h}h ago`;
  if (m > 0) return `${m}m ago`;
  return "just now";
}

// ── Stat card ─────────────────────────────────────────────────────────────────
function StatCard({
  label,
  value,
  sub,
  index,
}: {
  label: string;
  value: string | number;
  sub?: string;
  index: number;
}) {
  return (
    <motion.div
      initial={{ opacity: 0, y: 20 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ delay: index * 0.08, duration: 0.4 }}
      className="rounded-xl p-5 flex flex-col gap-1 relative overflow-hidden"
      style={{ background: "#1E293B", border: "1px solid #2D3F57" }}
    >
      <div
        className="absolute top-0 left-0 right-0 h-px"
        style={{
          background:
            "linear-gradient(90deg, transparent, #6366F130, transparent)",
        }}
      />
      <span
        className="text-xs font-semibold uppercase tracking-widest"
        style={{ color: "#64748B" }}
      >
        {label}
      </span>
      <span
        className="text-3xl font-bold tracking-tight"
        style={{ color: "#F1F5F9" }}
      >
        {value}
      </span>
      {sub && (
        <span className="text-xs" style={{ color: "#64748B" }}>
          {sub}
        </span>
      )}
    </motion.div>
  );
}

// ── Backup button with job polling ────────────────────────────────────────────
type ButtonState = "idle" | "queued" | "running" | "done" | "failed";

function BackupButton({
  dbName,
  onDone,
}: {
  dbName: string;
  onDone?: () => void;
}) {
  const [state, setState] = useState<ButtonState>("idle");
  const [errorMsg, setErrorMsg] = useState("");

  const handleClick = useCallback(async () => {
    if (state !== "idle") return;
    setState("queued");
    try {
      const res = await triggerBackup(dbName);
      const jobId = res.jobs[0]?.job_id;
      if (!jobId) throw new Error("No job ID returned");
      const poll = setInterval(async () => {
        try {
          const job: Job = await getJob(jobId);
          if (job.status === "running") setState("running");
          if (job.status === "completed") {
            clearInterval(poll);
            setState("done");
            onDone?.();
            setTimeout(() => setState("idle"), 3000);
          }
          if (job.status === "failed") {
            clearInterval(poll);
            setErrorMsg(job.error_message ?? "Unknown error");
            setState("failed");
            setTimeout(() => setState("idle"), 5000);
          }
        } catch {
          clearInterval(poll);
          setState("failed");
          setErrorMsg("Failed to poll job status");
          setTimeout(() => setState("idle"), 5000);
        }
      }, 2000);
    } catch (e: unknown) {
      setState("failed");
      setErrorMsg(e instanceof Error ? e.message : String(e));
      setTimeout(() => setState("idle"), 5000);
    }
  }, [dbName, state, onDone]);

  const label =
    state === "idle"
      ? "Backup Now"
      : state === "queued"
        ? "Queued…"
        : state === "running"
          ? "Running…"
          : state === "done"
            ? "Done!"
            : "Failed";

  const bgColor =
    state === "idle"
      ? "#6366F1"
      : state === "done"
        ? "#10B981"
        : state === "failed"
          ? "#EF4444"
          : "#F59E0B";

  return (
    <div className="relative">
      <motion.button
        whileHover={state === "idle" ? { scale: 1.02 } : {}}
        whileTap={state === "idle" ? { scale: 0.98 } : {}}
        onClick={handleClick}
        disabled={state !== "idle"}
        className="px-4 py-2 rounded-lg text-sm font-semibold transition-all duration-200 disabled:opacity-80 shrink-0"
        style={{
          background: bgColor,
          color: "white",
          boxShadow: state === "idle" ? "0 0 20px #6366F125" : "none",
        }}
      >
        {label}
      </motion.button>
      {state === "failed" && errorMsg && (
        <div
          className="absolute bottom-full right-0 mb-2 z-10 text-white text-xs rounded-lg px-3 py-2 w-52 shadow-xl"
          style={{ background: "#EF4444" }}
        >
          {errorMsg}
        </div>
      )}
    </div>
  );
}

// ── DB panel ──────────────────────────────────────────────────────────────────
function DbPanel({
  db,
  backupCount,
  totalBytes,
  onRefresh,
  index,
}: {
  db: {
    database: string;
    last_run_time: string | null;
    next_scheduled_run: string | null;
    last_status: string | null;
    currently_running: boolean;
  };
  backupCount: number;
  totalBytes: number;
  onRefresh: () => void;
  index: number;
}) {
  const countdown = useCountdown(db.next_scheduled_run);
  const isRunning = db.currently_running;
  const status = isRunning
    ? "running"
    : db.last_status === "completed"
      ? "healthy"
      : db.last_status === "failed"
        ? "failed"
        : "idle";
  const statusColor = {
    running: "#3B82F6",
    healthy: "#10B981",
    failed: "#EF4444",
    idle: "#64748B",
  }[status];
  const statusLabel = {
    running: "Running",
    healthy: "Healthy",
    failed: "Failed",
    idle: "Idle",
  }[status];

  const barPct = Math.min(100, (totalBytes / 102400) * 100);

  return (
    <motion.div
      initial={{ opacity: 0, x: -20 }}
      animate={{ opacity: 1, x: 0 }}
      transition={{ delay: 0.3 + index * 0.1 }}
      whileHover={{ borderColor: "#6366F140" }}
      className="rounded-xl p-6 relative overflow-hidden transition-colors duration-200"
      style={{ background: "#1E293B", border: "1px solid #2D3F57" }}
    >
      {/* Left accent bar */}
      <div
        className="absolute left-0 top-4 bottom-4 w-0.5 rounded-full"
        style={{ background: statusColor }}
      />

      <div className="flex items-start justify-between gap-4 mb-5">
        <div>
          <div className="flex items-center gap-3 mb-1">
            <span
              className="font-bold text-lg"
              style={{ color: "#F1F5F9" }}
            >
              {db.database}
            </span>
            <span
              className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-semibold"
              style={{
                color: statusColor,
                background: `${statusColor}15`,
                border: `1px solid ${statusColor}30`,
              }}
            >
              <span
                className={`w-1.5 h-1.5 rounded-full ${isRunning ? "animate-pulse" : ""}`}
                style={{ background: statusColor }}
              />
              {statusLabel}
            </span>
          </div>
          <span className="text-xs font-mono" style={{ color: "#64748B" }}>
            database
          </span>
        </div>
        <BackupButton dbName={db.database} onDone={onRefresh} />
      </div>

      {/* Stats row */}
      <div className="grid grid-cols-3 gap-4 mb-5">
        {[
          { label: "Last backup", value: timeAgo(db.last_run_time) },
          { label: "Next run", value: countdown },
          { label: "Stored files", value: String(backupCount) },
        ].map((s) => (
          <div
            key={s.label}
            className="rounded-lg p-3"
            style={{ background: "#0C1120", border: "1px solid #1F2D40" }}
          >
            <div className="text-xs mb-1" style={{ color: "#64748B" }}>
              {s.label}
            </div>
            <div
              className="font-semibold text-sm"
              style={{ color: "#F1F5F9" }}
            >
              {s.value}
            </div>
          </div>
        ))}
      </div>

      {/* Storage bar */}
      <div>
        <div className="flex items-center justify-between mb-1.5">
          <span className="text-xs" style={{ color: "#64748B" }}>
            Storage used
          </span>
          <span
            className="text-xs font-mono"
            style={{ color: "#64748B" }}
          >
            {totalBytes < 1024
              ? `${totalBytes} B`
              : totalBytes < 1048576
                ? `${(totalBytes / 1024).toFixed(1)} KB`
                : `${(totalBytes / 1048576).toFixed(1)} MB`}
          </span>
        </div>
        <div
          className="h-1.5 rounded-full overflow-hidden"
          style={{ background: "#2D3F57" }}
        >
          <motion.div
            initial={{ width: 0 }}
            animate={{ width: `${barPct}%` }}
            transition={{ duration: 1, delay: 0.5, ease: "easeOut" }}
            className="h-full rounded-full"
            style={{
              background: "linear-gradient(90deg, #6366F1, #818CF8)",
            }}
          />
        </div>
      </div>
    </motion.div>
  );
}

// ── Activity item ─────────────────────────────────────────────────────────────
function ActivityItem({
  db,
  status,
  time,
  index,
}: {
  db: string;
  status: string;
  time: string;
  index: number;
}) {
  const color =
    status === "completed"
      ? "#10B981"
      : status === "failed"
        ? "#EF4444"
        : "#3B82F6";
  return (
    <motion.div
      initial={{ opacity: 0, x: -10 }}
      animate={{ opacity: 1, x: 0 }}
      transition={{ delay: 0.5 + index * 0.06 }}
      className="flex items-center gap-4 py-3"
      style={{ borderBottom: "1px solid #1F2D40" }}
    >
      <div
        className="w-2 h-2 rounded-full shrink-0"
        style={{ background: color, boxShadow: `0 0 6px ${color}` }}
      />
      <span
        className="text-sm font-medium flex-1"
        style={{ color: "#F1F5F9" }}
      >
        {db}
      </span>
      <span
        className="text-xs px-2 py-0.5 rounded-full font-semibold"
        style={{ color, background: `${color}15` }}
      >
        {status}
      </span>
      <span className="text-xs font-mono" style={{ color: "#64748B" }}>
        {time}
      </span>
    </motion.div>
  );
}

// ── Main ──────────────────────────────────────────────────────────────────────
export default function Dashboard() {
  const [status, setStatus] = useState<StatusResponse | null>(null);
  const [backups, setBackups] = useState<BackupsResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [reloading, setReloading] = useState(false);
  const [backingUpAll, setBackingUpAll] = useState(false);
  const [toast, setToast] = useState<{
    msg: string;
    type: "success" | "error";
  } | null>(null);

  function showToast(msg: string, type: "success" | "error") {
    setToast({ msg, type });
    setTimeout(() => setToast(null), 3000);
  }

  const load = useCallback(async () => {
    try {
      const [s, b] = await Promise.all([getStatus(), getBackups()]);
      setStatus(s);
      setBackups(b);
    } catch {
      // ignore  toast shown on specific actions
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
    const id = setInterval(load, 10000);
    return () => clearInterval(id);
  }, [load]);

  async function handleBackupAll() {
    setBackingUpAll(true);
    try {
      await triggerBackup();
      showToast("All backups queued", "success");
      setTimeout(load, 2000);
    } catch (e: unknown) {
      showToast(e instanceof Error ? e.message : "Backup failed", "error");
    } finally {
      setBackingUpAll(false);
    }
  }

  async function handleReload() {
    setReloading(true);
    try {
      const res = await reloadConfig();
      showToast(
        `Config reloaded  ${res.databases_registered} database(s) registered`,
        "success"
      );
      await load();
    } catch (e: unknown) {
      showToast(
        e instanceof Error ? e.message : "Reload failed",
        "error"
      );
    } finally {
      setReloading(false);
    }
  }

  const totalBackups = backups?.backups.length ?? 0;
  const latestBackup = backups?.backups
    .slice()
    .sort((a, b) => b.timestamp.localeCompare(a.timestamp))[0];

  const latestBackupTime = latestBackup
    ? timeAgo(
      latestBackup.timestamp.replace(
        /T(\d{2})-(\d{2})-(\d{2})/,
        "T$1:$2:$3"
      )
    )
    : "—";

  const activeJobs =
    status?.databases.filter((d) => d.currently_running).length ?? 0;

  const nextRun =
    status?.databases
      .filter((d) => d.next_scheduled_run)
      .sort(
        (a, b) =>
          new Date(a.next_scheduled_run!).getTime() -
          new Date(b.next_scheduled_run!).getTime()
      )[0]?.next_scheduled_run ?? null;

  const countdown = useCountdown(nextRun);

  if (loading) {
    return (
      <div className="flex items-center justify-center min-h-96">
        <div className="w-8 h-8 rounded-full border-2 border-[#2D3F57] border-t-[#6366F1] animate-spin" />
      </div>
    );
  }

  return (
    <div className="space-y-8">
      {/* Toast */}
      {toast && (
        <motion.div
          initial={{ opacity: 0, y: -10 }}
          animate={{ opacity: 1, y: 0 }}
          exit={{ opacity: 0 }}
          className="fixed top-20 right-6 z-50 px-4 py-3 rounded-xl text-sm font-medium shadow-xl"
          style={{
            background:
              toast.type === "success" ? "#10B98120" : "#EF444420",
            border: `1px solid ${toast.type === "success" ? "#10B98140" : "#EF444440"}`,
            color: toast.type === "success" ? "#10B981" : "#EF4444",
          }}
        >
          {toast.msg}
        </motion.div>
      )}

      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <motion.h1
            initial={{ opacity: 0, y: -10 }}
            animate={{ opacity: 1, y: 0 }}
            className="text-2xl font-bold"
            style={{ color: "#F1F5F9" }}
          >
            Dashboard
          </motion.h1>
          <motion.p
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            transition={{ delay: 0.1 }}
            className="text-sm mt-0.5"
            style={{ color: "#64748B" }}
          >
            Monitor and trigger database backups
          </motion.p>
        </div>
        <motion.div
          initial={{ opacity: 0, x: 10 }}
          animate={{ opacity: 1, x: 0 }}
          className="flex items-center gap-3"
        >
          <button
            onClick={handleReload}
            disabled={reloading}
            className="flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-medium transition-all disabled:opacity-60"
            style={{
              border: "1px solid #2D3F57",
              color: "#64748B",
              background: "#1E293B",
            }}
            onMouseEnter={(e) => {
              (e.currentTarget as HTMLElement).style.borderColor =
                "#6366F130";
              (e.currentTarget as HTMLElement).style.color = "#F1F5F9";
            }}
            onMouseLeave={(e) => {
              (e.currentTarget as HTMLElement).style.borderColor =
                "#2D3F57";
              (e.currentTarget as HTMLElement).style.color = "#64748B";
            }}
          >
            <svg
              className={`w-4 h-4 ${reloading ? "animate-spin" : ""}`}
              fill="none"
              viewBox="0 0 24 24"
              stroke="currentColor"
              strokeWidth={2}
            >
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15"
              />
            </svg>
            Reload Config
          </button>
          <motion.button
            whileHover={{ scale: 1.02 }}
            whileTap={{ scale: 0.98 }}
            onClick={handleBackupAll}
            disabled={backingUpAll}
            className="flex items-center gap-2 px-5 py-2 rounded-lg text-sm font-semibold transition-all disabled:opacity-50"
            style={{
              background: "#6366F1",
              color: "white",
              boxShadow: "0 0 20px #6366F130",
            }}
          >
            <svg
              className="w-4 h-4"
              fill="none"
              viewBox="0 0 24 24"
              stroke="currentColor"
              strokeWidth={2.5}
            >
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                d="M13 10V3L4 14h7v7l9-11h-7z"
              />
            </svg>
            {backingUpAll ? "Queuing…" : "Backup All"}
          </motion.button>
        </motion.div>
      </div>

      {/* Stat cards */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <StatCard
          index={0}
          label="Databases"
          value={status?.databases.length ?? 0}
          sub={`${status?.databases.filter((d) => !d.currently_running).length ?? 0} healthy`}
        />
        <StatCard
          index={1}
          label="Total Backups"
          value={totalBackups}
          sub="stored files"
        />
        <StatCard
          index={2}
          label="Latest Backup"
          value={latestBackupTime}
          sub="most recent"
        />
        <StatCard
          index={3}
          label="Next Run"
          value={countdown}
          sub={
            activeJobs > 0 ? `${activeJobs} running` : "scheduled"
          }
        />
      </div>

      {/* DB panels */}
      <div>
        <div className="flex items-center gap-3 mb-4">
          <h2
            className="text-xs font-semibold uppercase tracking-widest"
            style={{ color: "#64748B" }}
          >
            Databases
          </h2>
          <span
            className="w-5 h-5 rounded-full flex items-center justify-center text-xs font-bold"
            style={{ background: "#253347", color: "#6366F1" }}
          >
            {status?.databases.length ?? 0}
          </span>
        </div>
        <div className="space-y-4">
          {status?.databases.map((db, i) => {
            const dbBackups =
              backups?.backups.filter(
                (b) => b.database === db.database
              ) ?? [];
            const totalBytes = dbBackups.reduce(
              (acc, b) => acc + b.size_bytes,
              0
            );
            return (
              <DbPanel
                key={db.database}
                db={db}
                backupCount={dbBackups.length}
                totalBytes={totalBytes}
                onRefresh={load}
                index={i}
              />
            );
          })}
        </div>
      </div>

      {/* Recent activity  uses backup listing */}
      {backups && backups.backups.length > 0 && (
        <div>
          <h2
            className="text-xs font-semibold uppercase tracking-widest mb-4"
            style={{ color: "#64748B" }}
          >
            Recent Activity
          </h2>
          <div
            className="rounded-xl overflow-hidden"
            style={{ background: "#1E293B", border: "1px solid #2D3F57" }}
          >
            <div className="px-6">
              {backups.backups
                .slice()
                .sort((a, b) =>
                  b.timestamp.localeCompare(a.timestamp)
                )
                .slice(0, 6)
                .map((b, i) => (
                  <ActivityItem
                    key={b.filename}
                    db={b.database}
                    status="completed"
                    time={timeAgo(
                      b.timestamp.replace(
                        /T(\d{2})-(\d{2})-(\d{2})/,
                        "T$1:$2:$3"
                      )
                    )}
                    index={i}
                  />
                ))}
            </div>
          </div>
        </div>
      )}

      {/* Empty state */}
      {status && status.databases.length === 0 && (
        <motion.div
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          className="flex flex-col items-center justify-center py-24 rounded-xl"
          style={{ background: "#1E293B", border: "1px solid #2D3F57" }}
        >
          <div className="mb-4 text-[#2D3F57]">
            <svg className="w-10 h-10" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5"><path strokeLinecap="round" strokeLinejoin="round" d="M20.25 6.375c0 2.278-3.694 4.125-8.25 4.125S3.75 8.653 3.75 6.375m16.5 0c0-2.278-3.694-4.125-8.25-4.125S3.75 4.097 3.75 6.375m16.5 0v11.25c0 2.278-3.694 4.125-8.25 4.125s-8.25-1.847-8.25-4.125V6.375m16.5 2.625c0 2.278-3.694 4.125-8.25 4.125s-8.25-1.847-8.25-4.125m16.5 5.625c0 2.278-3.694 4.125-8.25 4.125s-8.25-1.847-8.25-4.125" /></svg>
          </div>
          <p className="font-semibold mb-1" style={{ color: "#F1F5F9" }}>
            No databases configured
          </p>
          <p className="text-sm" style={{ color: "#64748B" }}>
            Add databases to config.yaml and reload the config.
          </p>
        </motion.div>
      )}
    </div>
  );
}
