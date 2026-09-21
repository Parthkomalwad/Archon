import { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { motion, AnimatePresence } from "framer-motion";
import { useNavigate } from "react-router-dom";
import { getBackups, deleteBackup, type Backup } from "../api/client";
import BackupTag from "../components/BackupTag";
import GranularRestoreWizard from "./GranularRestore";

// ── Helpers ───────────────────────────────────────────────────────────────────

function fmtBytes(b: number): string {
  if (b < 1024) return `${b} B`;
  if (b < 1048576) return `${(b / 1024).toFixed(1)} KB`;
  if (b < 1073741824) return `${(b / 1048576).toFixed(1)} MB`;
  return `${(b / 1073741824).toFixed(2)} GB`;
}

function timeAgo(ts: string): string {
  const iso = ts.replace(/T(\d{2})-(\d{2})-(\d{2})/, "T$1:$2:$3");
  const diff = Date.now() - new Date(iso).getTime();
  const m = Math.floor(diff / 60000);
  const h = Math.floor(m / 60);
  const d = Math.floor(h / 24);
  if (d > 0) return `${d}d ago`;
  if (h > 0) return `${h}h ago`;
  if (m > 0) return `${m}m ago`;
  return "just now";
}

// ── Badges ────────────────────────────────────────────────────────────────────

const ROTATION_COLORS: Record<
  string,
  { text: string; bg: string; border: string }
> = {
  hourly: {
    text: "#60A5FA",
    bg: "#60A5FA15",
    border: "#60A5FA30",
  },
  daily: {
    text: "#6366F1",
    bg: "#6366F115",
    border: "#6366F130",
  },
  weekly: {
    text: "#A78BFA",
    bg: "#A78BFA15",
    border: "#A78BFA30",
  },
  monthly: {
    text: "#C084FC",
    bg: "#C084FC15",
    border: "#C084FC30",
  },
};

function RotBadge({ type }: { type: string }) {
  const c = ROTATION_COLORS[type] ?? {
    text: "#64748B",
    bg: "#64748B15",
    border: "#64748B30",
  };
  return (
    <span
      className="px-2 py-0.5 rounded-full text-xs font-semibold border capitalize"
      style={{ color: c.text, background: c.bg, borderColor: c.border }}
    >
      {type}
    </span>
  );
}

function IntegrityBadge({ backup }: { backup: Backup }) {
  if (!backup.file_exists) {
    return (
      <span
        className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-semibold border"
        style={{
          color: "#EF4444",
          background: "#EF444415",
          borderColor: "#EF444430",
        }}
      >
        <svg className="w-3.5 h-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5"><path strokeLinecap="round" strokeLinejoin="round" d="M12 9v3.75m-9.303 3.376c-.866 1.5.217 3.374 1.948 3.374h14.71c1.73 0 2.813-1.874 1.948-3.374L13.949 3.378c-.866-1.5-3.032-1.5-3.898 0L2.697 16.126zM12 15.75h.007v.008H12v-.008z"/></svg>
        Orphaned
      </span>
    );
  }
  if (!backup.sidecar_exists) {
    return (
      <span
        className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-semibold border"
        style={{
          color: "#F59E0B",
          background: "#F59E0B15",
          borderColor: "#F59E0B30",
        }}
      >
        <svg className="w-3.5 h-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5"><path strokeLinecap="round" strokeLinejoin="round" d="M12 9v3.75m-9.303 3.376c-.866 1.5.217 3.374 1.948 3.374h14.71c1.73 0 2.813-1.874 1.948-3.374L13.949 3.378c-.866-1.5-3.032-1.5-3.898 0L2.697 16.126zM12 15.75h.007v.008H12v-.008z"/></svg>
        No checksum
      </span>
    );
  }
  return (
    <span
      className="inline-flex items-center gap-1 text-xs font-semibold"
      style={{ color: "#10B981" }}
    >
      <svg className="w-3.5 h-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5"><path strokeLinecap="round" strokeLinejoin="round" d="M4.5 12.75l6 6 9-13.5"/></svg>
      OK
    </span>
  );
}

// ── Filter select ─────────────────────────────────────────────────────────────

function FilterSelect({
  value,
  onChange,
  children,
}: {
  value: string;
  onChange: (v: string) => void;
  children: React.ReactNode;
}) {
  return (
    <select
      value={value}
      onChange={(e) => onChange(e.target.value)}
      className="px-3 py-1.5 rounded-lg text-sm transition-colors outline-none appearance-none pr-8 cursor-pointer"
      style={{
        background: "#1E293B",
        border: "1px solid #2D3F57",
        color: "#F1F5F9",
        backgroundImage: `url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='12' height='12' viewBox='0 0 24 24' fill='none' stroke='%2364748B' stroke-width='2'%3E%3Cpath d='M6 9l6 6 6-6'/%3E%3C/svg%3E")`,
        backgroundRepeat: "no-repeat",
        backgroundPosition: "right 10px center",
      }}
    >
      {children}
    </select>
  );
}

// ── Backup card (grid view) ───────────────────────────────────────────────────

function BackupCard({
  backup,
  onDelete,
  onRestore,
  onGranular,
  index,
}: {
  backup: Backup;
  onDelete: (f: string) => void;
  onRestore: (f: string) => void;
  onGranular: (b: Backup) => void;
  index: number;
}) {
  const [confirmDelete, setConfirmDelete] = useState(false);

  function handleDelete() {
    if (!confirmDelete) {
      setConfirmDelete(true);
      setTimeout(() => setConfirmDelete(false), 3000);
      return;
    }
    onDelete(backup.filename);
  }

  return (
    <motion.div
      initial={{ opacity: 0, y: 20 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0, scale: 0.95 }}
      transition={{ delay: index * 0.04 }}
      whileHover={{ borderColor: "#6366F130" }}
      className="rounded-xl p-5 flex flex-col gap-4 transition-colors duration-200 relative overflow-hidden"
      style={{ background: "#1E293B", border: "1px solid #2D3F57" }}
    >
      {/* Top gradient line */}
      <div
        className="absolute top-0 left-0 right-0 h-px"
        style={{
          background:
            "linear-gradient(90deg, transparent, #6366F120, transparent)",
        }}
      />

      {/* Header: database + size */}
      <div className="flex items-start justify-between gap-3">
        <div>
          <div
            className="font-bold text-base mb-1"
            style={{ color: "#F1F5F9" }}
          >
            {backup.database}
          </div>
          <div className="flex items-center gap-2 flex-wrap">
            <RotBadge type={backup.rotation_type} />
            {backup.encrypted && (
              <span
                className="px-2 py-0.5 rounded-full text-xs font-semibold border"
                style={{
                  color: "#6366F1",
                  background: "#6366F115",
                  borderColor: "#6366F130",
                }}
              >
                ENC
              </span>
            )}
            <IntegrityBadge backup={backup} />
          </div>
        </div>
        <div className="text-right shrink-0">
          <div
            className="font-mono text-lg font-bold"
            style={{ color: "#6366F1" }}
          >
            {fmtBytes(backup.size_bytes)}
          </div>
          <div className="text-xs" style={{ color: "#64748B" }}>
            {timeAgo(backup.timestamp)}
          </div>
        </div>
      </div>

      {/* Filename */}
      <div
        className="rounded-lg px-3 py-2"
        style={{ background: "#0C1120", border: "1px solid #1F2D40" }}
      >
        <span
          className="font-mono text-xs break-all leading-5"
          style={{ color: "#64748B" }}
        >
          {backup.filename}
        </span>
      </div>

      {/* Source tag */}
      <div className="flex items-center gap-2">
        <span className="text-xs" style={{ color: "#64748B" }}>
          Source:
        </span>
        <BackupTag triggeredBy={backup.triggered_by} />
      </div>

      {/* Actions */}
      <div className="flex items-center gap-2 pt-1">
        <motion.button
          whileHover={{ scale: 1.02 }}
          whileTap={{ scale: 0.98 }}
          onClick={() => onRestore(backup.filename)}
          className="flex-1 py-2 rounded-lg text-sm font-semibold transition-all"
          style={{
            background: "#6366F1",
            color: "white",
            boxShadow: "0 0 16px #6366F120",
          }}
        >
          Restore
        </motion.button>
        {backup.filename.includes(".sql") && (
          <button
            onClick={() => onGranular(backup)}
            className="px-3 py-2 rounded-lg text-xs font-semibold transition-all"
            style={{
              background: "#818CF820",
              color: "#818CF8",
              border: "1px solid #818CF830",
            }}
          >
            Granular
          </button>
        )}
        <button
          onClick={handleDelete}
          className="px-4 py-2 rounded-lg text-sm font-semibold transition-all duration-200"
          style={{
            background: confirmDelete ? "#EF444420" : "#253347",
            color: confirmDelete ? "#EF4444" : "#64748B",
            border: `1px solid ${confirmDelete ? "#EF444440" : "#2D3F57"}`,
          }}
        >
          {confirmDelete ? "Confirm?" : "Delete"}
        </button>
      </div>
    </motion.div>
  );
}

// ── Backup row (table view) ───────────────────────────────────────────────────

function BackupRow({
  backup,
  onDelete,
  onRestore,
  onGranular,
  index,
}: {
  backup: Backup;
  onDelete: (f: string) => void;
  onRestore: (f: string) => void;
  onGranular: (b: Backup) => void;
  index: number;
}) {
  const [confirmDelete, setConfirmDelete] = useState(false);

  function handleDelete() {
    if (!confirmDelete) {
      setConfirmDelete(true);
      setTimeout(() => setConfirmDelete(false), 3000);
      return;
    }
    onDelete(backup.filename);
  }

  return (
    <motion.tr
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      exit={{ opacity: 0 }}
      transition={{ delay: index * 0.03 }}
      className="transition-colors group"
      style={{ borderBottom: "1px solid #1F2D40" }}
      onMouseEnter={(e) =>
        (e.currentTarget.style.background = "#253347")
      }
      onMouseLeave={(e) =>
        (e.currentTarget.style.background = "transparent")
      }
    >
      <td
        className="py-3 px-4 text-sm font-semibold whitespace-nowrap"
        style={{ color: "#F1F5F9" }}
      >
        {backup.database}
      </td>
      <td className="py-3 px-4 max-w-xs">
        <span
          className="font-mono text-xs truncate block"
          style={{ color: "#64748B" }}
          title={backup.filename}
        >
          {backup.filename}
        </span>
      </td>
      <td
        className="py-3 px-4 font-mono text-xs whitespace-nowrap"
        style={{ color: "#64748B" }}
      >
        {backup.timestamp.replace("T", " ")}
      </td>
      <td
        className="py-3 px-4 font-mono text-xs font-bold whitespace-nowrap"
        style={{ color: "#6366F1" }}
      >
        {fmtBytes(backup.size_bytes)}
      </td>
      <td className="py-3 px-4">
        <RotBadge type={backup.rotation_type} />
      </td>
      <td className="py-3 px-4">
        <BackupTag triggeredBy={backup.triggered_by} />
      </td>
      <td className="py-3 px-4">
        {backup.encrypted ? (
          <span
            className="text-xs font-semibold"
            style={{ color: "#6366F1" }}
          >
            Yes
          </span>
        ) : (
          <span className="text-xs" style={{ color: "#64748B" }}>
            —
          </span>
        )}
      </td>
      <td className="py-3 px-4">
        <IntegrityBadge backup={backup} />
      </td>
      <td className="py-3 px-4 whitespace-nowrap">
        <div className="flex items-center gap-2">
          <button
            onClick={() => onRestore(backup.filename)}
            className="px-3 py-1 rounded-lg text-xs font-semibold transition-all"
            style={{
              background: "#6366F120",
              color: "#6366F1",
              border: "1px solid #6366F130",
            }}
            onMouseEnter={(e) =>
              (e.currentTarget.style.background = "#6366F130")
            }
            onMouseLeave={(e) =>
              (e.currentTarget.style.background = "#6366F120")
            }
          >
            Restore
          </button>
          {backup.filename.includes(".sql") && (
            <button
              onClick={() => onGranular(backup)}
              className="px-3 py-1 rounded-lg text-xs font-semibold transition-all"
              style={{
                background: "#818CF815",
                color: "#818CF8",
                border: "1px solid #818CF830",
              }}
            >
              Granular
            </button>
          )}
          <button
            onClick={handleDelete}
            className="px-3 py-1 rounded-lg text-xs font-semibold transition-all duration-200"
            style={{
              background: confirmDelete ? "#EF444420" : "transparent",
              color: confirmDelete ? "#EF4444" : "#64748B",
              border: `1px solid ${confirmDelete ? "#EF444440" : "transparent"}`,
            }}
          >
            {confirmDelete ? "Sure?" : "Delete"}
          </button>
        </div>
      </td>
    </motion.tr>
  );
}

// ── Main ──────────────────────────────────────────────────────────────────────

export default function Backups() {
  const queryClient = useQueryClient();
  const navigate = useNavigate();
  const [viewMode, setViewMode] = useState<"grid" | "table">("grid");
  const [filterDb, setFilterDb] = useState("");
  const [filterRotation, setFilterRotation] = useState("");
  const [filterTriggeredBy, setFilterTriggeredBy] = useState("");
  const [granularTarget, setGranularTarget] = useState<Backup | null>(null);

  const { data, isLoading, isError } = useQuery({
    queryKey: ["backups"],
    queryFn: () => getBackups(),
    refetchInterval: 60_000,
  });

  const databases = Array.from(
    new Set((data?.backups ?? []).map((b) => b.database))
  ).sort();

  const filtered = (data?.backups ?? [])
    .filter((b) => {
      if (filterDb && b.database !== filterDb) return false;
      if (filterRotation && b.rotation_type !== filterRotation) return false;
      if (filterTriggeredBy && b.triggered_by !== filterTriggeredBy)
        return false;
      return true;
    })
    .sort((a, b) => b.timestamp.localeCompare(a.timestamp));

  async function handleDelete(filename: string) {
    await deleteBackup(filename);
    queryClient.invalidateQueries({ queryKey: ["backups"] });
  }

  function handleRestore(filename: string) {
    navigate(`/restore/${encodeURIComponent(filename)}`);
  }

  const hasFilters = filterDb || filterRotation || filterTriggeredBy;

  return (
    <motion.div
      initial={{ opacity: 0, y: 16 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.3, ease: "easeOut" }}
      className="space-y-6"
    >
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1
            className="text-2xl font-bold"
            style={{ color: "#F1F5F9" }}
          >
            Backups
          </h1>
          <p className="text-sm mt-0.5" style={{ color: "#64748B" }}>
            Browse, restore and manage backup files
          </p>
        </div>
        <div className="flex items-center gap-3">
          <span
            className="px-3 py-1.5 rounded-lg text-sm font-semibold"
            style={{
              background: "#1E293B",
              border: "1px solid #2D3F57",
              color: "#6366F1",
            }}
          >
            {filtered.length} backup{filtered.length !== 1 ? "s" : ""}
          </span>
          {/* View toggle */}
          <div
            className="flex rounded-lg overflow-hidden"
            style={{ border: "1px solid #2D3F57" }}
          >
            {(["grid", "table"] as const).map((mode) => (
              <button
                key={mode}
                onClick={() => setViewMode(mode)}
                className="px-3 py-1.5 text-xs font-semibold transition-colors"
                style={{
                  background:
                    viewMode === mode ? "#6366F120" : "#1E293B",
                  color: viewMode === mode ? "#6366F1" : "#64748B",
                }}
              >
                {mode === "grid" ? "Grid" : "Table"}
              </button>
            ))}
          </div>
        </div>
      </div>

      {/* Filters */}
      <div className="flex flex-wrap items-center gap-3">
        <FilterSelect value={filterDb} onChange={setFilterDb}>
          <option value="">All databases</option>
          {databases.map((d) => (
            <option key={d} value={d}>
              {d}
            </option>
          ))}
        </FilterSelect>
        <FilterSelect
          value={filterRotation}
          onChange={setFilterRotation}
        >
          <option value="">All rotations</option>
          {["hourly", "daily", "weekly", "monthly"].map((r) => (
            <option key={r} value={r} className="capitalize">
              {r.charAt(0).toUpperCase() + r.slice(1)}
            </option>
          ))}
        </FilterSelect>
        <FilterSelect
          value={filterTriggeredBy}
          onChange={setFilterTriggeredBy}
        >
          <option value="">All sources</option>
          <option value="scheduler">Scheduled</option>
          <option value="manual">Manual</option>
          <option value="unknown">Unknown</option>
        </FilterSelect>
        {hasFilters && (
          <button
            onClick={() => {
              setFilterDb("");
              setFilterRotation("");
              setFilterTriggeredBy("");
            }}
            className="px-3 py-1.5 text-xs font-medium transition-colors rounded-lg"
            style={{
              border: "1px solid #2D3F57",
              color: "#64748B",
              background: "#1E293B",
            }}
            onMouseEnter={(e) => {
              (e.currentTarget as HTMLElement).style.color = "#F1F5F9";
              (e.currentTarget as HTMLElement).style.borderColor =
                "#6366F130";
            }}
            onMouseLeave={(e) => {
              (e.currentTarget as HTMLElement).style.color = "#64748B";
              (e.currentTarget as HTMLElement).style.borderColor =
                "#2D3F57";
            }}
          >
            Clear filters
          </button>
        )}
      </div>

      {/* States */}
      {isLoading && (
        <div
          className="flex items-center gap-3 text-sm py-8"
          style={{ color: "#64748B" }}
        >
          <span className="w-4 h-4 border-2 border-[#2D3F57] border-t-[#6366F1] rounded-full animate-spin" />
          Loading backups…
        </div>
      )}
      {isError && (
        <div
          className="flex items-center gap-2 text-sm rounded-xl px-4 py-3"
          style={{
            background: "#EF444410",
            border: "1px solid #EF444430",
            color: "#EF4444",
          }}
        >
          Failed to load backups.
        </div>
      )}

      {/* Empty state */}
      {!isLoading && !isError && filtered.length === 0 && (
        <motion.div
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          className="flex flex-col items-center justify-center py-24 rounded-xl"
          style={{
            background: "#1E293B",
            border: "1px solid #2D3F57",
          }}
        >
          <div className="mb-4 text-[#2D3F57]">
            <svg className="w-10 h-10" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5"><path strokeLinecap="round" strokeLinejoin="round" d="M20.25 6.375c0 2.278-3.694 4.125-8.25 4.125S3.75 8.653 3.75 6.375m16.5 0c0-2.278-3.694-4.125-8.25-4.125S3.75 4.097 3.75 6.375m16.5 0v11.25c0 2.278-3.694 4.125-8.25 4.125s-8.25-1.847-8.25-4.125V6.375m16.5 2.625c0 2.278-3.694 4.125-8.25 4.125s-8.25-1.847-8.25-4.125m16.5 5.625c0 2.278-3.694 4.125-8.25 4.125s-8.25-1.847-8.25-4.125"/></svg>
          </div>
          <p
            className="font-semibold mb-1"
            style={{ color: "#F1F5F9" }}
          >
            No backups found
          </p>
          <p className="text-sm" style={{ color: "#64748B" }}>
            {hasFilters
              ? "Try clearing your filters or trigger a new backup."
              : "Trigger a backup from the Dashboard to get started."}
          </p>
        </motion.div>
      )}

      {/* Grid view */}
      {!isLoading && viewMode === "grid" && filtered.length > 0 && (
        <AnimatePresence>
          <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
            {filtered.map((b, i) => (
              <BackupCard
                key={b.filename}
                backup={b}
                onDelete={handleDelete}
                onRestore={handleRestore}
                onGranular={setGranularTarget}
                index={i}
              />
            ))}
          </div>
        </AnimatePresence>
      )}

      {/* Table view */}
      {!isLoading && viewMode === "table" && filtered.length > 0 && (
        <div
          className="rounded-xl overflow-hidden"
          style={{ border: "1px solid #2D3F57" }}
        >
          <div className="overflow-x-auto">
            <table className="w-full min-w-[960px]">
              <thead>
                <tr
                  style={{
                    background: "#111827",
                    borderBottom: "1px solid #1F2D40",
                  }}
                >
                  {[
                    "Database",
                    "Filename",
                    "Timestamp",
                    "Size",
                    "Rotation",
                    "Source",
                    "Encrypted",
                    "Integrity",
                    "Actions",
                  ].map((h) => (
                    <th
                      key={h}
                      className="text-left py-3 px-4 text-xs font-semibold uppercase tracking-wider whitespace-nowrap"
                      style={{ color: "#64748B" }}
                    >
                      {h}
                    </th>
                  ))}
                </tr>
              </thead>
              <AnimatePresence>
                <tbody>
                  {filtered.map((b, i) => (
                    <BackupRow
                      key={b.filename}
                      backup={b}
                      onDelete={handleDelete}
                      onRestore={handleRestore}
                      onGranular={setGranularTarget}
                      index={i}
                    />
                  ))}
                </tbody>
              </AnimatePresence>
            </table>
          </div>
        </div>
      )}

      {/* Granular restore wizard */}
      {granularTarget && (
        <GranularRestoreWizard
          backup={granularTarget}
          onClose={() => setGranularTarget(null)}
        />
      )}
    </motion.div>
  );
}
