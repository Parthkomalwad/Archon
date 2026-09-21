import { useState, useEffect, useCallback } from "react";
import {
  createGranularSession,
  getRows,
  resolveMultiDependencies,
  applyMultiGranularRestore,
  deleteGranularSession,
  type TableSummary,
  type FKDep,
  type ConflictStrategy,
} from "../api/granular";
import type { Backup } from "../api/client";

// ─── Step types ────────────────────────────────────────────────────────────────

type Step = "loading" | "tables" | "rows" | "deps" | "strategy" | "result";

interface SessionState {
  sessionId: string;
  dbName: string;
  dbType: string;
  tables: TableSummary[];
}

interface RowsState {
  columns: string[];
  rows: Record<string, unknown>[];
  total: number;
  page: number;
}

interface ResultState {
  rowsApplied: number;
  tablesAffected: string[];
}

// ─── SVG icons ─────────────────────────────────────────────────────────────────

const IconTable = () => (
  <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.8}>
    <path strokeLinecap="round" strokeLinejoin="round"
      d="M3 10h18M3 6h18M3 14h18M3 18h18M9 6v12M15 6v12" />
  </svg>
);
const IconRows = () => (
  <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.8}>
    <path strokeLinecap="round" strokeLinejoin="round"
      d="M4 6h16M4 10h16M4 14h16M4 18h16" />
  </svg>
);
const IconLink = () => (
  <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.8}>
    <path strokeLinecap="round" strokeLinejoin="round"
      d="M13.828 10.172a4 4 0 00-5.656 0l-4 4a4 4 0 105.656 5.656l1.102-1.101m-.758-4.899a4 4 0 005.656 0l4-4a4 4 0 00-5.656-5.656l-1.1 1.1" />
  </svg>
);
const IconShield = () => (
  <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.8}>
    <path strokeLinecap="round" strokeLinejoin="round"
      d="M9 12l2 2 4-4m5.618-4.016A11.955 11.955 0 0112 2.944a11.955 11.955 0 01-8.618 3.04A12.02 12.02 0 003 9c0 5.591 3.824 10.29 9 11.622 5.176-1.332 9-6.03 9-11.622 0-1.042-.133-2.052-.382-3.016z" />
  </svg>
);
const IconCheck = () => (
  <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2.5}>
    <path strokeLinecap="round" strokeLinejoin="round" d="M5 13l4 4L19 7" />
  </svg>
);
const IconXSmall = () => (
  <svg className="w-3 h-3" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2.5}>
    <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
  </svg>
);
const IconPlus = () => (
  <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2.5}>
    <path strokeLinecap="round" strokeLinejoin="round" d="M12 4v16m8-8H4" />
  </svg>
);
const IconX = () => (
  <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
    <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
  </svg>
);
const IconChevronLeft = () => (
  <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
    <path strokeLinecap="round" strokeLinejoin="round" d="M15 19l-7-7 7-7" />
  </svg>
);
const IconChevronRight = () => (
  <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
    <path strokeLinecap="round" strokeLinejoin="round" d="M9 5l7 7-7 7" />
  </svg>
);

// ─── Step indicator ────────────────────────────────────────────────────────────

const STEPS: { key: Step; label: string; icon: React.ReactNode }[] = [
  { key: "tables", label: "Select Table", icon: <IconTable /> },
  { key: "rows", label: "Select Rows", icon: <IconRows /> },
  { key: "deps", label: "Dependencies", icon: <IconLink /> },
  { key: "strategy", label: "Strategy", icon: <IconShield /> },
];

function StepIndicator({ current }: { current: Step }) {
  const stepKeys = STEPS.map((s) => s.key);
  const currentIdx = stepKeys.indexOf(current);
  return (
    <div className="flex items-center gap-0 mb-8">
      {STEPS.map((s, i) => {
        const done = i < currentIdx;
        const active = s.key === current;
        return (
          <div key={s.key} className="flex items-center flex-1 min-w-0">
            <div className="flex flex-col items-center flex-1">
              <div
                className={`w-8 h-8 rounded-full flex items-center justify-center text-xs font-bold border-2 transition-all ${done
                    ? "bg-[#6366F1] border-[#6366F1] text-white"
                    : active
                      ? "bg-[#1E293B] border-[#6366F1] text-[#6366F1]"
                      : "bg-[#1E293B] border-[#2D3F57] text-[#64748B]"
                  }`}
              >
                {done ? <IconCheck /> : i + 1}
              </div>
              <span
                className={`text-xs mt-1 font-medium whitespace-nowrap ${active ? "text-[#6366F1]" : done ? "text-[#F1F5F9]" : "text-[#64748B]"
                  }`}
              >
                {s.label}
              </span>
            </div>
            {i < STEPS.length - 1 && (
              <div
                className={`h-0.5 flex-1 mx-1 -mt-5 transition-all ${i < currentIdx ? "bg-[#6366F1]" : "bg-[#2D3F57]"
                  }`}
              />
            )}
          </div>
        );
      })}
    </div>
  );
}

