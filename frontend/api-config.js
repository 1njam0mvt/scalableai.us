/**
 * API base URL for the ScalableAI frontend.
 * -----------------------------------------------------------------
 * Same-origin mode (backend serves the frontend, e.g. local dev or
 * single-container deploy): leave as "".
 *
 * Split mode (frontend on Cloudflare Pages, API on Railway):
 * set to the backend origin, e.g. "https://api.scalableai.us"
 * — or let scripts/prepare-pages.mjs fill this in at build time
 *   via the API_BASE_URL environment variable.
 */
window.API_BASE = "";
