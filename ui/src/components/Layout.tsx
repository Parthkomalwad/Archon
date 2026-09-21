import { useLocation, NavLink, Outlet, Link } from "react-router-dom";
import { motion, AnimatePresence } from "framer-motion";
import ArchonLogo from "./ArchonLogo";

const navItems = [
  { to: "/app",          label: "Dashboard"  },
  { to: "/app/backups",  label: "Backups"    },
  { to: "/app/restore",  label: "Restore"    },
  { to: "/app/granular", label: "Granular"   },
  { to: "/app/logs",     label: "Logs"       },
  { to: "/app/settings", label: "Settings"   },
];

export default function Layout() {
  const location = useLocation();

  return (
    <div className="min-h-screen" style={{ background: "#0C1120" }}>
      {/* ── Navbar h-16 ── */}
      <header
        className="sticky top-0 z-50 h-16 flex items-center px-8 gap-10"
        style={{
          background: "rgba(17,24,39,0.92)",
          borderBottom: "1px solid #1F2D40",
          backdropFilter: "blur(16px)",
          WebkitBackdropFilter: "blur(16px)",
        }}
      >
        {/* Logo → links to HOME / */}
        <Link to="/" className="flex items-center gap-3 shrink-0 group">
          <ArchonLogo size={34} />
          <div className="flex flex-col leading-tight">
            <span className="font-bold text-base tracking-tight" style={{ color: "#F1F5F9" }}>
              Archon
            </span>
            <span className="text-xs font-mono" style={{ color: "#64748B" }}>v2.0</span>
          </div>
        </Link>

        {/* Divider */}
        <div className="w-px h-6 shrink-0" style={{ background: "#1F2D40" }} />

        {/* Nav links */}
        <nav className="hidden md:flex items-center gap-1 flex-1">
          {navItems.map(({ to, label }) => (
            <NavLink
              key={to}
              to={to}
              end={to === "/app"}
              className="relative px-4 py-2 text-sm font-medium rounded-lg transition-colors duration-150 outline-none"
              style={({ isActive }) => ({
                color: isActive ? "#F1F5F9" : "#64748B",
              })}
            >
              {({ isActive }) => (
                <>
                  {label}
                  {isActive && (
                    <motion.div
                      layoutId="nav-pill"
                      className="absolute inset-0 rounded-lg"
                      style={{ background: "#6366F120", border: "1px solid #6366F130" }}
                      transition={{ type: "spring", bounce: 0.2, duration: 0.4 }}
                    />
                  )}
                </>
              )}
            </NavLink>
          ))}
        </nav>

        {/* Right */}
        <div className="ml-auto flex items-center gap-4">
          <span
            className="inline-flex items-center gap-1.5 text-xs font-medium px-3 py-1.5 rounded-full"
            style={{ color: "#10B981", background: "#10B98115", border: "1px solid #10B98130" }}
          >
            <span className="w-1.5 h-1.5 rounded-full animate-pulse" style={{ background: "#10B981" }} />
            Connected
          </span>
        </div>
      </header>

      {/* ── Page content ── */}
      <main className="px-6 md:px-12 py-10 max-w-7xl mx-auto">
        <AnimatePresence mode="wait">
          <motion.div
            key={location.pathname}
            initial={{ opacity: 0, y: 14 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -8 }}
            transition={{ duration: 0.18, ease: "easeOut" }}
          >
            <Outlet />
          </motion.div>
        </AnimatePresence>
      </main>
    </div>
  );
}
