import { useState } from "react";
import { triggerRestore, type Backup } from "../api/client";

interface RestoreDialogProps {
  backup: Backup;
  onClose: () => void;
}

function formatBytes(n: number): string {
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
  return `${(n / (1024 * 1024)).toFixed(1)} MB`;
}

function InfoRow({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="flex items-start justify-between gap-4 py-2 border-b border-[#1F2D40] last:border-0">
      <span className="text-xs text-[#64748B] font-medium shrink-0">{label}</span>
      <span className="text-xs text-[#F1F5F9] font-semibold text-right">{value}</span>
    </div>
  );
}

export default function RestoreDialog({ backup, onClose }: RestoreDialogProps) {
  const [confirmText, setConfirmText] = useState("");
  const [status, setStatus] = useState<"idle" | "loading" | "done" | "error">("idle");
  const [errorMsg, setErrorMsg] = useState("");

  const canConfirm = confirmText === "restore";

  const handleRestore = async () => {
    if (!canConfirm) return;
    setStatus("loading");
    try {
      await triggerRestore(backup.filename);
      setStatus("done");
    } catch (e: unknown) {
      setErrorMsg(e instanceof Error ? e.message : String(e));
      setStatus("error");
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-end sm:items-center justify-center bg-black/60 backdrop-blur-sm p-4">
      <div className="bg-[#1E293B] border border-[#2D3F57] rounded-2xl shadow-2xl w-full max-w-lg">
        {/* Header */}
        <div className="flex items-center gap-3 px-6 py-5 border-b border-[#2D3F57]">
          <div className="w-10 h-10 rounded-xl bg-[#EF4444]/10 border border-[#EF4444]/20 flex items-center justify-center text-xl shrink-0 text-[#EF4444]">
            ↩
          </div>
          <div>
            <h2 className="text-base font-bold text-[#F1F5F9]">Restore Database</h2>
            <p className="text-xs text-[#64748B] mt-0.5">This will overwrite the current database</p>
          </div>
        </div>

        <div className="px-6 py-5 space-y-4">
          {/* Backup metadata */}
          <div className="bg-[#0C1120] rounded-xl border border-[#1F2D40] px-4 py-1">
            <InfoRow label="Database" value={backup.database} />
            <InfoRow label="Timestamp" value={backup.timestamp.replace("T", " ")} />
            <InfoRow label="Storage backend" value={backup.storage_backend} />
            <InfoRow label="Size" value={formatBytes(backup.size_bytes)} />
            <InfoRow label="Encrypted" value={backup.encrypted ? "Yes" : "No"} />
            <InfoRow
              label="Filename"
              value={<span className="font-mono text-[#64748B] break-all">{backup.filename}</span>}
            />
          </div>

          {/* Danger alert */}
          <div className="flex gap-3 items-start bg-[#EF4444]/10 border border-[#EF4444]/20 text-[#EF4444] rounded-xl px-4 py-3">
            <span className="shrink-0 mt-0.5 text-[#EF4444]"><svg className="w-4 h-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5"><path strokeLinecap="round" strokeLinejoin="round" d="M12 9v3.75m-9.303 3.376c-.866 1.5.217 3.374 1.948 3.374h14.71c1.73 0 2.813-1.874 1.948-3.374L13.949 3.378c-.866-1.5-3.032-1.5-3.898 0L2.697 16.126zM12 15.75h.007v.008H12v-.008z"/></svg></span>
            <div>
              <p className="text-sm font-bold">Database will be dropped and recreated</p>
              <p className="text-xs text-[#EF4444]/80 mt-0.5">All data added after this backup will be permanently lost.</p>
            </div>
          </div>

          {/* Confirm input */}
          {status === "idle" && (
            <div>
              <label className="block text-sm text-[#64748B] font-medium mb-1.5">
                Type <span className="font-mono font-bold text-[#F1F5F9]">restore</span> to confirm:
              </label>
              <input
                type="text"
                value={confirmText}
                onChange={(e) => setConfirmText(e.target.value)}
                placeholder='Type "restore" to confirm'
                className="w-full bg-[#0C1120] border border-[#1F2D40] text-[#F1F5F9] placeholder-[#64748B] rounded-xl px-3 py-2.5 text-sm focus:outline-none focus:ring-2 focus:ring-[#6366F1]/50 focus:border-[#6366F1]/40"
              />
            </div>
          )}

          {status === "loading" && (
            <div className="flex items-center gap-2 text-sm text-[#6366F1] bg-[#6366F1]/10 border border-[#6366F1]/20 rounded-xl px-4 py-3 font-medium">
              <span className="w-4 h-4 border-2 border-[#6366F1]/30 border-t-[#6366F1] rounded-full animate-spin shrink-0" />
              Restoring database…
            </div>
          )}
          {status === "done" && (
            <div className="flex items-center gap-2 text-sm text-[#10B981] bg-[#10B981]/10 border border-[#10B981]/20 rounded-xl px-4 py-3 font-semibold">
              <svg className="w-3.5 h-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5"><path strokeLinecap="round" strokeLinejoin="round" d="M4.5 12.75l6 6 9-13.5"/></svg>
              Restore completed successfully.
            </div>
          )}
          {status === "error" && (
            <div className="flex items-start gap-2 text-sm text-[#EF4444] bg-[#EF4444]/10 border border-[#EF4444]/20 rounded-xl px-4 py-3">
              {errorMsg}
            </div>
          )}
        </div>

        {/* Footer */}
        <div className="flex justify-end gap-2 px-6 py-4 border-t border-[#2D3F57]">
          <button
            onClick={onClose}
            className="px-4 py-2 text-sm font-semibold bg-[#253347] text-[#F1F5F9] rounded-xl hover:bg-[#2D3F57] transition-colors"
          >
            {status === "done" ? "Close" : "Cancel"}
          </button>
          {status === "idle" && (
            <button
              onClick={handleRestore}
              disabled={!canConfirm}
              className={`px-4 py-2 text-sm font-semibold rounded-xl transition-colors ${
                canConfirm
                  ? "bg-[#EF4444] text-white hover:bg-red-500"
                  : "bg-[#253347] text-[#64748B] cursor-not-allowed"
              }`}
            >
              Restore Database
            </button>
          )}
        </div>
      </div>
    </div>
  );
}
