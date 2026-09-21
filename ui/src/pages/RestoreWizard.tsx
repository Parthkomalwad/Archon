import { useState, useEffect } from "react";
import { useNavigate } from "react-router-dom";
import { getBackups, triggerRestore, type Backup } from "../api/client";

// ─── Step indicator ──────────────────────────────────────────────────────────

function Steps({ current }: { current: number }) {
  const labels = ["Select Backup", "Confirm", "Done"];
  return (
    <div className="flex items-center gap-0 mb-8">
      {labels.map((label, i) => {
        const step = i + 1;
        const done = step < current;
        const active = step === current;
        return (
          <div key={step} className="flex items-center">
            <div className="flex flex-col items-center">
              <div
                className={`w-8 h-8 rounded-full flex items-center justify-center text-sm font-semibold
                  ${done ? "bg-[#10B981] text-white" : active ? "bg-[#6366F1] text-white" : "bg-[#253347] text-[#64748B]"}`}
              >
                {done ? (
                  <svg className="w-3.5 h-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5"><path strokeLinecap="round" strokeLinejoin="round" d="M4.5 12.75l6 6 9-13.5"/></svg>
                ) : step}
              </div>
              <span className={`mt-1 text-xs font-medium ${active ? "text-[#6366F1]" : "text-[#64748B]"}`}>
                {label}
              </span>
            </div>
            {i < labels.length - 1 && (
              <div className={`h-0.5 w-20 mx-1 mb-5 ${done ? "bg-[#10B981]" : "bg-[#2D3F57]"}`} />
            )}
          </div>
        );
      })}
    </div>
  );
}

// ─── Rotation badge ──────────────────────────────────────────────────────────

function RotationBadge({ type }: { type: string }) {
  const colors: Record<string, string> = {
    hourly: "bg-blue-500/10 text-blue-400 border-blue-500/20",
    daily: "bg-[#6366F1]/10 text-[#6366F1] border-[#6366F1]/20",
    weekly: "bg-[#6366F1]/10 text-[#818CF8] border-[#6366F1]/20",
    monthly: "bg-[#6366F1]/10 text-[#818CF8] border-[#6366F1]/20",
  };
  return (
    <span className={`px-2 py-0.5 rounded-full text-xs font-semibold border ${colors[type] ?? "bg-[#253347] text-[#64748B] border-[#2D3F57]"}`}>
      {type}
    </span>
  );
}

// ─── Format bytes ─────────────────────────────────────────────────────────────

function fmtBytes(b: number) {
  if (b < 1024) return `${b} B`;
  if (b < 1024 * 1024) return `${(b / 1024).toFixed(1)} KB`;
  return `${(b / 1024 / 1024).toFixed(1)} MB`;
}

// ─── Main wizard ──────────────────────────────────────────────────────────────

