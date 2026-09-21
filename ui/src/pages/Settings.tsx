import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { motion } from "framer-motion";
import { getStatus, getHealth, reloadConfig } from "../api/client";

// ── Helpers ───────────────────────────────────────────────────────────────────

function formatUptime(secs: number): string {
  if (secs < 60) return `${Math.floor(secs)}s`;
  if (secs < 3600) return `${Math.floor(secs / 60)}m ${Math.floor(secs % 60)}s`;
  if (secs < 86400)
    return `${Math.floor(secs / 3600)}h ${Math.floor((secs % 3600) / 60)}m`;
  return `${Math.floor(secs / 86400)}d ${Math.floor((secs % 86400) / 3600)}h`;
}

// ── Section card with glowing top border ─────────────────────────────────────

function SectionCard({
  title,
  icon,
  children,
  index = 0,
}: {
  title: string;
  icon: React.ReactNode;
  children: React.ReactNode;
  index?: number;
}) {
  return (
    <motion.div
      initial={{ opacity: 0, y: 20 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ delay: index * 0.1, duration: 0.4 }}
      className="rounded-xl overflow-hidden relative"
      style={{ background: "#1E293B", border: "1px solid #2D3F57" }}
    >
      {/* Glowing top border line */}
      <div
        className="absolute top-0 left-0 right-0 h-px"
        style={{
          background:
            "linear-gradient(90deg, transparent, #6366F130, transparent)",
        }}
      />
      {/* Header */}
      <div
        className="flex items-center gap-3 px-5 py-4"
        style={{ borderBottom: "1px solid #2D3F57" }}
      >
        <span className="text-[#6366F1]">{icon}</span>
        <h2 className="text-sm font-bold" style={{ color: "#F1F5F9" }}>
          {title}
        </h2>
      </div>
      <div className="px-5 py-5">{children}</div>
    </motion.div>
  );
}

// ── Info row ──────────────────────────────────────────────────────────────────

function InfoRow({
  label,
  value,
}: {
  label: string;
  value: React.ReactNode;
}) {
  return (
    <div
      className="flex items-center justify-between py-3"
      style={{ borderBottom: "1px solid #2D3F57" }}
    >
      <span
        className="text-sm font-medium"
        style={{ color: "#64748B" }}
      >
        {label}
      </span>
      <span className="text-sm font-semibold" style={{ color: "#F1F5F9" }}>
        {value}
      </span>
    </div>
  );
}

// ── Settings page ─────────────────────────────────────────────────────────────

