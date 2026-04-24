import { useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";

import DiscoveryClipCard from "../components/DiscoveryClipCard";
import EmptyState from "../components/EmptyState";
import LoadingState from "../components/LoadingState";
import { discoverRedditClips, listRedditTopicMarkers } from "../services/api";
import { readUsedClipIds } from "../utils/usedClips";

const initialFormState = {
  topic_markers: [],
  max_results: 12,
};
const STORAGE_KEY = "clipping-automation:selected-clips";

function emptyResults() {
  return {
    items: [],
    total_safe: 0,
    total_results: 0,
    searched_subreddits: [],
    page: 1,
    page_size: 0,
    has_more: false,
    next_page: null,
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
  const [topicOptions, setTopicOptions] = useState([]);
  const [topicLoadError, setTopicLoadError] = useState("");
  const [usedClipIds, setUsedClipIds] = useState(() => readUsedClipIds());
  const [loading, setLoading] = useState(false);
  const [loadingMore, setLoadingMore] = useState(false);
  const [error, setError] = useState("");
  const [activeQuery, setActiveQuery] = useState(null);
  const [activeTopicFilter, setActiveTopicFilter] = useState("all");

  const usedClipLookup = useMemo(() => new Set(usedClipIds), [usedClipIds]);
  const selectedTopicOptions = useMemo(
    () => topicOptions.filter((option) => formState.topic_markers.includes(option.key)),
    [formState.topic_markers, topicOptions]
  );
  const discoveryItems = useMemo(
    () => results.items.filter((clip) => !usedClipLookup.has(String(clip.external_id || "").toLowerCase())),
    [results.items, usedClipLookup]
  );
  const filteredItems = useMemo(() => {
    if (activeTopicFilter === "all") {
      return discoveryItems;
    }
    return discoveryItems.filter((clip) => (clip.topic_markers || []).includes(activeTopicFilter));
  }, [activeTopicFilter, discoveryItems]);
  const resultTopicOptions = useMemo(() => {
    const keys = new Set();
    discoveryItems.forEach((clip) => {
      (clip.topic_markers || []).forEach((marker) => keys.add(marker));
    });
    return topicOptions.filter((option) => keys.has(option.key));
  }, [discoveryItems, topicOptions]);

  useEffect(() => {
    let ignore = false;

    async function loadTopicOptions() {
      try {
        const data = await listRedditTopicMarkers();
        if (ignore) {
          return;
        }
        setTopicOptions(data.items || []);
        setTopicLoadError("");
      } catch (err) {
        if (ignore) {
          return;
        }
        setTopicOptions([]);
        setTopicLoadError(err.response?.data?.detail || "Unable to load topic markers right now.");
      }
    }

    loadTopicOptions();

    return () => {
      ignore = true;
    };
  }, []);

  useEffect(() => {
    function syncUsedClips() {
      setUsedClipIds(readUsedClipIds());
    }

    window.addEventListener("focus", syncUsedClips);
    window.addEventListener("storage", syncUsedClips);

    return () => {
      window.removeEventListener("focus", syncUsedClips);
      window.removeEventListener("storage", syncUsedClips);
    };
  }, []);

  const selectedClips = useMemo(
    () =>
      selectedIds
        .map((externalId) => discoveryItems.find((clip) => clip.external_id === externalId))
        .filter(Boolean),
    [discoveryItems, selectedIds]
  );

  const selectionOutput = useMemo(() => {
    if (selectedClips.length !== 5) {
      return null;
    }

    return {
      topic_markers: formState.topic_markers,
      tags: selectedTopicOptions.map((topic) => topic.label),
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
  }, [formState.topic_markers, results.searched_subreddits, selectedClips, selectedTopicOptions]);

  function buildRequest(page = 1) {
    return {
      topic_markers: formState.topic_markers,
      max_results: Number(formState.max_results),
      page,
    };
  }

  function handleChange(event) {
    const { name, value } = event.target;
    setFormState((current) => ({
      ...current,
      [name]: name === "max_results" ? Number(value) : value,
    }));
  }

  function handleToggleTopic(markerKey) {
    setFormState((current) => {
      const exists = current.topic_markers.includes(markerKey);
      return {
        ...current,
        topic_markers: exists
          ? current.topic_markers.filter((value) => value !== markerKey)
          : [...current.topic_markers, markerKey],
      };
    });
  }

  async function handleSubmit(event) {
    event.preventDefault();
    const requestPayload = buildRequest(1);
    setLoading(true);
    setError("");
    setSelectedIds([]);
    setActiveTopicFilter("all");

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

  const canSubmit = formState.topic_markers.length > 0;

  return (
    <div className="page-stack">
      <section className="feature-panel hero-panel">
        <div className="panel-heading">
          <div>
            <span className="eyebrow">Reddit Discovery</span>
            <h3>Pick topic markers, then rank the best Reddit clips</h3>
            <p>
              Select one or more topic markers and the app will fetch clips only from the
              subreddits mapped in the JSON catalog. Results list video clips only and are sorted
              by shortest length first before you lock five clips for compilation.
            </p>
          </div>
        </div>

        <form className="modal-form" onSubmit={handleSubmit}>
          <div className="topic-marker-panel">
            <div className="topic-marker-heading">
              <strong>Topic markers</strong>
              <span className="helper-text">
                Select multiple markers to fetch clips only from those mapped subreddits.
              </span>
            </div>

            {topicOptions.length ? (
              <div className="topic-marker-grid" role="group" aria-label="Topic markers">
                {topicOptions.map((option) => {
                  const isActive = formState.topic_markers.includes(option.key);
                  return (
                    <button
                      key={option.key}
                      className={`topic-marker-chip${isActive ? " active" : ""}`}
                      type="button"
                      onClick={() => handleToggleTopic(option.key)}
                      aria-pressed={isActive}
                    >
                      <span>{option.label}</span>
                      <small>{option.subreddits.length} subreddits</small>
                    </button>
                  );
                })}
              </div>
            ) : (
              <p className="helper-text">{topicLoadError || "No topic markers configured yet."}</p>
            )}

            {selectedTopicOptions.length ? (
              <p className="helper-text">
                Searching only in:{" "}
                {selectedTopicOptions
                  .flatMap((option) => option.subreddits.map((subreddit) => `r/${subreddit}`))
                  .join(", ")}
              </p>
            ) : null}
          </div>

          <div className="form-grid">
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
          </div>

          <div className="action-row">
            <button className="primary-button" type="submit" disabled={loading || !canSubmit}>
              {loading ? "Searching..." : canSubmit ? "Discover clips" : "Select at least one topic"}
            </button>
          </div>
        </form>
      </section>

      {error ? <EmptyState title="Discovery blocked" message={error} /> : null}

      {loading ? (
        <LoadingState message="Fetching posts from the selected topic subreddits and ranking results..." />
      ) : (
        <>
          <section className="feature-panel">
            <div className="panel-heading">
              <div>
                <span className="eyebrow">Selection</span>
                <h3>Choose exactly 5 compilation-ready clips</h3>
                <p>
                  Only video clips from the selected topic subreddits are shown here.
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

          {activeQuery ? (
            <>
              <section className="panel-inline-summary">
                <div>
                  <span className="eyebrow">Discovery results</span>
                  <strong>
                    Loaded {filteredItems.length} of {results.total_results} ranked clips
                  </strong>
                  <p className="helper-text">Sorted by clip length from shortest to longest.</p>
                </div>
              </section>

              {resultTopicOptions.length ? (
                <section className="feature-panel">
                  <div className="panel-heading">
                    <div>
                      <span className="eyebrow">View Filter</span>
                      <h3>Browse clips by topic</h3>
                      <p className="helper-text">
                        Narrow the current results to one selected topic without changing the fetch.
                      </p>
                    </div>
                  </div>
                  <div className="topic-filter-row" role="group" aria-label="Result topic filter">
                    <button
                      type="button"
                      className={`topic-filter-chip${activeTopicFilter === "all" ? " active" : ""}`}
                      onClick={() => setActiveTopicFilter("all")}
                    >
                      All topics
                    </button>
                    {resultTopicOptions.map((option) => (
                      <button
                        key={option.key}
                        type="button"
                        className={`topic-filter-chip${activeTopicFilter === option.key ? " active" : ""}`}
                        onClick={() => setActiveTopicFilter(option.key)}
                      >
                        {option.label}
                      </button>
                    ))}
                  </div>
                </section>
              ) : null}

              {filteredItems.length === 0 ? (
                <EmptyState
                  title="No clips found"
                  message={
                    activeTopicFilter === "all"
                      ? "Try another topic marker mix or increase the page size."
                      : "No clips matched this topic filter yet. Switch back to all topics or load more."
                  }
                />
              ) : (
                <>
                  <section className="results-grid" aria-live="polite">
                    {filteredItems.map((clip) => {
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
          ) : null}
        </>
      )}
    </div>
  );
}

export default RedditDiscoveryPage;
