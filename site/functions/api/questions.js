// Cloudflare Pages Function: /api/questions
//
//   POST   (the Help page's form)      store a visitor's question
//   GET    (admin.html, with the key)  list stored questions, newest first
//   DELETE ?id=q:...  (with the key)   remove one question
//
// Needs, in the Pages project's settings (Settings > Bindings / Variables and secrets):
//   QUESTIONS    a KV namespace binding
//   ADMIN_TOKEN  a secret: the key you type into admin.html
// Without them the endpoint answers 503 and the form shows its "not sent" line.

const MAX_QUESTION = 1000;
const MAX_EMAIL = 200;
const KEEP = 500; // at most this many questions are listed

const json = (data, status = 200) =>
  new Response(JSON.stringify(data), {
    status,
    headers: { 'content-type': 'application/json; charset=utf-8', 'cache-control': 'no-store' },
  });

function authorised(request, env) {
  const token = env.ADMIN_TOKEN || '';
  const given = (request.headers.get('Authorization') || '').replace(/^Bearer\s+/i, '');
  if (!token || given.length !== token.length) return false;
  let diff = 0; // compare in constant time
  for (let i = 0; i < token.length; i += 1) diff |= token.charCodeAt(i) ^ given.charCodeAt(i);
  return diff === 0;
}

export async function onRequestPost({ request, env }) {
  if (!env.QUESTIONS) return json({ error: 'Questions are not set up yet.' }, 503);

  let form;
  try {
    form = await request.formData();
  } catch {
    return json({ error: 'Send the form fields.' }, 400);
  }
  // a field people never see: bots fill it in, so pretend it worked and keep nothing
  if (String(form.get('website') || '').trim()) return json({ ok: true }, 201);

  const question = String(form.get('question') || '').trim();
  const email = String(form.get('email') || '').trim();
  if (question.length < 5 || question.length > MAX_QUESTION) {
    return json({ error: `Write a question of 5 to ${MAX_QUESTION} characters.` }, 400);
  }
  if (email && (email.length > MAX_EMAIL || !/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(email))) {
    return json({ error: 'Write a valid email address, or leave it empty.' }, 400);
  }

  // one question a minute per visitor; the address is kept only for that minute
  const ip = request.headers.get('CF-Connecting-IP') || 'unknown';
  const limitKey = `rl:${ip}`;
  if (await env.QUESTIONS.get(limitKey)) return json({ error: 'Wait a minute before sending another question.' }, 429);
  await env.QUESTIONS.put(limitKey, '1', { expirationTtl: 60 });

  const at = new Date().toISOString();
  const id = `q:${at}:${crypto.randomUUID().slice(0, 8)}`;
  await env.QUESTIONS.put(id, JSON.stringify({ question, email, at }));
  return json({ ok: true }, 201);
}

export async function onRequestGet({ request, env }) {
  if (!env.QUESTIONS || !env.ADMIN_TOKEN) return json({ error: 'Questions are not set up yet.' }, 503);
  if (!authorised(request, env)) return json({ error: 'Wrong admin key.' }, 401);

  const keys = [];
  let cursor;
  do {
    const page = await env.QUESTIONS.list({ prefix: 'q:', cursor });
    keys.push(...page.keys.map((k) => k.name));
    cursor = page.list_complete ? undefined : page.cursor;
  } while (cursor && keys.length < KEEP);

  keys.sort().reverse(); // ids start with the ISO time, so this is newest first
  const items = await Promise.all(
    keys.slice(0, KEEP).map(async (id) => ({ id, ...JSON.parse((await env.QUESTIONS.get(id)) || '{}') })),
  );
  return json({ items });
}

export async function onRequestDelete({ request, env }) {
  if (!env.QUESTIONS || !env.ADMIN_TOKEN) return json({ error: 'Questions are not set up yet.' }, 503);
  if (!authorised(request, env)) return json({ error: 'Wrong admin key.' }, 401);
  const id = new URL(request.url).searchParams.get('id') || '';
  if (!id.startsWith('q:')) return json({ error: 'Unknown question.' }, 400);
  await env.QUESTIONS.delete(id);
  return json({ ok: true });
}