export default function Settings() {
  const [reloadMsg, setReloadMsg] = useState<{
    text: string;
    ok: boolean;
  } | null>(null);
  const [copied, setCopied] = useState(false);

  const { data: status } = useQuery({
    queryKey: ["status"],
    queryFn: getStatus,
    refetchInterval: 30_000,
  });

  const { data: health } = useQuery({
    queryKey: ["health"],
    queryFn: getHealth,
    refetchInterval: 60_000,
  });

  async function handleReload() {
    try {
      const res = await reloadConfig();
      setReloadMsg({
        text: `Config reloaded  ${res.databases_registered} database(s) registered`,
        ok: true,
      });
    } catch (e: unknown) {
      setReloadMsg({
        text: e instanceof Error ? e.message : String(e),
        ok: false,
      });
    }
    setTimeout(() => setReloadMsg(null), 5000);
  }

  function handleCopy() {
    navigator.clipboard.writeText("/app/config.yaml");
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  }

  const dbCount = status?.databases.length ?? 0;

  return (
    <div className="max-w-2xl space-y-6">
      {/* Page header */}
      <div>
        <motion.h1
          initial={{ opacity: 0, y: -10 }}
          animate={{ opacity: 1, y: 0 }}
          className="text-2xl font-bold"
          style={{ color: "#F1F5F9" }}
        >
          Settings
        </motion.h1>
        <motion.p
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          transition={{ delay: 0.1 }}
          className="text-sm mt-0.5"
          style={{ color: "#64748B" }}
        >
          Service configuration and health information
        </motion.p>
      </div>

      {/* HTTP warning banner */}
      <motion.div
        initial={{ opacity: 0, x: -10 }}
        animate={{ opacity: 1, x: 0 }}
        transition={{ delay: 0.05 }}
        className="flex gap-4 items-start rounded-xl px-5 py-4 relative overflow-hidden"
        style={{
          background: "#F59E0B08",
          border: "1px solid #F59E0B25",
          borderLeft: "3px solid #F59E0B",
        }}
      >
        <div
          className="w-8 h-8 rounded-lg flex items-center justify-center shrink-0 text-[#F59E0B]"
          style={{ background: "#F59E0B15" }}
        >
          <svg className="w-4 h-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5"><path strokeLinecap="round" strokeLinejoin="round" d="M12 9v3.75m-9.303 3.376c-.866 1.5.217 3.374 1.948 3.374h14.71c1.73 0 2.813-1.874 1.948-3.374L13.949 3.378c-.866-1.5-3.032-1.5-3.898 0L2.697 16.126zM12 15.75h.007v.008H12v-.008z" /></svg>
        </div>
        <div>
          <p className="text-sm font-bold" style={{ color: "#F59E0B" }}>
            Archon is serving over HTTP
          </p>
          <p className="text-xs mt-0.5" style={{ color: "#F59E0B80" }}>
            If accessible outside your local network, use a reverse proxy
            (Nginx / Traefik) with HTTPS.
          </p>
        </div>
      </motion.div>

      {/* Config section */}
      <SectionCard icon={<svg className="w-4 h-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5"><path strokeLinecap="round" strokeLinejoin="round" d="M15.666 3.888A2.25 2.25 0 0013.5 2.25h-3c-1.03 0-1.96.693-2.166 1.638m7.332 0c.055.194.084.4.084.612v0a.75.75 0 01-.75.75H9a.75.75 0 01-.75-.75v0c0-.212.03-.418.084-.612m7.332 0c.646.049 1.288.11 1.927.184 1.1.128 1.907 1.077 1.907 2.185V19.5a2.25 2.25 0 01-2.25 2.25H6.75A2.25 2.25 0 014.5 19.5V6.262c0-1.108.806-2.057 1.907-2.185a48.208 48.208 0 011.927-.184" /></svg>} title="Configuration" index={0}>
        {/* Reload message */}
        {reloadMsg && (
          <div
            className="flex items-center gap-2 mb-5 px-4 py-3 rounded-xl text-sm font-medium border"
            style={{
              background: reloadMsg.ok ? "#10B98110" : "#EF444410",
              border: `1px solid ${reloadMsg.ok ? "#10B98130" : "#EF444430"}`,
              color: reloadMsg.ok ? "#10B981" : "#EF4444",
            }}
          >
            {reloadMsg.text}
          </div>
        )}

        <div className="space-y-0 mb-5">
          <InfoRow
            label="Databases configured"
            value={
              <span
                className="font-bold text-lg"
                style={{ color: "#6366F1" }}
              >
                {dbCount}
              </span>
            }
          />
          <div
            className="flex items-center justify-between py-3"
            style={{ borderBottom: "1px solid #2D3F57" }}
          >
            <span
              className="text-sm font-medium"
              style={{ color: "#64748B" }}
            >
              Config file
            </span>
            <div className="flex items-center gap-2">
              <span
                className="font-mono text-xs px-3 py-1.5 rounded-lg"
                style={{
                  background: "#0C1120",
                  border: "1px solid #1F2D40",
                  color: "#6366F1",
                }}
              >
                /app/config.yaml
              </span>
              <button
                onClick={handleCopy}
                className="p-1.5 rounded-lg transition-all text-xs font-semibold"
                style={{
                  background: copied ? "#10B98120" : "#253347",
                  color: copied ? "#10B981" : "#64748B",
                  border: `1px solid ${copied ? "#10B98130" : "#2D3F57"}`,
                }}
                title="Copy path"
              >
                {copied ? (
                  <svg className="w-3.5 h-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5"><path strokeLinecap="round" strokeLinejoin="round" d="M4.5 12.75l6 6 9-13.5" /></svg>
                ) : (
                  <svg className="w-3.5 h-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5"><path strokeLinecap="round" strokeLinejoin="round" d="M15.666 3.888A2.25 2.25 0 0013.5 2.25h-3c-1.03 0-1.96.693-2.166 1.638m7.332 0c.055.194.084.4.084.612v0a.75.75 0 01-.75.75H9a.75.75 0 01-.75-.75v0c0-.212.03-.418.084-.612m7.332 0c.646.049 1.288.11 1.927.184 1.1.128 1.907 1.077 1.907 2.185V19.5a2.25 2.25 0 01-2.25 2.25H6.75A2.25 2.25 0 014.5 19.5V6.262c0-1.108.806-2.057 1.907-2.185a48.208 48.208 0 011.927-.184" /></svg>
                )}
              </button>
            </div>
          </div>
        </div>

        <motion.button
          whileHover={{ scale: 1.02 }}
          whileTap={{ scale: 0.98 }}
          onClick={handleReload}
          className="inline-flex items-center gap-2 px-5 py-2.5 text-sm font-semibold rounded-xl transition-all"
          style={{
            background: "#6366F1",
            color: "white",
            boxShadow: "0 0 20px #6366F125",
          }}
        >
          <svg
            className="w-4 h-4"
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
        </motion.button>
      </SectionCard>

      {/* Health section */}
      <SectionCard icon={<svg className="w-4 h-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5"><path strokeLinecap="round" strokeLinejoin="round" d="M9 12.75L11.25 15 15 9.75m-3-7.036A11.959 11.959 0 013.598 6 11.955 11.955 0 003 9.749c0 5.592 3.824 10.29 9 11.623 5.176-1.332 9-6.03 9-11.622 0-1.31-.21-2.571-.598-3.751h-.152c-3.196 0-6.1-1.248-8.25-3.285z" /></svg>} title="Service Health" index={1}>
        {health ? (
          <div className="space-y-0">
            {/* Status indicator */}
            <div
              className="flex items-center justify-between py-4"
              style={{ borderBottom: "1px solid #2D3F57" }}
            >
              <span
                className="text-sm font-medium"
                style={{ color: "#64748B" }}
              >
                Status
              </span>
              <div className="flex items-center gap-3">
                <div
                  className="w-3 h-3 rounded-full"
                  style={{
                    background:
                      health.status === "ok" ? "#10B981" : "#EF4444",
                    boxShadow:
                      health.status === "ok"
                        ? "0 0 8px #10B981"
                        : "0 0 8px #EF4444",
                    animation: "pulse 2s infinite",
                  }}
                />
                <span
                  className="text-sm font-bold uppercase tracking-wider"
                  style={{
                    color:
                      health.status === "ok" ? "#10B981" : "#EF4444",
                  }}
                >
                  {health.status}
                </span>
              </div>
            </div>

            {/* Version */}
            <InfoRow
              label="Version"
              value={
                <span
                  className="font-mono text-xs px-3 py-1 rounded-lg"
                  style={{
                    background: "#0C1120",
                    border: "1px solid #1F2D40",
                    color: "#64748B",
                  }}
                >
                  {health.version}
                </span>
              }
            />

            {/* Uptime */}
            <div
              className="flex items-center justify-between py-3"
              style={{ borderBottom: "1px solid #2D3F57" }}
            >
              <span
                className="text-sm font-medium"
                style={{ color: "#64748B" }}
              >
                Uptime
              </span>
              <div className="flex items-center gap-3">
                <span
                  className="font-mono text-xl font-bold"
                  style={{ color: "#F1F5F9" }}
                >
                  {formatUptime(health.uptime_seconds)}
                </span>
                <div
                  className="w-8 h-8 rounded-full flex items-center justify-center"
                  style={{
                    border: "2px solid #10B98130",
                    boxShadow: "0 0 12px #10B98120",
                  }}
                >
                  <div
                    className="w-2 h-2 rounded-full"
                    style={{ background: "#10B981" }}
                  />
                </div>
              </div>
            </div>
          </div>
        ) : (
          <div
            className="flex items-center gap-2 text-sm py-2"
            style={{ color: "#64748B" }}
          >
            <span className="w-4 h-4 border-2 border-[#2D3F57] border-t-[#6366F1] rounded-full animate-spin" />
            Loading health data…
          </div>
        )}
      </SectionCard>

      {/* Databases section */}
      <SectionCard icon={<svg className="w-4 h-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5"><path strokeLinecap="round" strokeLinejoin="round" d="M20.25 6.375c0 2.278-3.694 4.125-8.25 4.125S3.75 8.653 3.75 6.375m16.5 0c0-2.278-3.694-4.125-8.25-4.125S3.75 4.097 3.75 6.375m16.5 0v11.25c0 2.278-3.694 4.125-8.25 4.125s-8.25-1.847-8.25-4.125V6.375m16.5 2.625c0 2.278-3.694 4.125-8.25 4.125s-8.25-1.847-8.25-4.125m16.5 5.625c0 2.278-3.694 4.125-8.25 4.125s-8.25-1.847-8.25-4.125" /></svg>} title="Configured Databases" index={2}>
        {status?.databases.length ? (
          <div className="space-y-3">
            {status.databases.map((db) => {
              const isHealthy = db.last_status === "completed";
              const isFailed = db.last_status === "failed";
              const accentColor = isHealthy
                ? "#10B981"
                : isFailed
                  ? "#EF4444"
                  : "#64748B";
              const statusLabel = isHealthy
                ? "healthy"
                : isFailed
                  ? "failed"
                  : db.last_status ?? "idle";

              return (
                <div
                  key={db.database}
                  className="flex items-center justify-between rounded-xl px-4 py-3.5 relative overflow-hidden"
                  style={{
                    background: "#0C1120",
                    border: "1px solid #1F2D40",
                    borderLeft: `3px solid ${accentColor}`,
                  }}
                >
                  <div className="flex items-center gap-3">
                    <span
                      className="text-sm font-bold"
                      style={{ color: "#F1F5F9" }}
                    >
                      {db.database}
                    </span>
                    {db.currently_running && (
                      <span
                        className="text-xs font-semibold px-2 py-0.5 rounded-full"
                        style={{
                          background: "#3B82F615",
                          color: "#3B82F6",
                          border: "1px solid #3B82F630",
                        }}
                      >
                        <span className="inline-block w-1.5 h-1.5 rounded-full bg-[#3B82F6] animate-pulse mr-1" />
                        running
                      </span>
                    )}
                  </div>
                  <span
                    className="inline-flex items-center gap-1.5 text-xs font-semibold px-2.5 py-1 rounded-full capitalize"
                    style={{
                      color: accentColor,
                      background: `${accentColor}15`,
                      border: `1px solid ${accentColor}30`,
                    }}
                  >
                    <span
                      className="w-1.5 h-1.5 rounded-full"
                      style={{ background: accentColor }}
                    />
                    {statusLabel}
                  </span>
                </div>
              );
            })}
          </div>
        ) : (
          <p className="text-sm" style={{ color: "#64748B" }}>
            No databases loaded.
          </p>
        )}
      </SectionCard>
    </div>
  );
}
