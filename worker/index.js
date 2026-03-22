/**
 * AutoArboxBot Cloudflare Worker
 * Manages user credentials (KV) and public data (GitHub).
 */

const CORS_HEADERS = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Methods": "GET,POST,PUT,DELETE,PATCH,OPTIONS",
  "Access-Control-Allow-Headers": "Content-Type,X-Worker-Key",
};

function json(data, status = 200) {
  return new Response(JSON.stringify(data), {
    status,
    headers: { "Content-Type": "application/json", ...CORS_HEADERS },
  });
}

function err(message, status = 400) {
  return json({ error: message }, status);
}

// ── GitHub helpers ──────────────────────────────────────────────────

async function ghGet(env, path) {
  const url = `https://api.github.com/repos/${env.GITHUB_REPO}/contents/${path}?ref=${env.GITHUB_BRANCH}`;
  const res = await fetch(url, {
    headers: {
      Authorization: `token ${env.GITHUB_PAT}`,
      Accept: "application/vnd.github.v3+json",
      "User-Agent": "AutoArboxBot-Worker",
    },
  });
  if (!res.ok) return null;
  const meta = await res.json();
  const content = JSON.parse(atob(meta.content));
  return { content, sha: meta.sha };
}

async function ghPut(env, path, content, sha, message) {
  const url = `https://api.github.com/repos/${env.GITHUB_REPO}/contents/${path}`;
  const body = {
    message: message || `Update ${path} [skip ci]`,
    content: btoa(JSON.stringify(content, null, 2)),
    branch: env.GITHUB_BRANCH,
  };
  if (sha) body.sha = sha;
  const res = await fetch(url, {
    method: "PUT",
    headers: {
      Authorization: `token ${env.GITHUB_PAT}`,
      Accept: "application/vnd.github.v3+json",
      "User-Agent": "AutoArboxBot-Worker",
      "Content-Type": "application/json",
    },
    body: JSON.stringify(body),
  });
  return res.ok;
}

// ── Auth middleware ──────────────────────────────────────────────────

function authenticate(request, env) {
  const key = request.headers.get("X-Worker-Key");
  return key && key === env.WORKER_KEY;
}

// ── Route handlers ──────────────────────────────────────────────────

async function handlePostUsers(request, env) {
  const body = await request.json();
  const { user_id, name, email, password, membership_id, locations_box_id, notification_email } = body;

  if (!user_id || !name || !email || !password || !membership_id) {
    return err("Missing required fields: user_id, name, email, password, membership_id");
  }

  // Store credentials in KV (private)
  await env.ARBOX_KV.put(
    `creds:${user_id}`,
    JSON.stringify({ email, password, membership_id: Number(membership_id) })
  );

  // Update public profile in GitHub data/users.json
  const file = await ghGet(env, "data/users.json");
  const usersData = file ? file.content : { users: {} };
  usersData.users[user_id] = {
    name,
    notification_email: notification_email || "",
    locations_box_id: Number(locations_box_id) || 14,
  };

  const ok = await ghPut(env, "data/users.json", usersData, file?.sha, `Add/update user ${user_id} [skip ci]`);
  if (!ok) return err("Failed to update users.json on GitHub", 502);

  return json({ ok: true, user_id });
}

async function handleGetRules(env) {
  const file = await ghGet(env, "data/rules.json");
  if (!file) return json({ rules: [] });
  return json(file.content);
}

async function handlePostRules(request, env) {
  const rule = await request.json();

  // Generate id + compute trigger day
  rule.id = rule.id || crypto.randomUUID();
  rule.trigger_day = ((rule.target_day - 3 + 7) % 7);
  rule.trigger_time = rule.trigger_time || rule.target_time.slice(0, 5) + ":00";
  rule.repeat = rule.repeat || "weekly";
  rule.enabled = rule.enabled !== false;
  rule.created_at = rule.created_at || new Date().toISOString();

  const file = await ghGet(env, "data/rules.json");
  const data = file ? file.content : { rules: [] };
  data.rules.push(rule);

  const ok = await ghPut(env, "data/rules.json", data, file?.sha, `Add rule ${rule.name} [skip ci]`);
  if (!ok) return err("Failed to save rule", 502);

  return json({ ok: true, rule });
}

