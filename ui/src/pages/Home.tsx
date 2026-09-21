import React from "react";
import { motion, useInView, useMotionValue, useSpring, useTransform } from "framer-motion";
import { useRef, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import TopNav from "../components/TopNav";
import ArchonLogo from "../components/ArchonLogo";

// ── Animated counter ──────────────────────────────────────────────────────────
function Counter({ to, suffix = "" }: { to: number; suffix?: string }) {
  const ref = useRef<HTMLSpanElement>(null);
  const inView = useInView(ref, { once: true });
  const count = useMotionValue(0);
  const spring = useSpring(count, { stiffness: 80, damping: 20 });
  const display = useTransform(spring, (v) => `${Math.round(v)}${suffix}`);

  useEffect(() => {
    if (inView) count.set(to);
  }, [inView, to, count]);

  return <motion.span ref={ref}>{display}</motion.span>;
}

// ── Typewriter ────────────────────────────────────────────────────────────────
function Typewriter({ lines }: { lines: string[] }) {
  const [displayed, setDisplayed] = useState<string[]>([]);
  const [currentLine, setCurrentLine] = useState(0);
  const [currentChar, setCurrentChar] = useState(0);

  useEffect(() => {
    if (currentLine >= lines.length) return;
    const line = lines[currentLine];
    if (currentChar < line.length) {
      const t = setTimeout(() => setCurrentChar(c => c + 1), 28);
      return () => clearTimeout(t);
    } else {
      const t = setTimeout(() => {
        setDisplayed(d => [...d, line]);
        setCurrentLine(l => l + 1);
        setCurrentChar(0);
      }, 400);
      return () => clearTimeout(t);
    }
  }, [currentLine, currentChar, lines]);

  const currentText = currentLine < lines.length ? lines[currentLine].slice(0, currentChar) : "";

  return (
    <div
      className="rounded-xl p-5 font-mono text-xs leading-6 overflow-hidden"
      style={{ background: "#0C1120", border: "1px solid #1F2D40" }}
    >
      <div className="flex items-center gap-2 mb-4 pb-3" style={{ borderBottom: "1px solid #1F2D40" }}>
        <div className="w-3 h-3 rounded-full bg-[#EF4444]" />
        <div className="w-3 h-3 rounded-full bg-[#F59E0B]" />
        <div className="w-3 h-3 rounded-full bg-[#10B981]" />
        <span className="ml-2 text-[#64748B] text-xs">archon  log stream</span>
        <span className="ml-auto text-[#10B981] text-xs">● streaming</span>
      </div>
      {displayed.map((line, i) => (
        <div key={i} className="text-[#10B981]">{line}</div>
      ))}
      {currentLine < lines.length && (
        <div className="text-[#10B981]">
          {currentText}
          <span className="animate-pulse">█</span>
        </div>
      )}
    </div>
  );
}

// ── Floating grid background ───────────────────────────────────────────────────
function GridBackground() {
  return (
    <div className="absolute inset-0 overflow-hidden pointer-events-none">
      <svg width="100%" height="100%" xmlns="http://www.w3.org/2000/svg">
        <defs>
          <pattern id="grid" width="40" height="40" patternUnits="userSpaceOnUse">
            <path d="M 40 0 L 0 0 0 40" fill="none" stroke="#1F2D40" strokeWidth="0.5" />
          </pattern>
        </defs>
        <rect width="100%" height="100%" fill="url(#grid)" />
      </svg>
      {/* Radial fade overlay */}
      <div
        className="absolute inset-0"
        style={{
          background: "radial-gradient(ellipse 80% 60% at 50% 0%, transparent 0%, #0C1120 70%)",
        }}
      />
    </div>
  );
}

// ── Feature card ──────────────────────────────────────────────────────────────
function FeatureCard({
  icon, title, desc, delay
}: { icon: React.ReactNode; title: string; desc: string; delay: number }) {
  const ref = useRef(null);
  const inView = useInView(ref, { once: true, margin: "-50px" });

  return (
    <motion.div
      ref={ref}
      initial={{ opacity: 0, y: 30 }}
      animate={inView ? { opacity: 1, y: 0 } : {}}
      transition={{ duration: 0.5, delay, ease: "easeOut" }}
      whileHover={{ borderColor: "#6366F1", y: -2 }}
      className="p-6 rounded-xl cursor-default transition-colors duration-200"
      style={{ background: "#1E293B", border: "1px solid #2D3F57" }}
    >
      <div className="mb-3 text-[#6366F1]">{icon}</div>
      <h3 className="font-semibold text-sm mb-2" style={{ color: "#F1F5F9" }}>{title}</h3>
      <p className="text-xs leading-5" style={{ color: "#64748B" }}>{desc}</p>
    </motion.div>
  );
}

// ── Stack badge ───────────────────────────────────────────────────────────────
function StackBadge({ label, color }: { label: string; color: string }) {
  return (
    <motion.span
      whileHover={{ scale: 1.05, y: -1 }}
      className="px-3 py-1.5 rounded-lg text-xs font-semibold font-mono border cursor-default"
      style={{ color, borderColor: `${color}40`, background: `${color}12` }}
    >
      {label}
    </motion.span>
  );
}

// ── Main ─────────────────────────────────────────────────────────────────────
const FEATURES = [
  {
    icon: <svg className="w-5 h-5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5"><path strokeLinecap="round" strokeLinejoin="round" d="M3.75 13.5l10.5-11.25L12 10.5h8.25L9.75 21.75 12 13.5H3.75z" /></svg>,
    title: "Scheduled Backups",
    desc: "Cron or human-readable. hourly, daily, weekly, monthly  per database. Runs silently alongside your stack.",
  },
  {
    icon: <svg className="w-5 h-5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5"><path strokeLinecap="round" strokeLinejoin="round" d="M21 21l-5.197-5.197m0 0A7.5 7.5 0 105.196 5.196a7.5 7.5 0 0010.607 10.607z" /></svg>,
    title: "Granular Restore",
    desc: "Browse tables, pick rows, resolve FK dependencies. Restore 3 rows, not the entire database.",
  },
  {
    icon: <svg className="w-5 h-5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5"><path strokeLinecap="round" strokeLinejoin="round" d="M16.5 10.5V6.75a4.5 4.5 0 10-9 0v3.75m-.75 11.25h10.5a2.25 2.25 0 002.25-2.25v-6.75a2.25 2.25 0 00-2.25-2.25H6.75a2.25 2.25 0 00-2.25 2.25v6.75a2.25 2.25 0 002.25 2.25z" /></svg>,
    title: "AES-256 Encryption",
    desc: "Every backup encrypted at rest. SHA-256 checksum sidecar on every file. Verified before restore.",
  },
  {
    icon: <svg className="w-5 h-5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5"><path strokeLinecap="round" strokeLinejoin="round" d="M20.25 6.375c0 2.278-3.694 4.125-8.25 4.125S3.75 8.653 3.75 6.375m16.5 0c0-2.278-3.694-4.125-8.25-4.125S3.75 4.097 3.75 6.375m16.5 0v11.25c0 2.278-3.694 4.125-8.25 4.125s-8.25-1.847-8.25-4.125V6.375m16.5 2.625c0 2.278-3.694 4.125-8.25 4.125s-8.25-1.847-8.25-4.125m16.5 5.625c0 2.278-3.694 4.125-8.25 4.125s-8.25-1.847-8.25-4.125" /></svg>,
    title: "Multi-Database",
    desc: "PostgreSQL, MongoDB, MySQL, SQLite. Same config format. Same pipeline. Same guarantees.",
  },
  {
    icon: <svg className="w-5 h-5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5"><path strokeLinecap="round" strokeLinejoin="round" d="M2.25 15a4.5 4.5 0 004.5 4.5H18a3.75 3.75 0 001.332-7.257 3 3 0 00-3.758-3.848 5.25 5.25 0 00-10.233 2.33A4.502 4.502 0 002.25 15z" /></svg>,
    title: "Multi-Storage",
    desc: "Local disk, AWS S3, Azure Blob. Switch backends in one line. No migration needed.",
  },
  {
    icon: <svg className="w-5 h-5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5"><path strokeLinecap="round" strokeLinejoin="round" d="M14.857 17.082a23.848 23.848 0 005.454-1.31A8.967 8.967 0 0118 9.75v-.7V9A6 6 0 006 9v.75a8.967 8.967 0 01-2.312 6.022c1.733.64 3.56 1.085 5.455 1.31m5.714 0a24.255 24.255 0 01-5.714 0m5.714 0a3 3 0 11-5.714 0" /></svg>,
    title: "Webhooks",
    desc: "HMAC-signed events on every backup and restore. Retry logic built in. Plug into Slack, PagerDuty, anything.",
  },
];

const LOG_LINES = [
  '{"event":"startup_ok","message":"Archon started. 2 database(s) configured."}',
  '{"event":"backup_started","database":"primary_postgres","rotation":"daily"}',
  '{"event":"backup_completed","database":"primary_postgres","filename":"archon_primary_postgres_2025-01-15T02-00-00_daily.sql.enc","duration_seconds":1.8}',
  '{"event":"backup_started","database":"analytics_mongo","rotation":"daily"}',
  '{"event":"backup_completed","database":"analytics_mongo","filename":"archon_analytics_mongo_2025-01-15T02-00-01_daily.archive.enc","duration_seconds":3.2}',
];

export default function Home() {
  return (
    <div style={{ background: "#0C1120", color: "#F1F5F9", minHeight: "100vh" }}>
      <TopNav />

      {/* ── Hero ── */}
      <section className="relative pt-24 pb-20 px-6 text-center overflow-hidden">
        <GridBackground />
        <div className="relative max-w-4xl mx-auto">
          {/* Logo */}
          <motion.div
            initial={{ opacity: 0, scale: 0.8 }}
            animate={{ opacity: 1, scale: 1 }}
            transition={{ duration: 0.5 }}
            className="flex justify-center mb-6"
          >
            <ArchonLogo size={64} />
          </motion.div>

          {/* Version pill */}
          <motion.div
            initial={{ opacity: 0, scale: 0.9 }}
            animate={{ opacity: 1, scale: 1 }}
            transition={{ duration: 0.4 }}
            className="inline-flex items-center gap-2 px-3 py-1 rounded-full text-xs font-semibold mb-8"
            style={{ background: "#6366F115", border: "1px solid #6366F130", color: "#818CF8" }}
          >
            <span className="w-1.5 h-1.5 rounded-full bg-[#6366F1] animate-pulse" />
            Archon v2.0  Production Ready
          </motion.div>

          {/* Headline */}
          <motion.h1
            initial={{ opacity: 0, y: 24 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.6, delay: 0.1 }}
            className="text-5xl md:text-7xl font-bold tracking-tight leading-tight mb-6"
            style={{ color: "#F1F5F9" }}
          >
            Database backup
            <br />
            <span
              style={{
                background: "linear-gradient(135deg, #6366F1 0%, #818CF8 50%, #A5B4FC 100%)",
                WebkitBackgroundClip: "text",
                WebkitTextFillColor: "transparent",
                backgroundClip: "text",
              }}
            >
              without the drama.
            </span>
          </motion.h1>

          {/* Subheadline */}
          <motion.p
            initial={{ opacity: 0, y: 16 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.5, delay: 0.25 }}
            className="text-lg max-w-2xl mx-auto mb-4 leading-relaxed"
            style={{ color: "#64748B" }}
          >
            One container. One config file. Archon runs alongside your stack as a sidecar —
            <br className="hidden md:block" />
            zero code changes, zero vendor lock-in, full control.
          </motion.p>

          {/* CTAs */}
          <motion.div
            initial={{ opacity: 0, y: 16 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.5, delay: 0.35 }}
            className="flex items-center justify-center gap-4 mb-12 flex-wrap"
          >
            <Link
              to="/app"
              className="px-6 py-3 rounded-xl text-sm font-semibold transition-all duration-200 shadow-lg"
              style={{ background: "#6366F1", color: "white", boxShadow: "0 0 30px #6366F130" }}
              onMouseEnter={e => {
                (e.currentTarget as HTMLElement).style.background = "#818CF8";
                (e.currentTarget as HTMLElement).style.boxShadow = "0 0 40px #6366F160";
              }}
              onMouseLeave={e => {
                (e.currentTarget as HTMLElement).style.background = "#6366F1";
                (e.currentTarget as HTMLElement).style.boxShadow = "0 0 30px #6366F130";
              }}
            >
              Open Dashboard →
            </Link>
            <Link
              to="/docs"
              className="px-6 py-3 rounded-xl text-sm font-semibold transition-all duration-200"
              style={{ border: "1px solid #1F2D40", color: "#64748B" }}
              onMouseEnter={e => {
                (e.currentTarget as HTMLElement).style.borderColor = "#6366F140";
                (e.currentTarget as HTMLElement).style.color = "#F1F5F9";
              }}
              onMouseLeave={e => {
                (e.currentTarget as HTMLElement).style.borderColor = "#1F2D40";
                (e.currentTarget as HTMLElement).style.color = "#64748B";
              }}
            >
              Read the Docs
            </Link>
          </motion.div>

          {/* Typewriter terminal */}
          <motion.div
            initial={{ opacity: 0, y: 24 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.6, delay: 0.5 }}
            className="max-w-2xl mx-auto text-left"
          >
            <Typewriter lines={LOG_LINES} />
          </motion.div>
        </div>
      </section>

      {/* ── Stats strip ── */}
      <motion.section
        initial={{ opacity: 0 }}
        whileInView={{ opacity: 1 }}
        viewport={{ once: true }}
        transition={{ duration: 0.5 }}
        className="py-8 px-6"
        style={{ borderTop: "1px solid #1F2D40", borderBottom: "1px solid #1F2D40", background: "rgba(30,41,59,0.5)" }}
      >
        <div className="max-w-4xl mx-auto grid grid-cols-2 md:grid-cols-4 gap-8 text-center">
          {[
            { value: 4, suffix: "", label: "Supported databases", sub: "Postgres · Mongo · MySQL · SQLite" },
            { value: 3, suffix: "", label: "Storage backends", sub: "Local · S3 · Azure" },
            { value: 256, suffix: "-bit", label: "AES encryption", sub: "SHA-256 integrity check" },
            { value: 1, suffix: "", label: "Config file", sub: "One YAML to rule them all" },
          ].map((s, i) => (
            <motion.div
              key={i}
              initial={{ opacity: 0, y: 16 }}
              whileInView={{ opacity: 1, y: 0 }}
              viewport={{ once: true }}
              transition={{ delay: i * 0.1 }}
            >
              <div className="text-3xl font-bold mb-1" style={{ color: "#6366F1" }}>
                <Counter to={s.value} suffix={s.suffix} />
              </div>
              <div className="text-sm font-semibold mb-0.5" style={{ color: "#F1F5F9" }}>{s.label}</div>
              <div className="text-xs" style={{ color: "#64748B" }}>{s.sub}</div>
            </motion.div>
          ))}
        </div>
      </motion.section>

      {/* ── Drop into any stack ── */}
      <section className="py-20 px-6">
        <div className="max-w-4xl mx-auto text-center">
          <motion.div
            initial={{ opacity: 0, y: 20 }}
            whileInView={{ opacity: 1, y: 0 }}
            viewport={{ once: true }}
            className="mb-3 text-xs uppercase tracking-widest font-semibold"
            style={{ color: "#6366F1" }}
          >
            Zero friction integration
          </motion.div>
          <motion.h2
            initial={{ opacity: 0, y: 20 }}
            whileInView={{ opacity: 1, y: 0 }}
            viewport={{ once: true }}
            transition={{ delay: 0.1 }}
            className="text-3xl md:text-4xl font-bold mb-4"
            style={{ color: "#F1F5F9" }}
          >
            Drop it into any stack.
          </motion.h2>
          <motion.p
            initial={{ opacity: 0, y: 16 }}
            whileInView={{ opacity: 1, y: 0 }}
            viewport={{ once: true }}
            transition={{ delay: 0.2 }}
            className="text-base mb-12 max-w-xl mx-auto"
            style={{ color: "#64748B" }}
          >
            Archon runs as a Docker sidecar. Zero code changes in your app.
            It runs alongside, not inside.
          </motion.p>

          <div className="space-y-6">
            {[
              {
                label: "Databases",
                badges: [
                  { label: "PostgreSQL", color: "#60A5FA" },
                  { label: "MongoDB", color: "#10B981" },
                  { label: "MySQL", color: "#F59E0B" },
                  { label: "SQLite", color: "#A78BFA" },
                ],
              },
              {
                label: "Storage",
                badges: [
                  { label: "Local Disk", color: "#64748B" },
                  { label: "AWS S3", color: "#F59E0B" },
                  { label: "Azure Blob", color: "#60A5FA" },
                ],
              },
              {
                label: "Runtime",
                badges: [
                  { label: "Docker", color: "#60A5FA" },
                  { label: "docker-compose", color: "#10B981" },
                  { label: "Any Linux", color: "#64748B" },
                ],
              },
            ].map((row, ri) => (
              <motion.div
                key={ri}
                initial={{ opacity: 0, x: -20 }}
                whileInView={{ opacity: 1, x: 0 }}
                viewport={{ once: true }}
                transition={{ delay: ri * 0.15 }}
                className="flex items-center gap-4 flex-wrap justify-center"
              >
                <span className="text-xs font-semibold w-20 text-right shrink-0" style={{ color: "#64748B" }}>
                  {row.label}
                </span>
                <div className="flex items-center gap-2 flex-wrap">
                  {row.badges.map((b) => (
                    <StackBadge key={b.label} label={b.label} color={b.color} />
                  ))}
                </div>
              </motion.div>
            ))}
          </div>
        </div>
      </section>

      {/* ── Features grid ── */}
      <section className="py-20 px-6" style={{ borderTop: "1px solid #1F2D40" }}>
        <div className="max-w-5xl mx-auto">
          <motion.div
            initial={{ opacity: 0, y: 20 }}
            whileInView={{ opacity: 1, y: 0 }}
            viewport={{ once: true }}
            className="text-center mb-12"
          >
            <div className="text-xs uppercase tracking-widest font-semibold mb-3" style={{ color: "#6366F1" }}>
              What Archon does
            </div>
            <h2 className="text-3xl md:text-4xl font-bold" style={{ color: "#F1F5F9" }}>
              Everything you need. Nothing you don't.
            </h2>
          </motion.div>
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
            {FEATURES.map((f, i) => (
              <FeatureCard key={f.title} {...f} delay={i * 0.08} />
            ))}
          </div>
        </div>
      </section>

      {/* ── How it works ── */}
      <section className="py-20 px-6" style={{ borderTop: "1px solid #1F2D40" }}>
        <div className="max-w-5xl mx-auto">
          <motion.div
            initial={{ opacity: 0, y: 20 }}
            whileInView={{ opacity: 1, y: 0 }}
            viewport={{ once: true }}
            className="text-center mb-12"
          >
            <div className="text-xs uppercase tracking-widest font-semibold mb-3" style={{ color: "#6366F1" }}>
              Setup in minutes
            </div>
            <h2 className="text-3xl md:text-4xl font-bold" style={{ color: "#F1F5F9" }}>
              How it works.
            </h2>
          </motion.div>

          <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
            {[
              {
                step: "01",
                title: "Add to docker-compose.yml",
                desc: "Drop Archon in as a sidecar service. It shares the Docker network with your app and database.",
                code: `services:
  your-app:
    image: your-app:latest

  archon:
    image: archon:latest
    volumes:
      - ./config.yaml:/app/config.yaml
      - ./backups:/app/backups
    ports:
      - "8765:8765"`,
              },
              {
                step: "02",
                title: "Write config.yaml",
                desc: "Declare databases, schedules, storage backends, and encryption in a single YAML file.",
                code: `databases:
  - name: my_postgres
    type: postgres
    host: postgres
    database: mydb
    schedule:
      frequency: daily
      at: "02:00"
      timezone: UTC`,
              },
              {
                step: "03",
                title: "You're done.",
                desc: "Archon starts, checks DB connectivity, registers cron jobs, and begins protecting your data.",
                code: `{"event":"startup_ok",
 "message":"Archon started.
  1 database configured."}

{"event":"backup_completed",
 "database":"my_postgres",
 "duration_seconds":1.8}`,
              },
            ].map((s, i) => (
              <motion.div
                key={s.step}
                initial={{ opacity: 0, y: 30 }}
                whileInView={{ opacity: 1, y: 0 }}
                viewport={{ once: true }}
                transition={{ delay: i * 0.15, duration: 0.5 }}
                className="rounded-xl p-6"
                style={{ background: "#1E293B", border: "1px solid #2D3F57" }}
              >
                <div className="text-4xl font-bold mb-3 font-mono" style={{ color: "#6366F120" }}>
                  {s.step}
                </div>
                <div
                  className="text-xs font-semibold uppercase tracking-widest mb-2"
                  style={{ color: "#6366F1" }}
                >
                  Step {s.step}
                </div>
                <h3 className="font-bold text-base mb-2" style={{ color: "#F1F5F9" }}>{s.title}</h3>
                <p className="text-xs leading-5 mb-4" style={{ color: "#64748B" }}>{s.desc}</p>
                <pre
                  className="text-xs font-mono rounded-lg p-4 leading-5 overflow-x-auto"
                  style={{ background: "#0C1120", color: "#10B981", border: "1px solid #1F2D40" }}
                >
                  {s.code}
                </pre>
              </motion.div>
            ))}
          </div>
        </div>
      </section>

      {/* ── CTA banner ── */}
      <section className="py-20 px-6" style={{ borderTop: "1px solid #1F2D40" }}>
        <motion.div
          initial={{ opacity: 0, scale: 0.97 }}
          whileInView={{ opacity: 1, scale: 1 }}
          viewport={{ once: true }}
          className="max-w-3xl mx-auto text-center rounded-2xl p-12"
          style={{
            background: "linear-gradient(135deg, #6366F115 0%, #1E293B 50%, #6366F110 100%)",
            border: "1px solid #6366F130",
          }}
        >
          <h2 className="text-3xl md:text-4xl font-bold mb-4" style={{ color: "#F1F5F9" }}>
            Your database is running in production.
            <br />
            <span style={{ color: "#6366F1" }}>Is it backed up?</span>
          </h2>
          <p className="text-base mb-8" style={{ color: "#64748B" }}>
            It takes 5 minutes to set up Archon. The next data loss incident won't.
          </p>
          <div className="flex items-center justify-center gap-4 flex-wrap">
            <Link
              to="/app"
              className="px-8 py-3 rounded-xl text-sm font-semibold"
              style={{ background: "#6366F1", color: "white", boxShadow: "0 0 40px #6366F140" }}
            >
              Open Dashboard →
            </Link>
            <Link
              to="/docs"
              className="px-8 py-3 rounded-xl text-sm font-semibold"
              style={{ border: "1px solid #1F2D40", color: "#64748B" }}
            >
              Read Docs
            </Link>
          </div>
        </motion.div>
      </section>

      {/* ── Footer ── */}
      <footer
        className="py-8 px-6"
        style={{ borderTop: "1px solid #1F2D40" }}
      >
        <div className="max-w-5xl mx-auto flex items-center justify-between flex-wrap gap-4">
          <span className="text-sm font-semibold" style={{ color: "#64748B" }}>Archon v2.0</span>
          <div className="flex items-center gap-6">
            <Link to="/app" className="text-xs transition-colors" style={{ color: "#64748B" }}
              onMouseEnter={e => (e.currentTarget.style.color = "#F1F5F9")}
              onMouseLeave={e => (e.currentTarget.style.color = "#64748B")}>Dashboard</Link>
            <Link to="/docs" className="text-xs transition-colors" style={{ color: "#64748B" }}
              onMouseEnter={e => (e.currentTarget.style.color = "#F1F5F9")}
              onMouseLeave={e => (e.currentTarget.style.color = "#64748B")}>Docs</Link>
            <Link to="/about" className="text-xs transition-colors" style={{ color: "#64748B" }}
              onMouseEnter={e => (e.currentTarget.style.color = "#F1F5F9")}
              onMouseLeave={e => (e.currentTarget.style.color = "#64748B")}>About</Link>
          </div>
          <span className="text-xs italic" style={{ color: "#64748B" }}>
            Built for engineers who take data seriously.
          </span>
        </div>
      </footer>
    </div>
  );
}
