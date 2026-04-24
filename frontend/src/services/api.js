import axios from "axios";

const apiClient = axios.create({
  baseURL: process.env.REACT_APP_API_URL || "http://127.0.0.1:8000/api",
  headers: {
    "Content-Type": "application/json",
  },
});

export function getApiRoot() {
  return apiClient.defaults.baseURL.replace(/\/api\/?$/, "");
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
