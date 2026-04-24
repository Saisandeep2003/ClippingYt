import { Link } from "react-router-dom";

function DashboardPage() {
  return (
    <div className="page-stack">
      <section className="hero-panel">
        <div>
          <span className="eyebrow">Workflow</span>
          <h3>Discover Reddit clips, pick 5, then shape them into a compilation</h3>
          <p>
            The app is now focused on a single fast path: tag-based Reddit discovery, duplicate
            avoidance across sessions, and a separate compilation screen for the selected lineup.
          </p>
        </div>
        <div className="action-row">
          <Link className="primary-button" to="/reddit-discovery">
            Start discovery
          </Link>
          <Link className="ghost-button" to="/compilation">
            Open compilation
          </Link>
        </div>
      </section>

      <section className="stats-grid">
        <article className="stat-card">
          <span className="eyebrow">Step 1</span>
          <strong>Discover</strong>
          <p>Search by tag and let the backend find relevant Reddit posts and related subreddits.</p>
        </article>
        <article className="stat-card">
          <span className="eyebrow">Step 2</span>
          <strong>Filter</strong>
          <p>Keep only native Reddit clips that are not marked NSFW and have not been shown before.</p>
        </article>
        <article className="stat-card">
          <span className="eyebrow">Step 3</span>
          <strong>Compile</strong>
          <p>Proceed with exactly 5 clips and assemble them in a dedicated compilation screen.</p>
        </article>
      </section>
    </div>
  );
}

export default DashboardPage;
