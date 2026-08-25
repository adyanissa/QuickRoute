// Where THIS frontend is reachable from a phone camera.
//
// A QuickRoute QR label has to encode a real, openable HTTPS URL — a bare
// code like "2B8RLYRP" shows up in a camera app as inert text. The URL form
// is deliberately the ROOT query parameter:
//
//     {PUBLIC_FRONTEND_URL}/?locationCode={CODE}
//
// and NOT a deep route such as /scan/{CODE}, because the deployment
// (.github/workflows/deploy-aws.yml) only syncs `dist` to S3 and invalidates
// CloudFront — it configures no custom error response mapping unknown paths
// back to index.html. "/" is always served by the distribution's root object,
// so the root form is the only one guaranteed to boot the SPA. This also
// means we do NOT introduce a second navigation system: the query parameter
// is read by the existing entry screen and feeds the existing flow.
//
// The production hostname is NEVER hard-coded here. It comes from
// VITE_PUBLIC_FRONTEND_URL, the same `import.meta.env` convention
// api/api.js already uses for VITE_API_BASE_URL — including the optional
// chaining on `.env` itself, which plain Node (this repo's dependency-free
// *.test.mjs runner) does not populate.

export const PUBLIC_FRONTEND_URL_ENV_KEY = 'VITE_PUBLIC_FRONTEND_URL';

// The single query-parameter name the QR payload and the entry screen agree
// on. Exported so neither side can drift into a different spelling.
export const LOCATION_CODE_QUERY_PARAM = 'locationCode';

/**
 * The configured public origin, falling back to wherever this bundle is
 * actually being served from.
 *
 * window.location.origin is a correct default rather than a guess: the admin
 * generating a QR is already loading this app from the deployed frontend, so
 * its own origin is by definition the origin an end user should be sent to.
 * The env var exists for the cases where that is not true — a preview build,
 * a custom domain in front of CloudFront, or a print job produced from
 * localhost.
 *
 * @returns {string} an absolute origin, or '' when neither source exists
 *                   (e.g. plain Node in the test runner).
 */
export function getPublicFrontendUrl() {
  const configured = import.meta.env?.VITE_PUBLIC_FRONTEND_URL;

  if (typeof configured === 'string' && configured.trim()) {
    return configured.trim();
  }

  if (typeof window !== 'undefined' && window.location?.origin) {
    return window.location.origin;
  }

  return '';
}

/**
 * Build the URL a QR label encodes for one LocationCode.
 *
 * Uses URL/URLSearchParams rather than string concatenation so a base with
 * or without a trailing slash, or a code containing a character that needs
 * percent-encoding, can never produce a malformed link.
 *
 * The code itself is passed through untouched — this never invents, rewrites,
 * normalises or generates a LocationCode. It only formats one that already
 * exists in the database.
 *
 * @param {string} code    an existing LocationCode.code
 * @param {string} baseUrl origin to build against; defaults to the configured
 *                         public frontend URL
 * @returns {string} absolute URL, or '' when there is nothing valid to build
 */
export function buildLocationCodeUrl(code, baseUrl = getPublicFrontendUrl()) {
  const trimmedCode = typeof code === 'string' ? code.trim() : '';
  const trimmedBase = typeof baseUrl === 'string' ? baseUrl.trim() : '';

  if (!trimmedCode || !trimmedBase) return '';

  let url;

  try {
    url = new URL(trimmedBase);
  } catch {
    // A misconfigured env var must never render a broken QR that looks
    // valid — the caller falls back to showing no QR at all.
    return '';
  }

  // Force the ROOT form regardless of any path on the configured base: only
  // "/" is guaranteed to be served by the SPA (see the module comment).
  url.pathname = '/';
  url.search = '';
  url.hash = '';
  url.searchParams.set(LOCATION_CODE_QUERY_PARAM, trimmedCode);

  return url.toString();
}
