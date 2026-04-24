# Clipping Automation Plan

This plan reflects the current FastAPI + React codebase in this repository, not the older CLI-first implementation that previously existed.

## Current Baseline

- [x] FastAPI backend scaffolded with CORS, static asset mounts, and health endpoint
- [x] React frontend scaffolded with dashboard, Reddit discovery, and compilation screens
- [x] Tag-based Reddit discovery flow implemented
- [x] Automatic subreddit expansion and query planning implemented
- [x] Result scoring based on relevance, engagement, and recency implemented
- [x] Used-clip tracking added to reduce repeat selections across sessions
- [x] Playback caching for discovered Reddit clips implemented
- [x] Copyright-risk heuristics service added for screening support
- [x] Compilation render endpoint implemented
- [x] FFmpeg-based clip formatting, title overlays, and outro concatenation implemented
- [x] Frontend selection handoff from discovery to compilation implemented with local storage
- [x] Download flow marks rendered source clips as used
- [x] Initial backend unit tests added for Reddit discovery helpers

## Near-Term Priorities

- [ ] Add a clear `.env.example` or setup doc for Reddit API credentials and local configuration
- [ ] Expand backend test coverage beyond Reddit discovery helper logic
- [ ] Add API-level tests for routers and request validation
- [ ] Add frontend tests for discovery, selection, and compilation flows
- [ ] Improve render error reporting for missing media, audio failures, and FFmpeg issues
- [ ] Validate that all selected clips remain accessible before starting a long render
- [ ] Persist compilation history and render metadata in a more structured way

## Product Gaps

- [ ] Allow manual reordering of the five selected clips in the compilation screen
- [ ] Show richer copyright-risk reasons in the UI instead of relying on backend-only heuristics
- [ ] Add clip review states beyond "used" tracking
- [ ] Add search presets or saved discovery profiles for repeatable topics
- [ ] Add better visibility into why a result was rejected or marked not compilation-ready
- [ ] Support reusable render templates for different countdown styles

## Infrastructure And Ops

- [ ] Pin and document the supported Python and Node versions
- [ ] Add linting and formatting commands for backend and frontend
- [ ] Add a single project bootstrap flow for local setup
- [ ] Add CI for backend tests and frontend build verification
- [ ] Decide whether to keep SQLite as the long-term storage layer

## Open Decisions

- [ ] Decide whether external media should ever be renderable or remain discovery-only
- [ ] Decide whether used clips should be hidden forever or expire after a cooldown window
- [ ] Decide whether compilation rendering should stay local-only or move to a worker/job model
- [ ] Decide whether copyright screening should remain heuristic or integrate stronger media analysis later
- [ ] Decide whether the next milestone is creator review tooling, render reliability, or publishing automation
