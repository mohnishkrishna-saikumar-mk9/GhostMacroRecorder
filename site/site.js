// Ghost Macro Recorder website: menu, live release data, answer search and the question form.
const REPO = 'mohnishkrishna-saikumar-mk9/GhostMacroRecorder';
const ASSET = 'GhostMacroRecorder-Setup.exe';

/* ---------------------------------------------------------------- phone menu */
const toggle = document.querySelector('.menu-toggle');
const menu = document.getElementById('menu');
if (toggle && menu) {
  toggle.addEventListener('click', () => {
    const open = menu.classList.toggle('open');
    toggle.setAttribute('aria-expanded', String(open));
  });
}

/* ---------------------------------------------------------------- releases from GitHub
   Every element with data-rel="..." is filled from the newest release; a page that lists versions
   has <ol data-rel-list>. The HTML holds the current values, so nothing breaks offline. */
const fmtDate = (iso) => new Date(iso).toLocaleDateString('en-GB', { day: 'numeric', month: 'long', year: 'numeric' });
const fmtMB = (bytes) => `${(bytes / 1e6).toFixed(1)} MB`;

function notesOf(body) {
  return (body || '')
    .split('\n')
    .map((l) => l.replace(/^[#>*\-\s]+/, '').trim())
    .filter((l) => l && !/^(full changelog|what's changed|new contributors|\*\*full)/i.test(l))
    .slice(0, 6);
}

async function releases() {
  const needs = document.querySelector('[data-rel], [data-rel-list]');
  if (!needs) return;
  let list;
  try {
    const res = await fetch(`https://api.github.com/repos/${REPO}/releases?per_page=10`, {
      headers: { Accept: 'application/vnd.github+json' },
    });
    if (!res.ok) return;
    list = (await res.json()).filter((r) => !r.draft && !r.prerelease);
  } catch {
    return;
  }
  if (!list.length) return;
  const latest = list[0];
  const asset = latest.assets.find((a) => a.name === ASSET) || latest.assets[0];
  const values = {
    version: latest.tag_name.replace(/^v/, ''),
    tag: latest.tag_name,
    date: fmtDate(latest.published_at),
    size: asset ? fmtMB(asset.size) : '',
    url: latest.html_url,
  };
  document.querySelectorAll('[data-rel]').forEach((el) => {
    const v = values[el.dataset.rel];
    if (!v) return;
    if (el.tagName === 'A' && el.dataset.rel === 'url') el.href = v;
    else el.textContent = v;
  });

  const ol = document.querySelector('[data-rel-list]');
  if (!ol) return;
  const known = new Map([...ol.querySelectorAll('li[data-tag]')].map((li) => [li.dataset.tag, li.querySelector('ul')?.outerHTML]));
  ol.replaceChildren(...list.map((r) => {
    const li = document.createElement('li');
    const h = document.createElement('h3');
    h.textContent = r.tag_name;
    const date = Object.assign(document.createElement('span'), { className: 'date', textContent: fmtDate(r.published_at) });
    h.append(date);
    li.append(h);
    const lines = notesOf(r.body);
    if (lines.length) {
      const ul = document.createElement('ul');
      lines.forEach((t) => ul.append(Object.assign(document.createElement('li'), { textContent: t })));
      li.append(ul);
    } else if (known.get(r.tag_name)) {
      li.insertAdjacentHTML('beforeend', known.get(r.tag_name));
    }
    const a = r.assets.find((x) => x.name === ASSET) || r.assets[0];
    const link = Object.assign(document.createElement('a'), {
      className: 'link', href: a ? a.browser_download_url : r.html_url,
      textContent: a ? `Download ${r.tag_name} (${fmtMB(a.size)})` : `See ${r.tag_name} on GitHub`,
    });
    li.append(link);
    return li;
  }));
}
releases();

/* ---------------------------------------------------------------- answer search (Help)
   Forgiving search: punctuation and small words are ignored, words match by their stem
   ("blocked" finds "block"), and the best matches move to the top. */
const search = document.getElementById('faq-search');
if (search) {
  const list = document.querySelector('.faq');
  const items = [...list.querySelectorAll('details')];
  const status = document.getElementById('faq-status');
  const STOP = new Set('a an the is are was be it its to do does did i my me you your how why what when where who which can could should would will in on at of for and or with this that there from by as not no get got'.split(' '));
  const stem = (w) => w.replace(/(ing|ed|es|s|er|ers)$/, '').slice(0, 6);
  const raw = (t) => t.toLowerCase().normalize('NFKD').replace(/[̀-ͯ]/g, '')
    .split(/[^a-z0-9]+/).filter((w) => w && !STOP.has(w));
  const words = (t) => raw(t).map(stem).filter((w) => w.length >= 2);
  const both = (t) => [...words(t), ...raw(t).filter((w) => w.length >= 2)];
  const index = items.map((el) => {
    const sum = el.querySelector('summary');
    const q = both(sum.textContent);
    return { el, sum, text: sum.textContent, q, all: new Set([...q, ...both(el.textContent)]) };
  });
  const esc = (t) => t.replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
  // light up the words in a question that match what was typed
  const mark = (it, query, typed) => {
    it.sum.innerHTML = it.text.split(/(\s+)/).map((part) => {
      const w = words(part)[0];
      const r = raw(part)[0];
      return w && [...query, ...typed].some((q) => like(q, w) || (r && like(q, r))) ? `<mark>${esc(part)}</mark>` : esc(part);
    }).join('');
  };
  // letters of the typed word appear in order inside the other word ("wndws" in "windows")
  const inOrder = (w, x) => { let i = 0; for (const c of x) { if (c === w[i]) i += 1; if (i === w.length) return true; } return false; };
  // at most one letter wrong, missing or extra ("blokced", "uninstal")
  const swapped = (a, b) => {
    if (a.length !== b.length) return false;
    const d = [...a].map((c, i) => (c === b[i] ? -1 : i)).filter((i) => i >= 0);
    return d.length === 2 && d[1] === d[0] + 1 && a[d[0]] === b[d[1]] && a[d[1]] === b[d[0]];
  };
  const oneOff = (a, b) => {
    if (swapped(a, b)) return true;
    if (Math.abs(a.length - b.length) > 1) return false;
    let i = 0; let j = 0; let edits = 0;
    while (i < a.length && j < b.length) {
      if (a[i] === b[j]) { i += 1; j += 1; continue; }
      edits += 1; if (edits > 1) return false;
      if (a.length > b.length) i += 1; else if (b.length > a.length) j += 1; else { i += 1; j += 1; }
    }
    return edits + (a.length - i) + (b.length - j) <= 1;
  };
  const like = (w, x) => x === w || x.startsWith(w) || (w.length >= 4 && x.length >= 4 && w.startsWith(x))
    || (w.length >= 3 && w[0] === x[0] && inOrder(w, x)) || (w.length >= 4 && oneOff(w, x.slice(0, Math.max(w.length, 4))));
  const hit = (set, w) => set.has(w) || [...set].some((x) => like(w, x));
  const run = () => {
    const query = [...new Set(words(search.value))];
    const typed = [...new Set(raw(search.value).filter((w) => w.length >= 2))];
    const empty = document.getElementById('faq-empty');
    if (!query.length) {
      index.forEach((it) => { it.el.hidden = false; it.sum.textContent = it.text; list.append(it.el); });
      if (empty) empty.hidden = true;
      status.textContent = '';
      return;
    }
    const need = Math.max(1, Math.ceil(query.length / 2));
    const scored = index.map((it) => {
      const found = (set, i) => hit(set, query[i]) || (typed[i] !== undefined && hit(set, typed[i]));
      const inAll = query.filter((_, i) => found(it.all, i)).length;
      const qs = new Set(it.q);
      const inQ = query.filter((_, i) => found(qs, i)).length;
      return { ...it, ok: inAll >= need, score: inAll * 2 + inQ };
    }).sort((a, b) => b.score - a.score);
    let shown = 0;
    scored.forEach((it, i) => {
      it.el.hidden = !it.ok;
      list.append(it.el); // best matches first
      if (it.ok) { shown += 1; it.el.open = i === 0; mark(it, query, typed); } else { it.sum.textContent = it.text; }
    });
    if (empty) {
      empty.hidden = shown > 0;
      document.getElementById('faq-empty-term').textContent = search.value.trim();
    }
    status.textContent = shown ? `${shown} ${shown === 1 ? 'answer matches' : 'answers match'}, best first.` : '';
  };
  search.addEventListener('input', run);
  search.addEventListener('search', run); // the clear (x) button
  // "Ask this question": copy the search into the form's title and take the visitor there
  document.getElementById('faq-ask')?.addEventListener('click', () => {
    const title = document.getElementById('q-title');
    if (!title) return;
    title.value = search.value.trim().slice(0, 150);
    document.getElementById('ask').scrollIntoView({ behavior: 'smooth', block: 'start' });
    const details = document.getElementById('q-text');
    setTimeout(() => { details.focus({ preventScroll: true }); details.classList.add('flash'); setTimeout(() => details.classList.remove('flash'), 1300); }, 450);
  });
}

/* ---------------------------------------------------------------- question form (Help)
   Posts to the Cloudflare Pages Function at /api/questions (site/functions/api/questions.js). */
const form = document.getElementById('ask-form');
if (form) {
  const status = form.querySelector('.form-status');
  const say = (text, kind = '') => { status.textContent = text; status.className = `form-status ${kind}`; };
  const fields = [...form.querySelectorAll('input:not([name="website"]), textarea')];
  const showErr = (el) => {
    const err = document.getElementById(el.getAttribute('aria-describedby'));
    const ok = el.checkValidity();
    el.toggleAttribute('aria-invalid', !ok);
    if (err) err.hidden = ok;
    return ok;
  };
  fields.forEach((el) => el.addEventListener('input', () => { if (el.hasAttribute('aria-invalid')) showErr(el); }));
  form.addEventListener('submit', async (e) => {
    e.preventDefault();
    const bad = fields.filter((el) => !showErr(el));
    if (bad.length) { say(bad.length === 1 ? 'One field to fix.' : `${bad.length} fields to fix.`, 'bad'); bad[0].focus(); return; }
    const button = form.querySelector('button[type="submit"]');
    button.disabled = true;
    say('Sending…');
    try {
      const res = await fetch('/api/questions', { method: 'POST', body: new FormData(form), headers: { Accept: 'application/json' } });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(data.error || '');
      form.reset();
      say('Your question is in. The answer will appear on this page, or by email if you left one.', 'ok');
    } catch (err) {
      say(err.message || 'Not sent: the question box opens once the site is live on Cloudflare. Your words are still here.', 'bad');
    } finally {
      button.disabled = false;
    }
  });
}

/* ---------------------------------------------------------------- footer year */
document.querySelectorAll('[data-year]').forEach((el) => { el.textContent = String(new Date().getFullYear()); });
