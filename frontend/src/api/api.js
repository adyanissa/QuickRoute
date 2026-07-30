// Optional chaining on `.env` (not just `.VITE_API_BASE_URL`) is
// deliberate: under Vite this object always exists, but plain Node (used
// to run this repo's dependency-free *.test.mjs files) doesn't populate
// import.meta.env at all, which would otherwise throw before any test
// code runs.
const API_BASE_URL = import.meta.env?.VITE_API_BASE_URL;

// Same key AuthContext writes the JWT access token to on login/signup.
// Read directly from storage here (rather than importing AuthContext) so
// every API call — including ones made outside a React component — always
// sends the current token with no extra wiring required.
const TOKEN_STORAGE_KEY = "quickroute_token";

// Exported so other request helpers (e.g. mapsApi.js's multipart upload,
// which cannot go through apiRequest() below because it must not set a
// JSON Content-Type header) can attach the same Authorization header from
// the same single source of truth instead of re-implementing token storage
// access.
export function getStoredToken() {
  try {
    return localStorage.getItem(TOKEN_STORAGE_KEY);
  } catch {
    return null;
  }
}

export function clearStoredAuth() {
  try {
    localStorage.removeItem(TOKEN_STORAGE_KEY);
    localStorage.removeItem("quickroute_user");
  } catch {
    // Ignore storage errors.
  }
}

export async function apiRequest(endpoint, options = {}) {
  const token = getStoredToken();

  const response = await fetch(`${API_BASE_URL}${endpoint}`, {
    headers: {
      "Content-Type": "application/json",
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...(options.headers || {}),
    },
    ...options,
  });

  if (!response.ok) {
    const errorData = await response.json().catch(() => null);

    // An expired/invalid token means the stored session is no longer
    // valid anywhere — clear it so the next protected action correctly
    // requires a fresh login instead of silently failing again.
    if (response.status === 401) {
      clearStoredAuth();
    }

    // `status` is attached (in addition to the existing `.message`) so
    // callers that need to distinguish "session expired" (401) from
    // "wrong role" (403) — e.g. the Initialize Project Data action — can
    // do so reliably instead of pattern-matching on the detail text.
    // Existing callers that only read `.message` are unaffected.
    const error = new Error(errorData?.detail || "API request failed");
    error.status = response.status;
    throw error;
  }

  return response.json();
}

export default API_BASE_URL;