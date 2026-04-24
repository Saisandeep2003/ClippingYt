import StatusPill from "./StatusPill";

function formatCount(value) {
  return new Intl.NumberFormat().format(value || 0);
}

function formatCreatedAt(value) {
  if (!value) {
    return "unknown";
  }

  try {
    return new Intl.DateTimeFormat(undefined, {
      dateStyle: "medium",
      timeStyle: "short",
    }).format(new Date(value));
  } catch {
    return value;
  }
}

function DiscoveryClipCard({ clip, selectedRank, disableSelect, onToggle }) {
  const isSelected = Boolean(selectedRank);
  const canSelect = clip.compilation_ready && !disableSelect;

  return (
    <article className={`discovery-card${isSelected ? " selected" : ""}`}>
      <div className="clip-preview-frame">
        {clip.preview_kind === "video" ? (
          <video
            className="clip-preview"
            controls
            playsInline
            preload="metadata"
            poster={clip.thumbnail_url || undefined}
            src={clip.preview_url}
          />
        ) : (
          <img className="clip-preview" alt={clip.title} src={clip.thumbnail_url || clip.preview_url} />
        )}
      </div>

      <div className="candidate-card__header">
        <div>
          <span className="eyebrow">{clip.source}</span>
          <h3>{clip.title}</h3>
        </div>
        <div className="pill-row">
          {selectedRank ? <StatusPill tone="success">#{selectedRank}</StatusPill> : null}
          {clip.duration_seconds ? <StatusPill>{clip.duration_seconds}s</StatusPill> : null}
          <StatusPill>{clip.media_type.replace(/_/g, " ")}</StatusPill>
        </div>
      </div>

      <div className="candidate-meta-grid">
        <div>
          <span className="meta-label">Subreddit</span>
          <span>{clip.subreddit}</span>
        </div>
        <div>
          <span className="meta-label">Upvotes</span>
          <span>{formatCount(clip.upvotes)}</span>
        </div>
        <div>
          <span className="meta-label">Comments</span>
          <span>{formatCount(clip.comments)}</span>
        </div>
        <div>
          <span className="meta-label">Engagement</span>
          <span>{formatCount(clip.engagement)}</span>
        </div>
        <div>
          <span className="meta-label">Rank score</span>
          <span>{clip.final_score.toFixed(3)}</span>
        </div>
        <div>
          <span className="meta-label">Created</span>
          <span>{formatCreatedAt(clip.created_at)}</span>
        </div>
      </div>

      <p className="candidate-description">{clip.selection_reason}</p>

      <div className="link-row">
        <a href={clip.permalink || clip.source_url} target="_blank" rel="noreferrer">
          Reddit post
        </a>
        <a href={clip.video_url} target="_blank" rel="noreferrer">
          Media link
        </a>
      </div>

      <div className="action-row">
        <button
          className={isSelected ? "ghost-button" : "primary-button"}
          onClick={() => onToggle(clip)}
          disabled={isSelected ? false : !canSelect}
        >
          {isSelected ? "Remove selection" : clip.compilation_ready ? "Select clip" : "View only"}
        </button>
      </div>
    </article>
  );
}

export default DiscoveryClipCard;
