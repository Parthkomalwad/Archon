import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom";
import Layout from "./components/Layout";
import Dashboard from "./pages/Dashboard";
import Backups from "./pages/Backups";
import Logs from "./pages/Logs";
import Settings from "./pages/Settings";
import RestoreWizard from "./pages/RestoreWizard";
import About from "./pages/About";
import Home from "./pages/Home";
import Docs from "./pages/Docs";

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        {/* Public routes  use TopNav (embedded in each page) */}
        <Route path="/" element={<Home />} />
        <Route path="/docs" element={<Docs />} />
        <Route path="/about" element={<About />} />

        {/* App routes  use sidebar Layout */}
        <Route path="/app" element={<Layout />}>
          <Route index element={<Dashboard />} />
          <Route path="backups" element={<Backups />} />
          <Route path="restore" element={<RestoreWizard />} />
          <Route path="restore/:filename" element={<RestoreWizard />} />
          <Route path="granular" element={<Backups />} />
          <Route path="logs" element={<Logs />} />
          <Route path="settings" element={<Settings />} />
        </Route>

        {/* Fallback */}
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </BrowserRouter>
  );
}
