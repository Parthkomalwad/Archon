import { useEffect, useRef, useState } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { getLogs, streamLogs, type LogEntry } from "../api/client";

// ── Level config ──────────────────────────────────────────────────────────────

const LEVEL_CONFIG: Record<
  string,
  { color: string; bg: string; border: string; rowBg: string }
> = {
  INFO: {
    color: "#10B981",
    bg: "#10B98115",
    border: "#10B98130",
    rowBg: "transparent",
  },
  WARNING: {
    color: "#F59E0B",
    bg: "#F59E0B15",
    border: "#F59E0B30",
    rowBg: "#F59E0B05",
  },
  ERROR: {
    color: "#EF4444",
    bg: "#EF444415",
    border: "#EF444430",
    rowBg: "#EF444408",
  },
  DEBUG: {
    color: "#64748B",
    bg: "#64748B15",
    border: "#64748B30",
    rowBg: "transparent",
  },
};

function getLevel(cfg: (typeof LEVEL_CONFIG)[string] | undefined) {
  return (
    cfg ?? {
      color: "#64748B",
      bg: "#64748B15",
      border: "#64748B30",
      rowBg: "transparent",
    }
  );
}

// ── Log line ──────────────────────────────────────────────────────────────────

function LogLine({
  entry,
  lineNum,
  isNew,
}: {
  entry: LogEntry;
  lineNum: number;
  isNew: boolean;
}) {
  const lvl = getLevel(LEVEL_CONFIG[entry.level]);

  return (
    <motion.div
      initial={isNew ? { opacity: 0, y: -8, backgroundColor: "#6366F110" } : false}
      animate={{ opacity: 1, y: 0, backgroundColor: lvl.rowBg }}
      transition={{ duration: 0.25 }}
      className="flex items-start gap-0 group hover:bg-white/[0.025] transition-colors duration-75"
      style={{ borderBottom: "1px solid #ffffff05" }}
    >
      {/* Line number */}
      <span
        className="shrink-0 w-12 text-right pr-4 pt-2 text-xs font-mono select-none"
        style={{ color: "#2d3748" }}
      >
        {lineNum}
      </span>

      {/* Timestamp */}
      <span
        className="shrink-0 w-20 pt-2 text-xs font-mono select-none"
        style={{ color: "#374151" }}
      >
        {entry.timestamp.slice(11, 19)}
      </span>

      {/* Level badge */}
      <span className="shrink-0 pt-1.5 mr-3">
        <span
          className="inline-block px-1.5 py-0.5 rounded text-xs font-bold font-mono w-16 text-center"
          style={{ color: lvl.color, background: lvl.bg, border: `1px solid ${lvl.border}` }}
        >
          {entry.level.slice(0, 4)}
        </span>
      </span>

      {/* Event */}
      <span
        className="shrink-0 w-32 pt-2 text-xs font-mono truncate"
        style={{ color: "#6366F1" }}
        title={entry.event}
      >
        {entry.event}
      </span>

      {/* Database */}
      {entry.database && (
        <span
          className="shrink-0 w-24 pt-2 text-xs font-mono truncate mr-2"
          style={{ color: "#10B981" }}
          title={String(entry.database)}
        >
          {entry.database}
        </span>
      )}
      {!entry.database && <span className="shrink-0 w-24 mr-2" />}

      {/* Message */}
      <span
        className="flex-1 pt-2 pb-2 text-xs font-mono truncate"
        style={{ color: "#94a3b8" }}
        title={entry.message}
      >
        {entry.message}
      </span>

      {/* Error */}
      {entry.error && (
        <span
          className="shrink-0 pt-2 pb-2 ml-2 text-xs font-mono truncate max-w-[180px]"
          style={{ color: "#EF4444" }}
          title={String(entry.error)}
        >
          {entry.error}
        </span>
      )}
    </motion.div>
  );
}

// ── Main ──────────────────────────────────────────────────────────────────────

