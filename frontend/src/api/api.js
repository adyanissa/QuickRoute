const API_BASE_URL = import.meta.env.VITE_API_BASE_URL;

// Same key AuthContext writes the JWT access token to on login/signup.
// Read directly from storage here (rather than importing AuthContext) so
// every API call — including ones made outside a React component — always
// sends the current token with no extra wiring required.
const TOKEN_STORAGE_KEY = "quickroute_token";

function getStoredToken() {
  try {
    return localStorage.getItem(TOKEN_STORAGE_KEY);
  } catch {
    return null;
  }
}

function clearStoredAuth() {
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

    throw new Error(errorData?.detail || "API request failed");
  }

  return response.json();
}

export default API_BASE_URL;