async function handlePutRule(ruleId, request, env) {
  const updates = await request.json();
  const file = await ghGet(env, "data/rules.json");
  if (!file) return err("rules.json not found", 404);

  const data = file.content;
  const idx = data.rules.findIndex((r) => r.id === ruleId);
  if (idx === -1) return err("Rule not found", 404);

  // Recompute trigger day if target_day changed
  if (updates.target_day !== undefined) {
    updates.trigger_day = ((updates.target_day - 3 + 7) % 7);
  }

  data.rules[idx] = { ...data.rules[idx], ...updates };

  const ok = await ghPut(env, "data/rules.json", data, file.sha, `Update rule ${ruleId} [skip ci]`);
  if (!ok) return err("Failed to update rule", 502);

  return json({ ok: true, rule: data.rules[idx] });
}

async function handleDeleteRule(ruleId, env) {
  const file = await ghGet(env, "data/rules.json");
  if (!file) return err("rules.json not found", 404);

  const data = file.content;
  const before = data.rules.length;
  data.rules = data.rules.filter((r) => r.id !== ruleId);
  if (data.rules.length === before) return err("Rule not found", 404);

  const ok = await ghPut(env, "data/rules.json", data, file.sha, `Delete rule ${ruleId} [skip ci]`);
  if (!ok) return err("Failed to delete rule", 502);

  return json({ ok: true });
}

async function handlePatchRule(ruleId, env) {
  const file = await ghGet(env, "data/rules.json");
  if (!file) return err("rules.json not found", 404);

  const data = file.content;
  const rule = data.rules.find((r) => r.id === ruleId);
  if (!rule) return err("Rule not found", 404);

  rule.enabled = !rule.enabled;

  const ok = await ghPut(env, "data/rules.json", data, file.sha, `Toggle rule ${ruleId} [skip ci]`);
  if (!ok) return err("Failed to toggle rule", 502);

  return json({ ok: true, enabled: rule.enabled });
}

async function handleGetCreds(userId, env) {
  const raw = await env.ARBOX_KV.get(`creds:${userId}`);
  if (!raw) return err("Credentials not found", 404);
  return json(JSON.parse(raw));
}

async function handleGetClasses(env) {
  const file = await ghGet(env, "data/classes.json");
  if (!file) return json({ last_updated: "", classes: {} });
  return json(file.content);
}

// ── Router ──────────────────────────────────────────────────────────

export default {
  async fetch(request, env) {
    if (request.method === "OPTIONS") {
      return new Response(null, { status: 204, headers: CORS_HEADERS });
    }

    const url = new URL(request.url);
    const path = url.pathname;
    const method = request.method;

    // Public GET routes (no auth)
    if (method === "GET" && path === "/rules") return handleGetRules(env);
    if (method === "GET" && path === "/classes") return handleGetClasses(env);

    // All other routes require auth
    if (method !== "GET" && !authenticate(request, env)) {
      return err("Unauthorized", 401);
    }
    // GET routes that need auth
    if (method === "GET" && !authenticate(request, env)) {
      return err("Unauthorized", 401);
    }

    // Authenticated routes
    if (method === "POST" && path === "/users") return handlePostUsers(request, env);
    if (method === "POST" && path === "/rules") return handlePostRules(request, env);

    // /rules/:id routes
    const ruleMatch = path.match(/^\/rules\/(.+)$/);
    if (ruleMatch) {
      const ruleId = ruleMatch[1];
      if (method === "PUT") return handlePutRule(ruleId, request, env);
      if (method === "DELETE") return handleDeleteRule(ruleId, env);
      if (method === "PATCH") return handlePatchRule(ruleId, env);
    }

    // /creds/:userId
    const credsMatch = path.match(/^\/creds\/(.+)$/);
    if (credsMatch && method === "GET") {
      return handleGetCreds(credsMatch[1], env);
    }

    return err("Not found", 404);
  },
};
