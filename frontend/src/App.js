import { NavLink, Route, Routes } from "react-router-dom";

import DashboardPage from "./pages/DashboardPage";
import CompilationPage from "./pages/CompilationPage";
import RedditDiscoveryPage from "./pages/RedditDiscoveryPage";

const navItems = [
  { to: "/", label: "Overview" },
  { to: "/reddit-discovery", label: "Reddit Discovery" },
  { to: "/compilation", label: "Compilation" },
];

function App() {
  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="brand-block">
          <span className="brand-kicker">Clipping Automation</span>
          <h1>Review-first video ops</h1>
          <p>
            A focused workflow for discovering Reddit clips and turning them into
            compilation-ready lineups.
          </p>
        </div>

        <nav className="nav-stack" aria-label="Primary navigation">
          {navItems.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              end={item.to === "/"}
              className={({ isActive }) => `nav-link${isActive ? " active" : ""}`}
            >
              {item.label}
            </NavLink>
          ))}
        </nav>

        <div className="sidebar-card">
          <span className="eyebrow">API</span>
          <p>Backend expected at `http://127.0.0.1:8000/api` unless `REACT_APP_API_URL` is set.</p>
        </div>
      </aside>

      <main className="main-panel">
        <header className="page-header">
          <div>
            <span className="eyebrow">Modern React Frontend</span>
            <h2>Reddit discovery and compilation assembly in one interface</h2>
          </div>
        </header>

        <Routes>
          <Route path="/" element={<DashboardPage />} />
          <Route path="/reddit-discovery" element={<RedditDiscoveryPage />} />
          <Route path="/compilation" element={<CompilationPage />} />
        </Routes>
      </main>
    </div>
  );
}

export default App;