export default function RestoreWizard() {
  const navigate = useNavigate();

  const [step, setStep] = useState(1);
  const [backups, setBackups] = useState<Backup[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [selected, setSelected] = useState<Backup | null>(null);
  const [filter, setFilter] = useState("");
  const [restoring, setRestoring] = useState(false);

  useEffect(() => {
    setLoading(true);
    getBackups()
      .then((r) => setBackups(r.backups))
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  }, []);

  async function executeRestore() {
    if (!selected) return;
    setRestoring(true);
    setError("");
    try {
      await triggerRestore(selected.filename);
      setStep(3);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setRestoring(false);
    }
  }

  const filtered = backups.filter(
    (b) =>
      b.filename.toLowerCase().includes(filter.toLowerCase()) ||
      b.database.toLowerCase().includes(filter.toLowerCase())
  );

  // ── Step 3: Done ─────────────────────────────────────────────────────────
  if (step === 3) {
    return (
      <div className="max-w-2xl mx-auto text-center py-20">
        <div className="w-16 h-16 rounded-full bg-[#10B981]/10 border border-[#10B981]/30 flex items-center justify-center mx-auto mb-6 text-[#10B981]">
          <svg className="w-8 h-8" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5"><path strokeLinecap="round" strokeLinejoin="round" d="M4.5 12.75l6 6 9-13.5"/></svg>
        </div>
        <h2 className="text-2xl font-bold text-[#F1F5F9] mb-2">Restore Complete</h2>
        <p className="text-[#64748B] text-sm mb-2">The following backup was restored successfully.</p>
        <p className="font-mono text-xs bg-[#1E293B] border border-[#2D3F57] px-3 py-1.5 rounded-lg text-[#6366F1] inline-block mb-8">
          {selected?.filename}
        </p>
        <div className="flex justify-center gap-3">
          <button
            onClick={() => { setStep(1); setSelected(null); }}
            className="px-5 py-2 border border-[#2D3F57] text-[#64748B] rounded-lg text-sm hover:border-[#6366F1]/30 hover:text-[#F1F5F9] transition-colors"
          >
            Restore Another
          </button>
          <button
            onClick={() => navigate("/backups")}
            className="px-5 py-2 bg-[#6366F1] text-white rounded-lg text-sm font-medium hover:bg-[#818CF8] transition-colors"
          >
            Back to Backups
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="max-w-4xl mx-auto">
      <div className="mb-6">
        <h1 className="text-2xl font-bold text-[#F1F5F9]">Restore Wizard</h1>
        <p className="text-sm text-[#64748B] mt-1">Select a backup and restore it to the target database.</p>
      </div>

      <Steps current={step} />

      <div className="bg-[#1E293B] rounded-xl border border-[#2D3F57] p-6">

        {/* ── Step 1: Select backup ── */}
        {step === 1 && (
          <div className="space-y-4">
            <div className="flex items-center justify-between">
              <h2 className="text-base font-semibold text-[#F1F5F9]">Select a backup to restore</h2>
              <span className="text-xs text-[#64748B]">{backups.length} available</span>
            </div>

            <input
              type="text"
              placeholder="Filter by filename or database…"
              value={filter}
              onChange={(e) => setFilter(e.target.value)}
              className="w-full bg-[#0C1120] border border-[#1F2D40] text-[#F1F5F9] placeholder-[#64748B] rounded-lg px-4 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-[#6366F1]/40 font-mono"
            />

            {loading && (
              <div className="flex items-center justify-center py-12">
                <div className="w-8 h-8 rounded-full border-4 border-[#2D3F57] border-t-[#6366F1] animate-spin" />
              </div>
            )}

            {!loading && filtered.length === 0 && (
              <div className="text-center py-12 text-[#64748B] text-sm">
                No backups found. Trigger a backup first.
              </div>
            )}

            {!loading && filtered.length > 0 && (
              <div className="space-y-2 max-h-96 overflow-y-auto pr-1">
                {filtered.map((b) => (
                  <button
                    key={b.filename}
                    onClick={() => setSelected(b)}
                    className={`w-full text-left p-4 rounded-lg border transition-all ${
                      selected?.filename === b.filename
                        ? "border-[#6366F1] bg-[#6366F1]/10"
                        : "border-[#2D3F57] hover:border-[#6366F1]/40 hover:bg-[#253347]"
                    }`}
                  >
                    <div className="flex items-center justify-between gap-4 flex-wrap">
                      <span className="font-mono text-xs text-[#F1F5F9] break-all">{b.filename}</span>
                      <div className="flex items-center gap-2 shrink-0">
                        <RotationBadge type={b.rotation_type} />
                        {b.encrypted && (
                          <span className="px-2 py-0.5 rounded-full text-xs font-semibold bg-[#6366F1]/10 text-[#6366F1] border border-[#6366F1]/20">ENC</span>
                        )}
                        <span className="text-xs text-[#64748B]">{fmtBytes(b.size_bytes)}</span>
                      </div>
                    </div>
                    <div className="mt-1 flex items-center gap-3">
                      <span className="text-xs text-[#64748B]">{b.database}</span>
                      <span className="text-xs text-[#64748B]">·</span>
                      <span className="text-xs text-[#64748B] font-mono">{b.timestamp}</span>
                    </div>
                  </button>
                ))}
              </div>
            )}

            {error && (
              <div className="bg-[#EF4444]/10 border border-[#EF4444]/30 rounded-lg p-3 text-sm text-[#EF4444]">{error}</div>
            )}

            <div className="flex justify-end pt-2">
              <button
                disabled={!selected}
                onClick={() => setStep(2)}
                className="px-5 py-2 bg-[#6366F1] text-white rounded-lg text-sm font-medium hover:bg-[#818CF8] transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
              >
                Continue →
              </button>
            </div>
          </div>
        )}

        {/* ── Step 2: Confirm ── */}
        {step === 2 && selected && (
          <div className="space-y-4">
            <h2 className="text-base font-semibold text-[#F1F5F9]">Confirm Restore</h2>

            <div className="bg-[#F59E0B]/10 border border-[#F59E0B]/20 rounded-lg p-4 text-sm text-[#F59E0B]">
              <p className="font-semibold mb-1 flex items-center gap-2"><svg className="w-4 h-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5"><path strokeLinecap="round" strokeLinejoin="round" d="M12 9v3.75m-9.303 3.376c-.866 1.5.217 3.374 1.948 3.374h14.71c1.73 0 2.813-1.874 1.948-3.374L13.949 3.378c-.866-1.5-3.032-1.5-3.898 0L2.697 16.126zM12 15.75h.007v.008H12v-.008z"/></svg> This will overwrite the target database.</p>
              <p className="text-[#F59E0B]/80">The current database will be dropped and replaced with the backup data. This action cannot be undone.</p>
            </div>

            <div className="bg-[#0C1120] border border-[#1F2D40] rounded-lg p-4 space-y-2 text-sm">
              <div className="flex justify-between">
                <span className="text-[#64748B]">File</span>
                <span className="font-mono text-xs text-[#F1F5F9] max-w-xs truncate">{selected.filename}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-[#64748B]">Database</span>
                <span className="text-[#F1F5F9]">{selected.database}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-[#64748B]">Size</span>
                <span className="text-[#F1F5F9]">{fmtBytes(selected.size_bytes)}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-[#64748B]">Encrypted</span>
                <span className={selected.encrypted ? "text-[#6366F1]" : "text-[#64748B]"}>
                  {selected.encrypted ? "Yes" : "No"}
                </span>
              </div>
              <div className="flex justify-between">
                <span className="text-[#64748B]">Integrity</span>
                <span className={selected.sidecar_exists ? "text-[#10B981]" : "text-[#EF4444]"}>
                  {selected.sidecar_exists ? (
                    <span className="inline-flex items-center gap-1">
                      <svg className="w-3.5 h-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5"><path strokeLinecap="round" strokeLinejoin="round" d="M4.5 12.75l6 6 9-13.5"/></svg>
                      SHA-256 sidecar present
                    </span>
                  ) : (
                    <span className="inline-flex items-center gap-1">
                      <svg className="w-3.5 h-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5"><path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12"/></svg>
                      Sidecar missing
                    </span>
                  )}
                </span>
              </div>
            </div>

            {error && (
              <div className="bg-[#EF4444]/10 border border-[#EF4444]/30 rounded-lg p-3 text-sm text-[#EF4444]">{error}</div>
            )}

            <div className="flex items-center gap-3 pt-2">
              <button
                onClick={() => setStep(1)}
                className="px-5 py-2 border border-[#2D3F57] text-[#64748B] rounded-lg text-sm hover:border-[#6366F1]/30 hover:text-[#F1F5F9] transition-colors"
              >
                ← Back
              </button>
              <button
                onClick={executeRestore}
                disabled={restoring}
                className="px-5 py-2 bg-[#EF4444] text-white rounded-lg text-sm font-medium hover:bg-red-500 transition-colors disabled:opacity-50"
              >
                {restoring ? "Restoring…" : "Restore Now"}
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