// ─── Selection tray ────────────────────────────────────────────────────────────

function SelectionTray({
  selections, currentTable, onEdit, onRemove,
}: {
  selections: Map<string, Set<number>>;
  currentTable: string | null;
  onEdit: (t: string) => void;
  onRemove: (t: string) => void;
}) {
  const others = Array.from(selections.entries()).filter(([t]) => t !== currentTable);
  if (others.length === 0) return null;
  return (
    <div className="mb-4 p-3 bg-[#6366F1]/10 border border-[#6366F1]/20 rounded-xl">
      <p className="text-xs font-semibold text-[#6366F1] mb-2">Also selected:</p>
      <div className="flex flex-wrap gap-2">
        {others.map(([table, indices]) => (
          <div key={table} className="flex items-center gap-1 bg-[#1E293B] border border-[#6366F1]/20 rounded-lg px-2 py-1">
            <button onClick={() => onEdit(table)} className="flex items-center gap-1.5 text-xs font-semibold text-[#6366F1] hover:text-[#818CF8] transition-colors">
              <IconTable />{table}
              <span className="bg-[#6366F1] text-white rounded-full px-1.5 text-[11px]">{indices.size}</span>
            </button>
            <button onClick={() => onRemove(table)} className="ml-1 text-gray-400 hover:text-red-500 transition-colors">
              <IconXSmall />
            </button>
          </div>
        ))}
      </div>
    </div>
  );
}

// ─── Helpers ───────────────────────────────────────────────────────────────────

function formatCellValue(v: unknown): string {
  if (v === null || v === undefined) return "NULL";
  if (typeof v === "string" && v.length > 60) return v.slice(0, 60) + "…";
  return String(v);
}

function Pill({ label, colour }: { label: string; colour: string }) {
  return (
    <span className={`inline-flex items-center px-2 py-0.5 rounded-full text-xs font-semibold border ${colour}`}>
      {label}
    </span>
  );
}

// ─── Main wizard ───────────────────────────────────────────────────────────────

interface Props {
  backup: Backup;
  onClose: () => void;
}

