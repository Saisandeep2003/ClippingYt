import { useMemo, useState } from "react";
import { Link } from "react-router-dom";

import EmptyState from "../components/EmptyState";
import LoadingState from "../components/LoadingState";
import { getApiRoot, markCompilationClipsUsed, renderCompilation } from "../services/api";

const STORAGE_KEY = "clipping-automation:selected-clips";

function readSelection() {
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    if (!raw) {
      return null;
    }
    return JSON.parse(raw);
  } catch {
    return null;
  }
}

function writeSelection(selection) {
  if (!selection?.selected_clips?.length) {
    window.localStorage.removeItem(STORAGE_KEY);
    return;
  }

  window.localStorage.setItem(STORAGE_KEY, JSON.stringify(selection));
}

function buildCompilation(selection) {
  const clips = selection?.selected_clips || [];
  const clipCount = clips.length;
  const topics = selection?.tags?.join(" / ") || "Reddit clips";
  const opener = clips[0];
  const closer = clips[clips.length - 1];
  const title = clipCount ? `Top ${clipCount} ${topics} compilation` : "Reddit clip compilation";

  return {
    title,
    format: "countdown compilation",
    pacing: "Open with the strongest scroll-stopper, keep the middle clips quick, and end on the highest emotional payoff.",
    hook: opener ? `Open with "${opener.title}" in the first beat to stop the scroll immediately.` : "",
    closer: closer ? `Close with "${closer.title}" as the final payoff moment.` : "",
    selected_clips: clips.map((clip, index) => ({
      external_id: clip.external_id,
      rank: index + 1,
      title: clip.title,
      source: clip.source,
      url: clip.url,
      subreddit: clip.subreddit,
      duration_seconds: clip.duration_seconds,
    })),
  };
}

