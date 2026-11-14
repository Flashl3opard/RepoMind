// Fetches the backend's OpenAPI schema (BACKEND_URL + DASHBOARD_API_KEY, both
// server-side-only env vars -- this script runs in Node at dev/build time, never in
// the browser) and writes it to tmp/openapi.json for openapi-typescript to consume.
// Run via `pnpm gen:api`, which chains this with openapi-typescript.
import { writeFile, mkdir } from "node:fs/promises";
import path from "node:path";

const backendUrl = process.env.BACKEND_URL ?? "http://localhost:8000";
const apiKey = process.env.DASHBOARD_API_KEY;

const headers = {};
if (apiKey) {
  headers.Authorization = `Bearer ${apiKey}`;
}

const url = `${backendUrl.replace(/\/$/, "")}/openapi.json`;
console.log(`Fetching OpenAPI schema from ${url}`);

const response = await fetch(url, { headers });
if (!response.ok) {
  console.error(
    `Failed to fetch OpenAPI schema: ${response.status} ${response.statusText}\n` +
      `Make sure the backend is running at ${backendUrl} and, if DASHBOARD_API_KEY is set ` +
      `on the backend, that it's also set in this shell/.env.local.`,
  );
  process.exit(1);
}

const schema = await response.json();

const outDir = path.resolve(import.meta.dirname, "..", "tmp");
await mkdir(outDir, { recursive: true });
await writeFile(
  path.join(outDir, "openapi.json"),
  JSON.stringify(schema, null, 2),
);
console.log(`Wrote ${path.join(outDir, "openapi.json")}`);
