import { useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";

import DiscoveryClipCard from "../components/DiscoveryClipCard";
import EmptyState from "../components/EmptyState";
import LoadingState from "../components/LoadingState";
import { discoverRedditClips } from "../services/api";

const initialFormState = {
  tags: "funny, animal, fail",
  subreddits: "",
  max_results: 12,
  sort_mode: "relevance",
  time_filter: "week",
  allow_nsfw: false,
  include_external_media: false,
};
const STORAGE_KEY = "clipping-automation:selected-clips";

function parseList(value) {
  return value
    .split(",")
    .map((entry) => entry.trim())
    .filter(Boolean);
}

function emptyResults() {
  return {
    items: [],
    total_safe: 0,
    total_results: 0,
    checked_count: 0,
    rejected_count: 0,
    cached_count: 0,
    searched_subreddits: [],
    page: 1,
    page_size: 0,
    has_more: false,
    next_page: null,
    sort_mode: "relevance",
    time_filter: "week",
    source_mode: "public",
    warnings: [],
  };
}

function mergeResults(current, next) {
  if (next.page <= 1) {
    return next;
  }

  return {
    ...next,
    items: [...current.items, ...next.items],
    total_safe: current.items.length + next.items.length,
    warnings: Array.from(new Set([...(current.warnings || []), ...(next.warnings || [])])),
  };
}

function RedditDiscoveryPage() {
  const navigate = useNavigate();
  const [formState, setFormState] = useState(initialFormState);
  const [results, setResults] = useState(emptyResults);
  const [selectedIds, setSelectedIds] = useState([]);
  const [loading, setLoading] = useState(false);
  const [loadingMore, setLoadingMore] = useState(false);
  const [error, setError] = useState("");
  const [activeQuery, setActiveQuery] = useState(null);

  const selectedClips = useMemo(
    () =>
      selectedIds
        .map((externalId) => results.items.find((clip) => clip.external_id === externalId))
        .filter(Boolean),
    [results.items, selectedIds]
  );

  const selectionOutput = useMemo(() => {
    if (selectedClips.length !== 5) {
      return null;
    }

    return {
      tags: parseList(formState.tags),
      subreddits: results.searched_subreddits,
      selected_clips: selectedClips.map((clip, index) => ({
        external_id: clip.external_id,
        url: clip.video_url,
        title: clip.title,
        source: clip.source,
        rank: index + 1,
        subreddit: clip.subreddit,
        duration_seconds: clip.duration_seconds,
      })),
    };
  }, [formState.tags, results.searched_subreddits, selectedClips]);

  function buildRequest(page = 1) {
    return {
      tags: parseList(formState.tags),
      subreddits: parseList(formState.subreddits).length ? parseList(formState.subreddits) : null,
      max_results: Number(formState.max_results),
      page,
      sort_mode: formState.sort_mode,
      time_filter: formState.time_filter,
      allow_nsfw: Boolean(formState.allow_nsfw),
      include_external_media: Boolean(formState.include_external_media),
    };
  }

  function handleChange(event) {
    const { name, value, type, checked } = event.target;
    setFormState((current) => ({
      ...current,
      [name]: type === "checkbox" ? checked : name === "max_results" ? Number(value) : value,
    }));
  }

  async function handleSubmit(event) {
    event.preventDefault();
    const requestPayload = buildRequest(1);
    setLoading(true);
    setError("");
    setSelectedIds([]);

    try {
      const data = await discoverRedditClips(requestPayload);
      setResults(data);
      setActiveQuery(requestPayload);
    } catch (err) {
      setResults(emptyResults());
      setError(err.response?.data?.detail || "Unable to discover Reddit clips right now.");
    } finally {
      setLoading(false);
    }
  }

  async function handleLoadMore() {
    if (!activeQuery || !results.next_page) {
      return;
    }

    setLoadingMore(true);
    setError("");

    try {
      const data = await discoverRedditClips({
        ...activeQuery,
        page: results.next_page,
      });
      setResults((current) => mergeResults(current, data));
    } catch (err) {
      setError(err.response?.data?.detail || "Unable to load more Reddit clips right now.");
    } finally {
      setLoadingMore(false);
    }
  }

  function handleToggleClip(clip) {
    if (!clip.compilation_ready) {
      return;
    }

    setSelectedIds((current) => {
      if (current.includes(clip.external_id)) {
        return current.filter((externalId) => externalId !== clip.external_id);
      }

      if (current.length >= 5) {
        return current;
      }

      return [...current, clip.external_id];
    });
  }

  function handleProceed() {
    if (!selectionOutput) {
      return;
    }

    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(selectionOutput));
    navigate("/compilation");
  }

  return (
    <div className="page-stack">
      <section className="feature-panel hero-panel">
        <div className="panel-heading">
          <div>
            <span className="eyebrow">Reddit Discovery</span>
            <h3>Search tags, discover subreddits, then rank the best Reddit clips</h3>
            <p>
              Enter one or more tags and the app will find related subreddits, fetch media-rich
              posts, rank them using relevance, upvotes, comments, and recency, then let you load
              more or pick five compilation-ready clips.
            </p>
          </div>
        </div>

        <form className="modal-form" onSubmit={handleSubmit}>
          <div className="form-grid">
            <label>
              Search tags
              <input
                name="tags"
                value={formState.tags}
                onChange={handleChange}
                placeholder="funny, cat, wholesome"
                required
              />
            </label>
            <label>
              Subreddits (optional)
              <input
                name="subreddits"
                value={formState.subreddits}
                onChange={handleChange}
                placeholder="Leave blank to auto-discover from tags"
              />
            </label>
            <label>
              Page size
              <input
                name="max_results"
                type="number"
                min="1"
                max="50"
                value={formState.max_results}
                onChange={handleChange}
              />
            </label>
            <label>
              Sort mode
              <select name="sort_mode" value={formState.sort_mode} onChange={handleChange}>
                <option value="relevance">Relevance</option>
                <option value="top">Top</option>
                <option value="hot">Hot</option>
                <option value="new">New</option>
                <option value="rising">Rising</option>
              </select>
            </label>
            <label>
              Time filter
              <select name="time_filter" value={formState.time_filter} onChange={handleChange}>
                <option value="day">Day</option>
                <option value="week">Week</option>
                <option value="month">Month</option>
                <option value="year">Year</option>
                <option value="all">All time</option>
              </select>
            </label>
          </div>

          <div className="action-row">
            <label className="checkbox-row">
              <input
                name="allow_nsfw"
                type="checkbox"
                checked={formState.allow_nsfw}
                onChange={handleChange}
              />
              Include NSFW results
            </label>
            <label className="checkbox-row">
              <input
                name="include_external_media"
                type="checkbox"
                checked={formState.include_external_media}
                onChange={handleChange}
              />
              Include external media links
            </label>
          </div>

          <div className="action-row">
            <button className="primary-button" type="submit" disabled={loading}>
              {loading ? "Searching..." : "Discover clips"}
            </button>
          </div>
        </form>
      </section>

      {error ? <EmptyState title="Discovery blocked" message={error} /> : null}

      {loading ? (
        <LoadingState message="Discovering subreddits, fetching media posts, and ranking results..." />
      ) : (
        <>
          <section className="feature-panel">
            <div className="panel-heading">
              <div>
                <span className="eyebrow">Selection</span>
                <h3>Choose exactly 5 compilation-ready clips</h3>
                <p>
                  Only compilation-ready clips can be selected. External media entries can still be
                  reviewed from the results list when enabled.
                </p>
                {results.searched_subreddits?.length ? (
                  <p className="helper-text">
                    Searching in: {results.searched_subreddits.map((subreddit) => `r/${subreddit}`).join(", ")}
                  </p>
                ) : null}
                {results.warnings?.length ? (
                  <div className="warning-list">
                    {results.warnings.map((warning) => (
                      <p className="helper-text" key={warning}>
                        {warning}
                      </p>
                    ))}
                  </div>
                ) : null}
              </div>
              <div className="selection-meter">
                <strong>{selectedClips.length}/5 selected</strong>
                <span>
                  {selectedClips.length === 5
                    ? "Selection locked. Remove one to swap."
                    : `${5 - selectedClips.length} slots remaining`}
                </span>
              </div>
            </div>

            {selectionOutput ? (
              <div className="output-panel">
                <span className="eyebrow">Ready to compile</span>
                <p className="helper-text">
                  Your 5 clips are locked. Proceed to the separate compilation screen to tailor the lineup.
                </p>
                <div className="action-row">
                  <button className="primary-button" type="button" onClick={handleProceed}>
                    Proceed to compilation
                  </button>
                </div>
              </div>
            ) : (
              <p className="helper-text">Select five compilation-ready clips to continue.</p>
            )}
          </section>

          {results.items.length === 0 ? (
            <EmptyState
              title="No clips found"
              message="Try broader tags, a different sort mode, or different subreddits."
            />
          ) : (
            <>
              <section className="panel-inline-summary">
                <div>
                  <span className="eyebrow">Discovery results</span>
                  <strong>
                    Loaded {results.items.length} of {results.total_results} ranked clips
                  </strong>
                  <p className="helper-text">
                    Source mode: {results.source_mode} · sort: {results.sort_mode} · time: {results.time_filter}
                  </p>
                </div>
                <div className="pill-row">
                  <span className="status-pill">{results.checked_count} checked</span>
                  <span className="status-pill danger">{results.rejected_count} filtered</span>
                </div>
              </section>

              <section className="results-grid" aria-live="polite">
                {results.items.map((clip) => {
                  const selectedRank = selectedIds.indexOf(clip.external_id) + 1;
                  return (
                    <DiscoveryClipCard
                      key={clip.external_id}
                      clip={clip}
                      selectedRank={selectedRank || null}
                      disableSelect={selectedIds.length >= 5 && !selectedRank}
                      onToggle={handleToggleClip}
                    />
                  );
                })}
              </section>

              {results.has_more ? (
                <section className="feature-panel">
                  <div className="action-row">
                    <button className="ghost-button" type="button" onClick={handleLoadMore} disabled={loadingMore}>
                      {loadingMore ? "Loading..." : "Load more"}
                    </button>
                  </div>
                </section>
              ) : null}
            </>
          )}
        </>
      )}
    </div>
  );
}

export default RedditDiscoveryPage;
