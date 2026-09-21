import TopNav from "../components/TopNav";
import ArchonLogo from "../components/ArchonLogo";

const IconShield = () => (
  <svg className="w-6 h-6" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.8}>
    <path strokeLinecap="round" strokeLinejoin="round"
      d="M9 12l2 2 4-4m5.618-4.016A11.955 11.955 0 0112 2.944a11.955 11.955 0 01-8.618 3.04A12.02 12.02 0 003 9c0 5.591 3.824 10.29 9 11.622 5.176-1.332 9-6.03 9-11.622 0-1.042-.133-2.052-.382-3.016z" />
  </svg>
);

const IconDatabase = () => (
  <svg className="w-6 h-6" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.8}>
    <ellipse cx="12" cy="5" rx="9" ry="3" strokeLinejoin="round" />
    <path strokeLinecap="round" strokeLinejoin="round" d="M21 5v6c0 1.66-4.03 3-9 3S3 12.66 3 11V5" />
    <path strokeLinecap="round" strokeLinejoin="round" d="M21 11v8c0 1.66-4.03 3-9 3s-9-1.34-9-3v-8" />
  </svg>
);

const IconZap = () => (
  <svg className="w-6 h-6" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.8}>
    <path strokeLinecap="round" strokeLinejoin="round" d="M13 2L3 14h9l-1 8 10-12h-9l1-8z" />
  </svg>
);

const IconLayers = () => (
  <svg className="w-6 h-6" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.8}>
    <path strokeLinecap="round" strokeLinejoin="round" d="M12 2L2 7l10 5 10-5-10-5zM2 17l10 5 10-5M2 12l10 5 10-5" />
  </svg>
);

const principles = [
  {
    icon: <IconShield />,
    title: "Encrypted by Default",
    body: "AES-256 on every backup. SHA-256 on every restore. Trust nothing, verify everything.",
  },
  {
    icon: <IconDatabase />,
    title: "Your Data Stays Yours",
    body: "No telemetry. No cloud dependencies unless you choose them. Your backups, your storage.",
  },
  {
    icon: <IconZap />,
    title: "Zero Configuration Drift",
    body: "One YAML file drives everything. Scheduling, retention, encryption  all declarative.",
  },
  {
    icon: <IconLayers />,
    title: "Granular, Not Blunt",
    body: "Don't restore an entire database when you only need three rows. Surgical precision.",
  },
];

export default function About() {
  return (
    <div className="min-h-screen" style={{ background: "#0C1120" }}>
      <TopNav />
      {/* ── Hero ── */}
      <div className="max-w-3xl mx-auto px-6 pt-20 pb-16 text-center">
        <div className="flex justify-center mb-6">
          <ArchonLogo size={56} />
        </div>
        <p className="text-xs font-bold tracking-widest uppercase text-[#6366F1] mb-6">
          About Archon
        </p>
        <h1 className="text-5xl sm:text-6xl font-bold text-[#F1F5F9] leading-tight mb-6">
          Engineered in the Dark.<br />
          Runs in Production.
        </h1>
        <p className="text-lg text-[#64748B] max-w-xl mx-auto leading-relaxed">
          Archon was built for engineers who treat their data seriously.
          No SaaS. No subscriptions. No vendor lock-in.
          One config file. One container. Total control.
        </p>
      </div>

      {/* ── Divider ── */}
      <div className="max-w-3xl mx-auto px-6">
        <div className="h-px bg-[#1F2D40]" />
      </div>

      {/* ── Principles ── */}
      <div className="max-w-4xl mx-auto px-6 py-16">
        <p className="text-xs font-bold tracking-widest uppercase text-[#64748B] text-center mb-10">
          Principles
        </p>
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-5">
          {principles.map((p) => (
            <div
              key={p.title}
              className="group bg-[#1E293B] border border-[#2D3F57] rounded-2xl p-6 hover:border-[#6366F1] transition-all duration-200"
            >
              <div className="w-12 h-12 rounded-xl bg-[#6366F1]/10 text-[#6366F1] flex items-center justify-center mb-4 group-hover:bg-[#6366F1]/20 transition-colors">
                {p.icon}
              </div>
              <h3 className="text-base font-bold text-[#F1F5F9] mb-2">{p.title}</h3>
              <p className="text-sm text-[#64748B] leading-relaxed">{p.body}</p>
            </div>
          ))}
        </div>
      </div>

      {/* ── Divider ── */}
      <div className="max-w-3xl mx-auto px-6">
        <div className="h-px bg-[#1F2D40]" />
      </div>

      {/* ── On Identity ── */}
      <div className="max-w-2xl mx-auto px-6 py-20 text-center">
        <p className="text-xs font-bold tracking-widest uppercase text-[#64748B] mb-8">
          On Identity
        </p>
        <div className="border-l-2 border-[#6366F1] pl-6 text-left">
          <p className="text-lg text-[#F1F5F9] font-light leading-relaxed italic">
            "Good tools don't need a byline.
            They speak through uptime, not authorship.
            The work outlasts the name."
          </p>
        </div>
      </div>

      {/* ── Tech stack brief ── */}
      <div className="max-w-3xl mx-auto px-6 pb-16">
        <div className="h-px bg-[#1F2D40] mb-12" />
        <div className="flex flex-wrap gap-2 justify-center">
          {["Python 3.11", "FastAPI", "APScheduler", "AES-256-CBC", "SHA-256", "PostgreSQL", "MongoDB", "SQLite", "S3", "Azure Blob", "Docker"].map((tag) => (
            <span
              key={tag}
              className="text-xs font-medium text-[#64748B] bg-[#1E293B] border border-[#2D3F57] px-3 py-1.5 rounded-lg"
            >
              {tag}
            </span>
          ))}
        </div>
      </div>

    </div>
  );
}