export default function Logs() {
  const [entries, setEntries] = useState<LogEntry[]>([]);
  const [filterLevel, setFilterLevel] = useState("");
  const [paused, setPaused] = useState(false);
  const [autoScroll, setAutoScroll] = useState(true);
  const [newCount, setNewCount] = useState(0);

  const bottomRef = useRef<HTMLDivElement>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const esRef = useRef<EventSource | null>(null);
  const seenIds = useRef<Set<string>>(new Set());
  const newEntryKeys = useRef<Set<string>>(new Set());

  // Load historical logs
  useEffect(() => {
    seenIds.current.clear();
    newEntryKeys.current.clear();
    getLogs(200, filterLevel || undefined)
      .then((res) => {
        setEntries(res.entries);
        res.entries.forEach((e) =>
          seenIds.current.add(`${e.timestamp}|${e.event}|${e.message}`)
        );
      })
      .catch(() => {
        /* no persistence  start empty */
      });
  }, [filterLevel]);

  // Live SSE stream
  useEffect(() => {
    if (paused) {
      esRef.current?.close();
      esRef.current = null;
      return;
    }
    const es = streamLogs(filterLevel || undefined);
    esRef.current = es;
    es.onmessage = (ev) => {
      try {
        const entry = JSON.parse(ev.data) as LogEntry;
        const key = `${entry.timestamp}|${entry.event}|${entry.message}`;
        if (seenIds.current.has(key)) return;
        seenIds.current.add(key);
        newEntryKeys.current.add(key);
        setEntries((prev) => [...prev.slice(-999), entry]);
        setNewCount((c) => c + 1);
        // Clear "new" marker after animation
        setTimeout(() => {
          newEntryKeys.current.delete(key);
        }, 1000);
      } catch {
        /* ignore malformed */
      }
    };
    return () => {
      es.close();
      esRef.current = null;
    };
  }, [filterLevel, paused]);

  // Auto-scroll
  useEffect(() => {
    if (autoScroll) {
      bottomRef.current?.scrollIntoView({ behavior: "smooth" });
      setNewCount(0);
    }
  }, [entries, autoScroll]);

  function handleScroll() {
    const el = containerRef.current;
    if (!el) return;
    const atBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 60;
    setAutoScroll(atBottom);
    if (atBottom) setNewCount(0);
  }

  const levelCounts: Record<string, number> = {};
  for (const e of entries) {
    levelCounts[e.level] = (levelCounts[e.level] ?? 0) + 1;
  }

  return (
    <motion.div
      initial={{ opacity: 0, y: 16 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.3, ease: "easeOut" }}
      className="flex flex-col gap-4"
      style={{ height: "calc(100vh - 120px)" }}
    >
      {/* Outer terminal window */}
      <div
        className="flex flex-col flex-1 rounded-xl overflow-hidden"
        style={{
          background: "#0C1120",
          border: "1px solid #1F2D40",
          boxShadow: "0 0 40px #6366F108",
        }}
      >
        {/* Terminal toolbar */}
        <div
          className="flex items-center gap-3 px-4 py-3 shrink-0"
          style={{
            background: "#111827",
            borderBottom: "1px solid #1F2D40",
          }}
        >
          {/* Traffic lights */}
          <div className="flex items-center gap-1.5 shrink-0">
            <div
              className="w-3 h-3 rounded-full"
              style={{ background: "#EF444480" }}
            />
            <div
              className="w-3 h-3 rounded-full"
              style={{ background: "#F59E0B80" }}
            />
            <div
              className="w-3 h-3 rounded-full"
              style={{ background: "#10B98180" }}
            />
          </div>

          {/* Title */}
          <span
            className="text-xs font-mono ml-2 flex-1"
            style={{ color: "#64748B" }}
          >
            archon  log stream
          </span>

          {/* Level filter */}
          <select
            value={filterLevel}
            onChange={(e) => setFilterLevel(e.target.value)}
            className="text-xs font-mono rounded-md px-2 py-1 outline-none appearance-none cursor-pointer"
            style={{
              background: "#1F2D40",
              border: "1px solid #2D3F57",
              color: "#64748B",
            }}
          >
            <option value="">all levels</option>
            <option value="INFO">INFO</option>
            <option value="WARNING">WARN</option>
            <option value="ERROR">ERROR</option>
            <option value="DEBUG">DEBUG</option>
          </select>

          {/* Entry count + level pills */}
          <div className="flex items-center gap-2">
            {Object.entries(levelCounts).map(([level, count]) => {
              const c = getLevel(LEVEL_CONFIG[level]);
              return (
                <span
                  key={level}
                  className="text-xs font-mono px-1.5 py-0.5 rounded"
                  style={{ color: c.color, background: c.bg }}
                >
                  {level.slice(0, 1)}:{count}
                </span>
              );
            })}
            <span
              className="text-xs font-mono"
              style={{ color: "#2d3748" }}
            >
              {entries.length} lines
            </span>
          </div>

          {/* Pause/Resume */}
          <button
            onClick={() => setPaused((p) => !p)}
            className="flex items-center gap-1.5 px-3 py-1 rounded-md text-xs font-semibold font-mono transition-all"
            style={{
              background: paused ? "#10B98120" : "#1F2D40",
              color: paused ? "#10B981" : "#64748B",
              border: `1px solid ${paused ? "#10B98130" : "#2D3F57"}`,
            }}
          >
            {paused ? "▶ resume" : "⏸ pause"}
          </button>

          {/* Live indicator */}
          <AnimatePresence>
            {!paused && (
              <motion.span
                initial={{ opacity: 0, scale: 0.8 }}
                animate={{ opacity: 1, scale: 1 }}
                exit={{ opacity: 0, scale: 0.8 }}
                className="flex items-center gap-1.5 text-xs font-mono"
                style={{ color: "#10B981" }}
              >
                <span
                  className="w-1.5 h-1.5 rounded-full bg-[#10B981] animate-pulse"
                />
                live
              </motion.span>
            )}
            {paused && (
              <motion.span
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
                exit={{ opacity: 0 }}
                className="text-xs font-mono"
                style={{ color: "#F59E0B" }}
              >
                paused
              </motion.span>
            )}
          </AnimatePresence>
        </div>

        {/* Column headers */}
        <div
          className="flex items-center gap-0 px-0 py-1 shrink-0 select-none"
          style={{
            background: "#080b14",
            borderBottom: "1px solid #0d1220",
          }}
        >
          <span
            className="w-12 text-right pr-4 text-xs font-mono"
            style={{ color: "#1e2535" }}
          >
            #
          </span>
          <span
            className="w-20 text-xs font-mono"
            style={{ color: "#1e2535" }}
          >
            time
          </span>
          <span
            className="w-20 mr-3 text-xs font-mono"
            style={{ color: "#1e2535" }}
          >
            level
          </span>
          <span
            className="w-32 text-xs font-mono"
            style={{ color: "#1e2535" }}
          >
            event
          </span>
          <span
            className="w-24 mr-2 text-xs font-mono"
            style={{ color: "#1e2535" }}
          >
            database
          </span>
          <span className="flex-1 text-xs font-mono" style={{ color: "#1e2535" }}>
            message
          </span>
        </div>

        {/* Log lines */}
        <div
          ref={containerRef}
          onScroll={handleScroll}
          className="flex-1 overflow-y-auto scrollbar-thin"
          style={{ scrollbarColor: "#1F2D40 transparent" }}
        >
          {entries.length === 0 ? (
            <div className="flex flex-col items-center justify-center h-full gap-3">
              <span className="text-[#2D3F57]"><svg className="w-8 h-8" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5"><path strokeLinecap="round" strokeLinejoin="round" d="M9.348 14.651a3.75 3.75 0 010-5.303m5.304 0a3.75 3.75 0 010 5.303m-7.425 2.122a6.75 6.75 0 010-9.546m9.546 0a6.75 6.75 0 010 9.546M5.106 18.894c-3.808-3.808-3.808-9.98 0-13.789m13.788 0c3.808 3.808 3.808 9.981 0 13.79M12 12h.008v.007H12V12zm.375 0a.375.375 0 11-.75 0 .375.375 0 01.75 0z" /></svg></span>
              <p className="text-sm font-mono" style={{ color: "#2d3748" }}>
                {paused
                  ? "paused  no entries loaded"
                  : "waiting for log events…"}
              </p>
            </div>
          ) : (
            entries.map((entry, i) => {
              const key = `${entry.timestamp}|${entry.event}|${entry.message}`;
              return (
                <LogLine
                  key={`${key}-${i}`}
                  entry={entry}
                  lineNum={i + 1}
                  isNew={newEntryKeys.current.has(key)}
                />
              );
            })
          )}
          <div ref={bottomRef} />
        </div>
      </div>

      {/* Jump to bottom */}
      <AnimatePresence>
        {!autoScroll && (
          <motion.button
            initial={{ opacity: 0, y: 8 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: 8 }}
            onClick={() => {
              setAutoScroll(true);
              setNewCount(0);
              bottomRef.current?.scrollIntoView({ behavior: "smooth" });
            }}
            className="w-fit mx-auto flex items-center gap-2 px-4 py-2 rounded-xl text-xs font-semibold font-mono transition-all"
            style={{
              background: "#6366F115",
              border: "1px solid #6366F130",
              color: "#6366F1",
              boxShadow: "0 0 16px #6366F115",
            }}
          >
            ↓ jump to latest
            {newCount > 0 && (
              <span
                className="px-1.5 py-0.5 rounded-full text-xs font-bold"
                style={{ background: "#6366F1", color: "white" }}
              >
                {newCount}
              </span>
            )}
          </motion.button>
        )}
      </AnimatePresence>
    </motion.div>
  );
}
