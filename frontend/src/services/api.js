import axios from "axios";

const localApiUrl = "http://127.0.0.1:8000/api";
const sameOriginApiUrl = "/api";
const isLocalBrowser =
  typeof window !== "undefined" &&
  ["localhost", "127.0.0.1"].includes(window.location.hostname);
const defaultApiUrl = isLocalBrowser ? localApiUrl : sameOriginApiUrl;

const apiClient = axios.create({
  baseURL: process.env.REACT_APP_API_URL || defaultApiUrl,
  headers: {
    "Content-Type": "application/json",
  },
});

export function getApiRoot() {
  return apiClient.defaults.baseURL.replace(/\/api\/?$/, "");
}

export async function listRedditTopicMarkers() {
  const response = await apiClient.get("/reddit/topics");
  return response.data;
}

export async function discoverRedditClips(payload) {
  const response = await apiClient.post("/reddit/discover", payload);
  return response.data;
}

export async function renderCompilation(payload) {
  const response = await apiClient.post("/compilation/render", payload);
  return response.data;
}

export async function markCompilationClipsUsed(payload) {
  const response = await apiClient.post("/compilation/mark-used", payload);
  return response.data;
}
