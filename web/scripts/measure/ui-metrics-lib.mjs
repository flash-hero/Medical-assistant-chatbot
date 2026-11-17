/** Metric records from the Lighthouse and route-JS measurement outputs (see ui-metrics.mjs). */

const CHAT_ROUTE = /^\/(en|fr|ar)\/chat$/;

function base(source, measuredAt) {
  return { source, measured_at: measuredAt, free_tier: false };
}

/**
 * ui.lighthouse_a11y gates on the lowest accessibility score over every page and form factor.
 * Performance scores are reported per run as informational records (no gate reads them).
 */
export function lighthouseRecords(lh) {
  const runs = lh.runs ?? [];
  if (runs.length === 0) return [];
  const meta = base("web/scripts/measure/lighthouse.mjs", lh.measured_at);
  const worst = runs.reduce((min, r) => (r.scores.accessibility < min.scores.accessibility ? r : min));
  const records = [
    {
      metric: "lighthouse_accessibility",
      value: worst.scores.accessibility,
      labels: { worst_page: worst.url, worst_form_factor: worst.form_factor, pages: runs.map((r) => `${r.form_factor}:${r.url}`).join(",") },
      sample_size: runs.length,
      ...meta,
    },
  ];
  for (const r of runs) {
    records.push({
      metric: "lighthouse_performance",
      value: r.scores.performance,
      labels: { page: r.url, form_factor: r.form_factor, target: CHAT_ROUTE.test(r.url) ? "85" : "90" },
      sample_size: 1,
      ...meta,
    });
  }
  return records;
}

/** ui.chat_js_gzip_kb gates on the heaviest chat route; other routes are informational. */
export function routeJsRecords(routeJs) {
  const routes = routeJs.routes ?? [];
  const meta = base("web/scripts/measure/route-js.mjs", routeJs.measured_at);
  const chat = routes.filter((r) => CHAT_ROUTE.test(r.route));
  const records = [];
  if (chat.length > 0) {
    const heaviest = chat.reduce((max, r) => (r.gzip_kb > max.gzip_kb ? r : max));
    records.push({
      metric: "chat_route_js_gzip_kb",
      value: heaviest.gzip_kb,
      labels: { route: heaviest.route, scripts: String(heaviest.scripts), raw_kb: String(heaviest.raw_kb) },
      sample_size: chat.length,
      ...meta,
    });
  }
  for (const r of routes.filter((x) => !CHAT_ROUTE.test(x.route))) {
    records.push({ metric: "route_js_gzip_kb", value: r.gzip_kb, labels: { route: r.route }, sample_size: 1, ...meta });
  }
  return records;
}
