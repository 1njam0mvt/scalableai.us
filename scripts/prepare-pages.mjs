/**
 * Cloudflare Pages build script for the ScalableAI frontend.
 * -----------------------------------------------------------------
 * The backend serves three trees:
 *   /          -> frontend/    (mounted twice: "/" and "/app")
 *   /i18n      -> i18n-assets/
 *   /style-marketing.css, /og-banner.png, /faq.html, ... -> public/
 *
 * Pages has a single output dir, so this script reproduces that layout:
 *   dist-pages/         <- frontend/* + public/*
 *   dist-pages/app/     <- frontend/* again (viewer.html, /app/audio/*)
 *   dist-pages/i18n/    <- i18n-assets/*
 *
 * Optional: set API_BASE_URL (Pages env var) to point the UI at a
 * separately deployed backend, e.g. https://api.scalableai.us
 */
import { cpSync, mkdirSync, rmSync, writeFileSync } from "node:fs";
import { join } from "node:path";

const root = process.cwd();
const dist = join(root, "dist-pages");

rmSync(dist, { recursive: true, force: true });
mkdirSync(join(dist, "app"), { recursive: true });

cpSync(join(root, "frontend"), dist, { recursive: true });
cpSync(join(root, "frontend"), join(dist, "app"), { recursive: true });
cpSync(join(root, "public"), dist, { recursive: true });
cpSync(join(root, "i18n-assets"), join(dist, "i18n"), { recursive: true });

const apiBase = (process.env.API_BASE_URL || "").trim().replace(/\/+$/, "");
if (apiBase) {
    const content = `window.API_BASE = "${apiBase}";\n`;
    writeFileSync(join(dist, "api-config.js"), content);
    writeFileSync(join(dist, "app", "api-config.js"), content);
}

console.log(
    "dist-pages ready " +
    (apiBase ? `(API base: ${apiBase})` : "(same-origin API)")
);