function CompilationPage() {
  const [selection, setSelection] = useState(() => readSelection());
  const compilation = useMemo(() => buildCompilation(selection), [selection]);
  const [rendering, setRendering] = useState(false);
  const [downloading, setDownloading] = useState(false);
  const [renderError, setRenderError] = useState("");
  const [renderResult, setRenderResult] = useState(null);
  const [downloadMessage, setDownloadMessage] = useState("");

  if (!selection || !selection.selected_clips?.length) {
    return (
      <EmptyState
        title="No compilation queued"
        message="Select Reddit clips in Discovery, then proceed here to trim the lineup and render a compilation."
      />
    );
  }

  function handleDiscardClip(indexToRemove) {
    setSelection((current) => {
      if (!current?.selected_clips?.length) {
        return current;
      }

      const nextClips = current.selected_clips
        .filter((_, index) => index !== indexToRemove)
        .map((clip, index) => ({
          ...clip,
          rank: index + 1,
        }));

      const nextSelection = nextClips.length
        ? {
            ...current,
            selected_clips: nextClips,
          }
        : null;

      writeSelection(nextSelection);
      return nextSelection;
    });

    setRenderError("");
    setRenderResult(null);
    setDownloadMessage("");
  }

  async function handleRender() {
    if (!compilation.selected_clips.length) {
      return;
    }

    setRendering(true);
    setRenderError("");
    setDownloadMessage("");

    try {
      const result = await renderCompilation({
        title: compilation.title,
        selected_clips: compilation.selected_clips,
      });
      setRenderResult({
        ...result,
        video_url: `${getApiRoot()}${result.output_url}`,
      });
    } catch (err) {
      setRenderError(err.response?.data?.detail || "Unable to render the compilation video.");
    } finally {
      setRendering(false);
    }
  }

  async function handleDownloadRenderedVideo() {
    if (!renderResult?.video_url) {
      return;
    }

    const externalIds = compilation.selected_clips
      .map((clip) => clip.external_id)
      .filter(Boolean);

    setDownloading(true);
    setRenderError("");
    setDownloadMessage("");

    try {
      const response = await fetch(renderResult.video_url);
      if (!response.ok) {
        throw new Error("Unable to download the rendered video.");
      }

      const blob = await response.blob();
      const objectUrl = window.URL.createObjectURL(blob);
      const downloadLink = document.createElement("a");
      const outputName = renderResult.output_url?.split("/").pop() || "reddit-compilation.mp4";
      downloadLink.href = objectUrl;
      downloadLink.download = outputName;
      document.body.appendChild(downloadLink);
      downloadLink.click();
      downloadLink.remove();
      window.URL.revokeObjectURL(objectUrl);

      if (externalIds.length) {
        await markCompilationClipsUsed({ external_ids: externalIds });
      }

      setDownloadMessage("Downloaded successfully. These source clips are now marked as used.");
    } catch (err) {
      setRenderError(err.message || "Unable to download the rendered video.");
    } finally {
      setDownloading(false);
    }
  }

  return (
    <div className="page-stack">
      <section className="feature-panel hero-panel">
        <div className="panel-heading">
          <div>
            <span className="eyebrow">Compilation</span>
            <h3>Your selected clips, ready to trim and render</h3>
            <p>
              Remove any clip you do not want, keep the remaining lineup in order, and render the
              current selection into a compilation without going back to discovery.
            </p>
          </div>
          <Link className="primary-button" to="/reddit-discovery">
            Back to discovery
          </Link>
        </div>
      </section>

      {rendering ? <LoadingState message="Rendering compilation video..." /> : null}
      {downloading ? <LoadingState message="Downloading video and marking source clips as used..." /> : null}
      {renderError ? <EmptyState title="Render blocked" message={renderError} /> : null}
      {downloadMessage ? <section className="feature-panel"><p className="helper-text">{downloadMessage}</p></section> : null}

      <section className="feature-panel">
        <div className="panel-heading">
          <div>
            <span className="eyebrow">Compilation brief</span>
            <h3>{compilation.title}</h3>
            <p>{compilation.pacing}</p>
          </div>
          <button
            className="primary-button"
            type="button"
            onClick={handleRender}
            disabled={rendering || compilation.selected_clips.length === 0}
          >
            {rendering ? "Rendering..." : "Proceed and render video"}
          </button>
        </div>

        <div className="selection-meter">
          <strong>{compilation.selected_clips.length} clips ready</strong>
          <span>Use the red X on any card to discard it before rendering.</span>
        </div>

        <div className="stack-list">
          <article className="mini-card">
            <h4>Hook</h4>
            <p>{compilation.hook || "The first remaining clip becomes the opening beat."}</p>
          </article>
          <article className="mini-card">
            <h4>Closer</h4>
            <p>{compilation.closer || "The last remaining clip becomes the closing payoff moment."}</p>
          </article>
        </div>
      </section>

      <section className="results-grid">
        {compilation.selected_clips.map((clip, index) => (
          <article className="discovery-card selected compilation-card" key={`${clip.url}-${clip.rank}-${index}`}>
            <button
              className="clip-remove-button"
              type="button"
              aria-label={`Discard ${clip.title}`}
              onClick={() => handleDiscardClip(index)}
            >
              X
            </button>

            <div className="candidate-card__header">
              <div>
                <span className="eyebrow">{clip.source}</span>
                <h3>
                  #{clip.rank} {clip.title}
                </h3>
              </div>
            </div>

            <div className="candidate-meta-grid">
              <div>
                <span className="meta-label">Subreddit</span>
                <span>{clip.subreddit}</span>
              </div>
              <div>
                <span className="meta-label">Duration</span>
                <span>{clip.duration_seconds ? `${clip.duration_seconds}s` : "n/a"}</span>
              </div>
            </div>

            <div className="link-row">
              <a href={clip.url} target="_blank" rel="noreferrer">
                Open clip
              </a>
            </div>
          </article>
        ))}
      </section>

      {renderResult ? (
        <section className="feature-panel">
          <div className="panel-heading">
            <div>
              <span className="eyebrow">Rendered video</span>
              <h3>{renderResult.title}</h3>
              <p>
                {renderResult.clip_count} clips · {renderResult.total_duration_seconds}s total
              </p>
            </div>
          </div>

          <div className="compiled-video-frame">
            <video className="compiled-video" controls preload="metadata" src={renderResult.video_url} />
          </div>

          <div className="link-row">
            <a href={renderResult.video_url} target="_blank" rel="noreferrer">
              Open rendered video
            </a>
            <button className="primary-button" type="button" onClick={handleDownloadRenderedVideo} disabled={downloading}>
              {downloading ? "Downloading..." : "Download rendered video"}
            </button>
          </div>
        </section>
      ) : null}
    </div>
  );
}

export default CompilationPage;
