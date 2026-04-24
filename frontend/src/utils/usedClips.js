const USED_CLIPS_STORAGE_KEY = "clipping-automation:used-external-ids";

function normalizeId(value) {
  return String(value || "").trim().toLowerCase();
}

export function readUsedClipIds() {
  try {
    const raw = window.localStorage.getItem(USED_CLIPS_STORAGE_KEY);
    if (!raw) {
      return [];
    }

    const payload = JSON.parse(raw);
    if (!Array.isArray(payload)) {
      return [];
    }

    return Array.from(new Set(payload.map(normalizeId).filter(Boolean)));
  } catch {
    return [];
  }
}

export function appendUsedClipIds(externalIds) {
  const merged = Array.from(new Set([...readUsedClipIds(), ...(externalIds || []).map(normalizeId)]));
  window.localStorage.setItem(USED_CLIPS_STORAGE_KEY, JSON.stringify(merged));
  return merged;
}
