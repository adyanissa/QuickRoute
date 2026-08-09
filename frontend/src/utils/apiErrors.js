// RBAC/dashboard cleanup task (frontend completion), Section 2 — shared,
// tiny helper so every admin screen surfaces a backend 403 the exact same
// way (a clear, localized "you don't have permission" message) instead of
// each screen inventing its own generic "failed to load" text for what is
// actually an authorization rejection. `apiRequest` (api.js) already
// attaches `.status` to every thrown error — this only classifies it.
//
// Deliberately NOT a replacement for backend enforcement: this never
// decides whether an action is allowed, it only recognizes the backend's
// own 403 after the fact and picks the right message to show.
export function isForbiddenError(error) {
  return Boolean(error) && error.status === 403;
}

export function isNotFoundError(error) {
  return Boolean(error) && error.status === 404;
}

export function isSessionExpiredError(error) {
  return Boolean(error) && error.status === 401;
}

// `messages` is the calling screen's own UI[lang] object — expected to
// have `forbidden`/`sessionExpired`/`notFound`/generic `loadError` keys
// (screens that don't define all four simply fall back to loadError).
export function resolveApiErrorMessage(error, messages = {}) {
  if (isForbiddenError(error)) {
    return messages.forbidden || messages.loadError || 'You do not have permission to do this.';
  }
  if (isSessionExpiredError(error)) {
    return messages.sessionExpired || messages.loadError || 'Your session has expired. Please log in again.';
  }
  if (isNotFoundError(error)) {
    return messages.notFound || messages.loadError || 'Not found.';
  }
  return error?.message || messages.loadError || 'Something went wrong.';
}
