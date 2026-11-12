"""The single-page web UI served at GET /. It talks to the JSON API on the same origin."""

INDEX_HTML = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>shortlink</title>
<style>
  :root { color-scheme: light dark; }
  body { font: 16px/1.5 system-ui, sans-serif; max-width: 34rem; margin: 3rem auto; padding: 0 1rem; }
  h1 { margin-bottom: 0.25rem; }
  p.sub { margin-top: 0; opacity: 0.7; }
  form, section { display: grid; gap: 0.75rem; margin-top: 1.5rem; }
  label { display: grid; gap: 0.25rem; font-size: 0.9rem; }
  input, button { font: inherit; padding: 0.5rem 0.6rem; border-radius: 6px; border: 1px solid #8886; }
  button { cursor: pointer; background: #2563eb; color: white; border-color: #2563eb; }
  button.secondary { background: transparent; color: inherit; border-color: #8886; }
  .row { display: grid; grid-template-columns: 1fr 1fr; gap: 0.75rem; }
  .result { padding: 0.75rem; border-radius: 6px; border: 1px solid #8886; display: none; }
  .result.error { border-color: #dc2626; color: #dc2626; }
  .result a { word-break: break-all; }
  dl { margin: 0.5rem 0 0; display: grid; grid-template-columns: auto 1fr; gap: 0.2rem 0.75rem; }
  dt { opacity: 0.7; } dd { margin: 0; word-break: break-all; }
</style>
</head>
<body>
<h1>shortlink</h1>
<p class="sub">Paste a long URL, get a short one.</p>

<form id="shorten">
  <label>URL
    <input name="url" type="url" placeholder="https://example.com/very/long/path" required>
  </label>
  <div class="row">
    <label>Custom alias (optional)
      <input name="alias" type="text" placeholder="my-link">
    </label>
    <label>Expires after, seconds (optional)
      <input name="ttl" type="number" min="1" placeholder="3600">
    </label>
  </div>
  <button type="submit">Shorten</button>
</form>
<div id="created" class="result" role="status"></div>

<section>
  <h2 style="margin:0">Look up stats</h2>
  <form id="lookup" class="row" style="margin:0">
    <input name="code" type="text" placeholder="code or short URL" required>
    <button type="submit" class="secondary">Get stats</button>
  </form>
  <div id="stats" class="result" role="status"></div>
</section>

<script>
function show(box, error) {
  box.className = "result" + (error ? " error" : "");
  box.style.display = "block";
  box.replaceChildren();
  return box;
}

function showError(box, message) {
  show(box, true).textContent = message;
}

async function call(method, path, body) {
  const resp = await fetch(path, {
    method,
    headers: body ? {"Content-Type": "application/json"} : {},
    body: body ? JSON.stringify(body) : undefined,
  });
  const data = await resp.json().catch(() => ({}));
  if (!resp.ok) {
    const wait = resp.headers.get("Retry-After");
    throw new Error((data.error || "request failed (" + resp.status + ")") +
                    (wait ? " - retry in " + wait + "s" : ""));
  }
  return data;
}

function row(list, name, value) {
  const dt = document.createElement("dt");
  dt.textContent = name;
  const dd = document.createElement("dd");
  dd.textContent = value;
  list.append(dt, dd);
}

function when(ts) {
  return ts ? new Date(ts * 1000).toLocaleString() : "never";
}

document.getElementById("shorten").addEventListener("submit", async (e) => {
  e.preventDefault();
  const form = new FormData(e.target);
  const body = {url: form.get("url")};
  if (form.get("alias")) body.alias = form.get("alias");
  if (form.get("ttl")) body.ttl_seconds = Number(form.get("ttl"));
  const box = document.getElementById("created");
  try {
    const link = await call("POST", "/shorten", body);
    show(box, false);
    const a = document.createElement("a");
    a.href = link.short_url;
    a.target = "_blank";
    a.rel = "noopener";
    a.textContent = link.short_url;
    const copy = document.createElement("button");
    copy.type = "button";
    copy.className = "secondary";
    copy.textContent = "Copy";
    copy.style.marginLeft = "0.75rem";
    copy.onclick = async () => {
      await navigator.clipboard.writeText(link.short_url);
      copy.textContent = "Copied";
    };
    box.append(a, copy);
  } catch (err) {
    showError(box, err.message);
  }
});

document.getElementById("lookup").addEventListener("submit", async (e) => {
  e.preventDefault();
  const box = document.getElementById("stats");
  // accept either a bare code or a full short URL
  const code = new FormData(e.target).get("code").trim().replace(/\\/+$/, "").split("/").pop();
  try {
    const link = await call("GET", "/" + encodeURIComponent(code) + "/stats");
    const list = document.createElement("dl");
    row(list, "Original", link.url);
    row(list, "Clicks", link.clicks);
    row(list, "Created", when(link.created_at));
    row(list, "Expires", when(link.expires_at));
    show(box, false).append(list);
  } catch (err) {
    showError(box, err.message);
  }
});
</script>
</body>
</html>
"""