export default function GranularRestoreWizard({ backup, onClose }: Props) {
  const [step, setStep] = useState<Step>("loading");
  const [error, setError] = useState<string | null>(null);

  // Session
  const [session, setSession] = useState<SessionState | null>(null);

  // Multi-table selections: table → Set of _idx values
  const [allSelections, setAllSelections] = useState<Map<string, Set<number>>>(new Map());

  // Which table is currently open in the rows step
  const [currentTable, setCurrentTable] = useState<string | null>(null);
  const [tableSearch, setTableSearch] = useState("");

  // Row browsing
  const [rowsState, setRowsState] = useState<RowsState>({ columns: [], rows: [], total: 0, page: 1 });
  const [filterCol, setFilterCol] = useState("");
  const [filterVal, setFilterVal] = useState("");
  const [rowsLoading, setRowsLoading] = useState(false);
  const PAGE_SIZE = 50;

  // Derived
  const totalSelected = Array.from(allSelections.values()).reduce((n, s) => n + s.size, 0);
  const tablesWithSelections = allSelections.size;
  const currentIndices: Set<number> = currentTable ? (allSelections.get(currentTable) ?? new Set()) : new Set();

  // Dependencies
  const [depsLoading, setDepsLoading] = useState(false);
  const [deps, setDeps] = useState<FKDep[]>([]);
  const [totalDeps, setTotalDeps] = useState(0);

  // Strategy
  const [strategy, setStrategy] = useState<ConflictStrategy>("skip");
  const [restoring, setRestoring] = useState(false);

  // Result
  const [result, setResult] = useState<ResultState | null>(null);

  // ── Create session on mount ───────────────────────────────────────────────
  useEffect(() => {
    let cancelled = false;
    createGranularSession(backup.filename)
      .then((res) => {
        if (cancelled) return;
        setSession({
          sessionId: res.session_id,
          dbName: res.db_name,
          dbType: res.db_type,
          tables: res.tables,
        });
        setStep("tables");
      })
      .catch((e: Error) => {
        if (cancelled) return;
        setError(e.message);
        setStep("tables"); // show error on tables screen
      });
    return () => { cancelled = true; };
  }, [backup.filename]);

  // ── Close: cleanup session ────────────────────────────────────────────────
  const handleClose = useCallback(() => {
    if (session) deleteGranularSession(session.sessionId).catch(() => { });
    onClose();
  }, [session, onClose]);

  // ── Load rows ─────────────────────────────────────────────────────────────
  const loadRows = useCallback(
    async (table: string, page = 1, fCol = "", fVal = "") => {
      if (!session) return;
      setRowsLoading(true);
      try {
        const res = await getRows(session.sessionId, table, {
          filterCol: fCol || undefined,
          filterVal: fCol ? fVal : undefined,
          page,
          pageSize: PAGE_SIZE,
        });
        setRowsState({ columns: res.columns, rows: res.rows, total: res.total, page: res.page });
      } catch (e: unknown) {
        setError(e instanceof Error ? e.message : String(e));
      } finally {
        setRowsLoading(false);
      }
    },
    [session]
  );

  const openTable = (name: string) => {
    setCurrentTable(name);
    setFilterCol("");
    setFilterVal("");
    setStep("rows");
    loadRows(name, 1, "", "");
  };

  // ── Row toggle helpers ────────────────────────────────────────────────────
  const setCurrentIndices = (updater: (prev: Set<number>) => Set<number>) => {
    if (!currentTable) return;
    setAllSelections((prev) => {
      const next = new Map(prev);
      const updated = updater(next.get(currentTable) ?? new Set());
      if (updated.size === 0) next.delete(currentTable);
      else next.set(currentTable, updated);
      return next;
    });
  };

  const removeTableSelection = (table: string) => {
    setAllSelections((prev) => { const next = new Map(prev); next.delete(table); return next; });
  };

  // ── Row toggles ───────────────────────────────────────────────────────────
  const toggleRow = (idx: number) => {
    setCurrentIndices((prev) => {
      const next = new Set(prev);
      next.has(idx) ? next.delete(idx) : next.add(idx);
      return next;
    });
  };

  const toggleAll = () => {
    const pageIdxs = rowsState.rows.map((r) => r._idx as number);
    const allChecked = pageIdxs.every((i) => currentIndices.has(i));
    setCurrentIndices((prev) => {
      const next = new Set(prev);
      if (allChecked) pageIdxs.forEach((i) => next.delete(i));
      else pageIdxs.forEach((i) => next.add(i));
      return next;
    });
  };

  // ── Resolve dependencies (multi-table) ───────────────────────────────────
  const handleResolveDeps = async () => {
    if (!session || allSelections.size === 0) return;
    setDepsLoading(true);
    setStep("deps");
    try {
      const tables = Array.from(allSelections.entries()).map(([table, indices]) => ({
        table, row_indices: Array.from(indices),
      }));
      const res = await resolveMultiDependencies(session.sessionId, tables);
      setDeps(res.dependencies);
      setTotalDeps(res.total_rows);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setDepsLoading(false);
    }
  };

  // ── Execute restore ───────────────────────────────────────────────────────
  const handleRestore = async () => {
    if (!session || allSelections.size === 0) return;
    setRestoring(true);
    try {
      const tables = Array.from(allSelections.entries()).map(([table, indices]) => ({
        table, row_indices: Array.from(indices),
      }));
      const res = await applyMultiGranularRestore(session.sessionId, tables, strategy);
      setResult({ rowsApplied: res.rows_applied, tablesAffected: res.tables_affected });
      setStep("result");
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setRestoring(false);
    }
  };

  // ─── Render ───────────────────────────────────────────────────────────────
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm p-4">
      <div className="bg-[#1E293B] border border-[#2D3F57] rounded-2xl shadow-2xl w-full max-w-4xl max-h-[92vh] flex flex-col overflow-hidden">

        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-[#2D3F57] shrink-0">
          <div>
            <h2 className="text-base font-bold text-[#F1F5F9]">Granular Restore</h2>
            <p className="text-xs text-[#64748B] mt-0.5 font-mono truncate max-w-md">{backup.filename}</p>
          </div>
          <button onClick={handleClose} className="p-1.5 rounded-lg text-[#64748B] hover:text-[#F1F5F9] hover:bg-[#253347] transition-colors">
            <IconX />
          </button>
        </div>

        {/* Body */}
        <div className="flex-1 overflow-y-auto px-6 py-6">

          {/* ── Loading ── */}
          {step === "loading" && (
            <div className="flex flex-col items-center justify-center h-48 gap-4 text-[#64748B]">
              <span className="w-8 h-8 border-2 border-[#2D3F57] border-t-[#6366F1] rounded-full animate-spin" />
              <p className="text-sm font-medium">Decrypting and parsing backup…</p>
              <p className="text-xs text-[#64748B]">This may take a few seconds for large dumps</p>
            </div>
          )}

          {/* ── Error banner ── */}
          {error && step !== "loading" && (
            <div className="mb-5 flex items-start gap-3 px-4 py-3 bg-[#EF4444]/10 border border-[#EF4444]/30 rounded-xl text-sm text-[#EF4444]">
              <IconX />
              <div>
                <p className="font-semibold">Error</p>
                <p className="text-xs mt-0.5 font-mono">{error}</p>
              </div>
              <button onClick={() => setError(null)} className="ml-auto shrink-0 text-red-400 hover:text-red-700">
                <IconX />
              </button>
            </div>
          )}

          {/* ── Table browser ── */}
          {step === "tables" && session && (
            <>
              <StepIndicator current="tables" />
              <div className="mb-4 flex items-center justify-between">
                <div>
                  <p className="text-sm font-semibold text-[#F1F5F9]">
                    {session.tables.length} table{session.tables.length !== 1 ? "s" : ""} found
                    <span className="ml-2 text-[#64748B] font-normal text-xs">
                      DB: <span className="font-mono font-semibold text-[#F1F5F9]">{session.dbName}</span>
                    </span>
                  </p>
                  {tablesWithSelections > 0 && (
                    <p className="text-xs text-[#6366F1] font-semibold mt-0.5">
                      {totalSelected} row{totalSelected !== 1 ? "s" : ""} selected across {tablesWithSelections} table{tablesWithSelections !== 1 ? "s" : ""}  click to edit
                    </p>
                  )}
                </div>
                <input
                  value={tableSearch}
                  onChange={(e) => setTableSearch(e.target.value)}
                  placeholder="Search tables…"
                  className="bg-[#0C1120] border border-[#1F2D40] text-[#F1F5F9] rounded-xl px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-[#6366F1]/40 w-48 placeholder-[#64748B]"
                />
              </div>
              <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
                {session.tables
                  .filter((t) => t.name.toLowerCase().includes(tableSearch.toLowerCase()))
                  .map((t) => {
                    const sel = allSelections.get(t.name);
                    const hasSel = sel && sel.size > 0;
                    return (
                      <button
                        key={t.name}
                        onClick={() => openTable(t.name)}
                        className={`flex items-start gap-3 p-4 border-2 rounded-xl transition-all text-left group ${hasSel ? "border-[#6366F1]/60 bg-[#6366F1]/5" : "border-[#2D3F57] bg-[#1E293B] hover:border-[#6366F1]/40 hover:bg-[#6366F1]/5"
                          }`}
                      >
                        <div className={`w-8 h-8 rounded-lg flex items-center justify-center shrink-0 transition-colors ${hasSel ? "bg-[#6366F1] text-white" : "bg-[#6366F1]/10 text-[#6366F1]"
                          }`}>
                          {hasSel ? <IconCheck /> : <IconTable />}
                        </div>
                        <div className="min-w-0 flex-1">
                          <p className="font-semibold text-sm text-[#F1F5F9] truncate">{t.name}</p>
                          <p className="text-xs text-[#64748B] mt-0.5">
                            {t.row_count.toLocaleString()} rows
                            {t.fk_count > 0 && <span className="ml-1.5 text-[#6366F1]">· {t.fk_count} FK</span>}
                          </p>
                          {hasSel && (
                            <p className="text-xs font-semibold text-[#6366F1] mt-1">{sel!.size} selected</p>
                          )}
                        </div>
                        <IconChevronRight />
                      </button>
                    );
                  })}
              </div>
            </>
          )}

          {/* ── Row selector ── */}
          {step === "rows" && currentTable && session && (
            <>
              <StepIndicator current="rows" />

              {/* Selection tray: other tables already selected */}
              <SelectionTray
                selections={allSelections}
                currentTable={currentTable}
                onEdit={(t) => openTable(t)}
                onRemove={removeTableSelection}
              />

              {/* Filters */}
              <div className="flex flex-wrap gap-2 mb-4">
                <button
                  onClick={() => setStep("tables")}
                  className="inline-flex items-center gap-1.5 text-xs font-semibold text-[#64748B] hover:text-[#F1F5F9] bg-[#253347] hover:bg-[#2D3F57] px-3 py-1.5 rounded-lg transition-colors"
                >
                  <IconChevronLeft /> Back to tables
                </button>
                <div className="flex items-center gap-1 bg-[#6366F1]/10 border border-[#6366F1]/20 rounded-lg px-3 py-1.5">
                  <IconTable />
                  <span className="text-xs font-bold text-[#6366F1]">{currentTable}</span>
                  {currentIndices.size > 0 && (
                    <span className="ml-1 bg-[#6366F1] text-white rounded-full px-1.5 text-[11px] font-bold">{currentIndices.size}</span>
                  )}
                </div>
                <select
                  value={filterCol}
                  onChange={(e) => setFilterCol(e.target.value)}
                  className="bg-[#0C1120] border border-[#1F2D40] text-[#F1F5F9] rounded-lg px-3 py-1.5 text-xs focus:outline-none focus:ring-2 focus:ring-[#6366F1]/40"
                >
                  <option value="">Filter by column…</option>
                  {rowsState.columns.map((c) => (
                    <option key={c} value={c}>{c}</option>
                  ))}
                </select>
                {filterCol && (
                  <input
                    value={filterVal}
                    onChange={(e) => setFilterVal(e.target.value)}
                    onKeyDown={(e) => e.key === "Enter" && loadRows(currentTable, 1, filterCol, filterVal)}
                    placeholder="Filter value…"
                    className="bg-[#0C1120] border border-[#1F2D40] text-[#F1F5F9] placeholder-[#64748B] rounded-lg px-3 py-1.5 text-xs focus:outline-none focus:ring-2 focus:ring-[#6366F1]/40 w-36"
                  />
                )}
                {(filterCol || filterVal) && (
                  <button
                    onClick={() => { setFilterCol(""); setFilterVal(""); loadRows(currentTable, 1, "", ""); }}
                    className="text-xs text-[#64748B] hover:text-[#F1F5F9] px-2 py-1.5"
                  >Clear</button>
                )}
                {filterCol && (
                  <button
                    onClick={() => loadRows(currentTable, 1, filterCol, filterVal)}
                    className="text-xs font-semibold text-white bg-[#6366F1] hover:bg-[#818CF8] px-3 py-1.5 rounded-lg transition-colors"
                  >Search</button>
                )}
              </div>

              {/* Selection summary */}
              <div className="flex items-center justify-between mb-3">
                <p className="text-xs text-[#64748B]">
                  {rowsState.total.toLocaleString()} rows total
                  {currentIndices.size > 0 && (
                    <span className="ml-2 font-semibold text-[#6366F1]">
                      · {currentIndices.size} selected in {currentTable}
                    </span>
                  )}
                </p>
                {currentIndices.size > 0 && (
                  <button
                    onClick={() => setCurrentIndices(() => new Set())}
                    className="text-xs text-[#64748B] hover:text-[#F1F5F9] transition-colors"
                  >Clear this table</button>
                )}
              </div>

              {/* Rows table */}
              {rowsLoading ? (
                <div className="flex items-center gap-3 text-[#64748B] text-sm py-8 justify-center">
                  <span className="w-5 h-5 border-2 border-[#2D3F57] border-t-[#6366F1] rounded-full animate-spin" />
                  Loading rows…
                </div>
              ) : (
                <div className="border border-[#2D3F57] rounded-xl overflow-hidden">
                  <div className="overflow-x-auto">
                    <table className="w-full text-xs">
                      <thead>
                        <tr className="bg-[#0C1120] border-b border-[#1F2D40]">
                          <th className="px-3 py-2.5 w-9">
                            <input
                              type="checkbox"
                              className="rounded text-[#6366F1] focus:ring-[#6366F1]"
                              checked={
                                rowsState.rows.length > 0 &&
                                rowsState.rows.every((r) => currentIndices.has(r._idx as number))
                              }
                              onChange={toggleAll}
                            />
                          </th>
                          {rowsState.columns.map((col) => (
                            <th key={col} className="px-3 py-2.5 text-left font-semibold text-[#64748B] uppercase tracking-wide whitespace-nowrap">
                              {col}
                            </th>
                          ))}
                        </tr>
                      </thead>
                      <tbody className="divide-y divide-[#1F2D40]">
                        {rowsState.rows.map((row) => {
                          const idx = row._idx as number;
                          const checked = currentIndices.has(idx);
                          return (
                            <tr
                              key={idx}
                              onClick={() => toggleRow(idx)}
                              className={`cursor-pointer transition-colors ${checked
                                  ? "bg-[#6366F1]/10 hover:bg-[#6366F1]/15"
                                  : "bg-[#1E293B] hover:bg-[#253347]"
                                }`}
                            >
                              <td className="px-3 py-2" onClick={(e) => e.stopPropagation()}>
                                <input
                                  type="checkbox"
                                  className="rounded text-[#6366F1] focus:ring-[#6366F1]"
                                  checked={checked}
                                  onChange={() => toggleRow(idx)}
                                />
                              </td>
                              {rowsState.columns.map((col) => (
                                <td key={col} className="px-3 py-2 whitespace-nowrap">
                                  {row[col] === null || row[col] === undefined ? (
                                    <span className="text-[#64748B] italic">NULL</span>
                                  ) : (
                                    <span className={`font-mono ${typeof row[col] === "number" ? "text-[#6366F1]" : "text-[#F1F5F9]"}`}>
                                      {formatCellValue(row[col])}
                                    </span>
                                  )}
                                </td>
                              ))}
                            </tr>
                          );
                        })}
                        {rowsState.rows.length === 0 && (
                          <tr>
                            <td colSpan={rowsState.columns.length + 1} className="px-4 py-8 text-center text-[#64748B] text-xs">
                              No rows match the current filter
                            </td>
                          </tr>
                        )}
                      </tbody>
                    </table>
                  </div>
                </div>
              )}

              {/* Pagination */}
              {rowsState.total > PAGE_SIZE && (
                <div className="flex items-center justify-center gap-2 mt-4">
                  <button
                    disabled={rowsState.page <= 1}
                    onClick={() => loadRows(currentTable, rowsState.page - 1, filterCol, filterVal)}
                    className="px-3 py-1.5 text-xs text-[#64748B] rounded-lg border border-[#2D3F57] disabled:opacity-40 hover:bg-[#253347] hover:text-[#F1F5F9] transition-colors inline-flex items-center gap-1"
                  ><IconChevronLeft /> Prev</button>
                  <span className="text-xs text-[#64748B]">
                    Page {rowsState.page} of {Math.ceil(rowsState.total / PAGE_SIZE)}
                  </span>
                  <button
                    disabled={rowsState.page >= Math.ceil(rowsState.total / PAGE_SIZE)}
                    onClick={() => loadRows(currentTable, rowsState.page + 1, filterCol, filterVal)}
                    className="px-3 py-1.5 text-xs text-[#64748B] rounded-lg border border-[#2D3F57] disabled:opacity-40 hover:bg-[#253347] hover:text-[#F1F5F9] transition-colors inline-flex items-center gap-1"
                  >Next <IconChevronRight /></button>
                </div>
              )}
            </>
          )}

          {/* ── Dependencies ── */}
          {step === "deps" && (
            <>
              <StepIndicator current="deps" />
              {depsLoading ? (
                <div className="flex flex-col items-center justify-center h-40 gap-3 text-[#64748B]">
                  <span className="w-6 h-6 border-2 border-[#2D3F57] border-t-[#6366F1] rounded-full animate-spin" />
                  <p className="text-sm font-medium">Resolving FK dependencies…</p>
                </div>
              ) : (
                <>
                  <div className="mb-5">
                    <p className="text-sm font-semibold text-[#F1F5F9] mb-1">
                      {totalDeps} row{totalDeps !== 1 ? "s" : ""} will be restored across {deps.length} table{deps.length !== 1 ? "s" : ""}
                    </p>
                    <p className="text-xs text-[#64748B]">
                      All rows referenced via foreign keys have been automatically included to maintain data integrity.
                    </p>
                  </div>
                  <div className="space-y-3">
                    {deps.map((dep) => {
                      const isExplicit = allSelections.has(dep.table);
                      return (
                        <div key={dep.table} className="border border-[#2D3F57] rounded-xl overflow-hidden">
                          <div className={`flex items-center justify-between px-4 py-3 ${isExplicit ? "bg-[#6366F1]/10 border-b border-[#6366F1]/20" : "bg-[#0C1120] border-b border-[#1F2D40]"}`}>
                            <div className="flex items-center gap-2">
                              <IconTable />
                              <span className="font-bold text-sm text-[#F1F5F9]">{dep.table}</span>
                              {isExplicit && <Pill label="Selected" colour="bg-[#6366F1]/10 text-[#6366F1] border-[#6366F1]/20" />}
                              {!isExplicit && <Pill label="FK Dependency" colour="bg-[#F59E0B]/10 text-[#F59E0B] border-[#F59E0B]/20" />}
                            </div>
                            <span className="text-xs font-semibold text-[#64748B]">
                              {dep.row_count} row{dep.row_count !== 1 ? "s" : ""}
                            </span>
                          </div>
                          {/* Preview up to 3 rows */}
                          {dep.rows.length > 0 && (
                            <div className="overflow-x-auto">
                              <table className="w-full text-xs">
                                <thead>
                                  <tr className="border-b border-[#1F2D40]">
                                    {Object.keys(dep.rows[0]).slice(0, 6).map((col) => (
                                      <th key={col} className="px-3 py-2 text-left text-[#64748B] font-semibold uppercase tracking-wide whitespace-nowrap">
                                        {col}
                                      </th>
                                    ))}
                                  </tr>
                                </thead>
                                <tbody className="divide-y divide-[#1F2D40]">
                                  {dep.rows.slice(0, 3).map((row, ri) => (
                                    <tr key={ri} className="bg-[#1E293B] hover:bg-[#253347]">
                                      {Object.entries(row).slice(0, 6).map(([col, val]) => (
                                        <td key={col} className="px-3 py-2 whitespace-nowrap font-mono text-[#F1F5F9]">
                                          {val === null ? <span className="text-[#64748B] italic">NULL</span> : formatCellValue(val)}
                                        </td>
                                      ))}
                                    </tr>
                                  ))}
                                </tbody>
                              </table>
                              {dep.row_count > 3 && (
                                <p className="px-4 py-2 text-xs text-[#64748B] bg-[#0C1120] border-t border-[#1F2D40]">
                                  + {dep.row_count - 3} more rows
                                </p>
                              )}
                            </div>
                          )}
                        </div>
                      );
                    })}
                  </div>
                </>
              )}
            </>
          )}

          {/* ── Strategy ── */}
          {step === "strategy" && (
            <>
              <StepIndicator current="strategy" />
              <p className="text-sm font-semibold text-[#F1F5F9] mb-1">
                How should existing rows be handled?
              </p>
              <p className="text-xs text-[#64748B] mb-5">
                Choose what happens when a row in the backup already exists in the live database.
              </p>
              <div className="space-y-3 mb-6">
                {(
                  [
                    {
                      value: "skip",
                      label: "Skip existing rows",
                      desc: "INSERT IGNORE  if a row already exists, leave it untouched. Safe choice.",
                      colour: "border-[#10B981]/60 bg-[#10B981]/5",
                      badge: "Recommended",
                      badgeColour: "bg-[#10B981]/10 text-[#10B981] border-[#10B981]/20",
                    },
                    {
                      value: "replace",
                      label: "Replace existing rows",
                      desc: "REPLACE INTO  delete the existing row, then insert the backup version.",
                      colour: "border-[#F59E0B]/60 bg-[#F59E0B]/5",
                      badge: "Overwrites data",
                      badgeColour: "bg-[#F59E0B]/10 text-[#F59E0B] border-[#F59E0B]/20",
                    },
                    {
                      value: "merge",
                      label: "Merge (update existing)",
                      desc: "ON DUPLICATE KEY UPDATE  update the existing row's columns with backup values.",
                      colour: "border-blue-500/60 bg-blue-500/5",
                      badge: "Partial overwrite",
                      badgeColour: "bg-blue-500/10 text-blue-400 border-blue-500/20",
                    },
                  ] as const
                ).map((opt) => (
                  <label
                    key={opt.value}
                    className={`flex items-start gap-3 p-4 rounded-xl border-2 cursor-pointer transition-all ${strategy === opt.value ? opt.colour : "border-[#2D3F57] bg-[#1E293B] hover:border-[#6366F1]/30"
                      }`}
                  >
                    <input
                      type="radio"
                      name="strategy"
                      value={opt.value}
                      checked={strategy === opt.value}
                      onChange={() => setStrategy(opt.value)}
                      className="mt-0.5 text-[#6366F1] focus:ring-[#6366F1]"
                    />
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2 mb-0.5">
                        <span className="text-sm font-semibold text-[#F1F5F9]">{opt.label}</span>
                        <Pill label={opt.badge} colour={opt.badgeColour} />
                      </div>
                      <p className="text-xs text-[#64748B]">{opt.desc}</p>
                    </div>
                  </label>
                ))}
              </div>

              {/* Summary */}
              <div className="bg-[#0C1120] border border-[#1F2D40] rounded-xl px-4 py-3 text-xs space-y-1">
                <div className="flex justify-between">
                  <span className="text-[#64748B] font-medium">Backup file</span>
                  <span className="font-mono font-semibold text-[#F1F5F9] truncate max-w-xs">{backup.filename}</span>
                </div>
                {Array.from(allSelections.entries()).map(([table, indices]) => (
                  <div key={table} className="flex justify-between">
                    <span className="text-[#64748B] font-medium">{table}</span>
                    <span className="font-semibold text-[#F1F5F9]">{indices.size} row{indices.size !== 1 ? "s" : ""}</span>
                  </div>
                ))}
                <div className="flex justify-between border-t border-[#1F2D40] pt-1 mt-1">
                  <span className="text-[#64748B] font-medium">Total with deps</span>
                  <span className="font-bold text-[#6366F1]">{totalDeps} rows</span>
                </div>
              </div>
            </>
          )}

          {/* ── Result ── */}
          {step === "result" && result && (
            <div className="flex flex-col items-center justify-center py-8 text-center">
              <div className="w-16 h-16 rounded-full bg-[#10B981]/10 border border-[#10B981]/20 flex items-center justify-center mb-4">
                <svg className="w-8 h-8 text-[#10B981]" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2.5}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M5 13l4 4L19 7" />
                </svg>
              </div>
              <h3 className="text-xl font-bold text-[#F1F5F9] mb-1">Restore Complete</h3>
              <p className="text-sm text-[#64748B] mb-6">
                {result.rowsApplied} row{result.rowsApplied !== 1 ? "s" : ""} applied across{" "}
                {result.tablesAffected.length} table{result.tablesAffected.length !== 1 ? "s" : ""}
              </p>
              <div className="flex flex-wrap gap-2 justify-center mb-6">
                {result.tablesAffected.map((t) => (
                  <span key={t} className="inline-flex items-center gap-1.5 px-3 py-1.5 bg-[#6366F110] border border-[#6366F130] text-[#818CF8] text-xs font-semibold rounded-lg">
                    <IconTable /> {t}
                  </span>
                ))}
              </div>
              <button
                onClick={handleClose}
                className="px-6 py-2.5 bg-[#6366F1] text-white text-sm font-semibold rounded-xl hover:bg-[#818CF8] transition-colors"
              >
                Done
              </button>
            </div>
          )}
        </div>

        {/* Footer actions */}
        {!["loading", "result"].includes(step) && (
          <div className="shrink-0 flex items-center justify-between px-6 py-4 border-t border-[#2D3F57]">
            <button
              onClick={handleClose}
              className="px-4 py-2 text-sm font-semibold text-[#64748B] hover:text-[#F1F5F9] bg-[#0C1120] border border-[#1F2D40] rounded-xl hover:border-[#6366F1]/30 transition-colors"
            >
              Cancel
            </button>

            <div className="flex gap-2">
              {step === "rows" && (
                <>
                  <button
                    onClick={() => setStep("tables")}
                    className="inline-flex items-center gap-1.5 px-3 py-2 text-xs font-semibold text-[#818CF8] bg-[#6366F110] hover:bg-[#6366F120] border border-[#6366F130] rounded-xl transition-colors"
                  >
                    <IconPlus /> Add another table
                  </button>
                  <button
                    onClick={handleResolveDeps}
                    disabled={totalSelected === 0}
                    className="inline-flex items-center gap-2 px-4 py-2 text-sm font-semibold bg-[#6366F1] text-white rounded-xl hover:bg-[#818CF8] disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
                  >
                    Review
                    {totalSelected > 0 && (
                      <span className="bg-[#6366F110]0 rounded-full px-1.5 text-xs">
                        {totalSelected} row{totalSelected !== 1 ? "s" : ""}
                        {tablesWithSelections > 1 ? `, ${tablesWithSelections} tables` : ""}
                      </span>
                    )}
                    <IconChevronRight />
                  </button>
                </>
              )}

              {step === "tables" && totalSelected > 0 && (
                <button
                  onClick={handleResolveDeps}
                  className="inline-flex items-center gap-2 px-4 py-2 text-sm font-semibold bg-[#6366F1] text-white rounded-xl hover:bg-[#818CF8] transition-colors"
                >
                  <IconLink />
                  Review {totalSelected} row{totalSelected !== 1 ? "s" : ""}
                  {tablesWithSelections > 1 ? ` (${tablesWithSelections} tables)` : ""}
                  <IconChevronRight />
                </button>
              )}

              {step === "deps" && !depsLoading && (
                <button
                  onClick={() => setStep("strategy")}
                  className="inline-flex items-center gap-2 px-4 py-2 text-sm font-semibold bg-[#6366F1] text-white rounded-xl hover:bg-[#818CF8] transition-colors"
                >
                  <IconShield /> Choose strategy <IconChevronRight />
                </button>
              )}

              {step === "strategy" && (
                <button
                  onClick={handleRestore}
                  disabled={restoring}
                  className="inline-flex items-center gap-2 px-5 py-2 text-sm font-bold bg-[#6366F1] text-white rounded-xl hover:bg-[#818CF8] disabled:opacity-60 transition-colors shadow-sm shadow-[#6366F130]"
                >
                  {restoring ? (
                    <>
                      <span className="w-4 h-4 border-2 border-white/30 border-t-white rounded-full animate-spin" />
                      Applying…
                    </>
                  ) : (
                    <>
                      <IconCheck /> Apply {totalDeps} row{totalDeps !== 1 ? "s" : ""}
                    </>
                  )}
                </button>
              )}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
