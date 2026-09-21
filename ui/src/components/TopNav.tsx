import { Link, NavLink } from "react-router-dom";
import ArchonLogo from "./ArchonLogo";

export default function TopNav() {
  return (
    <header
      className="sticky top-0 z-50 h-16 flex items-center px-8 gap-10"
      style={{
        background: "rgba(17,24,39,0.92)",
        borderBottom: "1px solid #1F2D40",
        backdropFilter: "blur(16px)",
        WebkitBackdropFilter: "blur(16px)",
      }}
    >
      {/* Logo */}
      <Link to="/" className="flex items-center gap-3 shrink-0">
        <ArchonLogo size={34} />
        <div className="flex flex-col leading-tight">
          <span className="font-bold text-base tracking-tight" style={{ color: "#F1F5F9" }}>Archon</span>
          <span className="text-xs font-mono" style={{ color: "#64748B" }}>v2.0</span>
        </div>
      </Link>

      <div className="w-px h-6 shrink-0" style={{ background: "#1F2D40" }} />

      <nav className="hidden md:flex items-center gap-6 flex-1">
        <NavLink to="/docs" className={({ isActive }) =>
          `text-sm font-medium transition-colors ${isActive ? "text-[#6366F1]" : "text-[#64748B] hover:text-[#F1F5F9]"}`
        }>Docs</NavLink>
        <NavLink to="/about" className={({ isActive }) =>
          `text-sm font-medium transition-colors ${isActive ? "text-[#6366F1]" : "text-[#64748B] hover:text-[#F1F5F9]"}`
        }>About</NavLink>
      </nav>

      <div className="ml-auto">
        <Link
          to="/app"
          className="px-5 py-2 text-sm font-semibold rounded-lg transition-all duration-200 inline-block"
          style={{ background: "#6366F1", color: "white", boxShadow: "0 0 20px #6366F130" }}
          onMouseEnter={e => {
            (e.currentTarget as HTMLElement).style.background = "#818CF8";
            (e.currentTarget as HTMLElement).style.boxShadow = "0 0 30px #6366F150";
          }}
          onMouseLeave={e => {
            (e.currentTarget as HTMLElement).style.background = "#6366F1";
            (e.currentTarget as HTMLElement).style.boxShadow = "0 0 20px #6366F130";
          }}
        >
          Open Dashboard →
        </Link>
      </div>
    </header>
  );
}
