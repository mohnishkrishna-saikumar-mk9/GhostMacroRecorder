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

/* ---------------------------------------------------------------- answer search (Help) */
const search = document.getElementById('faq-search');
if (search) {
  const items = [...document.querySelectorAll('.faq details')];
  const status = document.getElementById('faq-status');
  const norm = (t) => t.toLowerCase().normalize('NFKD').replace(/[̀-ͯ]/g, '');
  const texts = items.map((el) => norm(el.textContent));
  search.addEventListener('input', () => {
    const words = norm(search.value).split(/\s+/).filter(Boolean);
    let shown = 0;
    items.forEach((el, i) => {
      const hit = words.every((w) => texts[i].includes(w));
      el.hidden = !hit;
      if (hit) { shown += 1; if (words.length) el.open = true; }
    });
    status.textContent = !words.length ? '' : shown
      ? `${shown} ${shown === 1 ? 'answer matches' : 'answers match'}.`
      : `No answer matches "${search.value.trim()}". Ask it below and it will be answered.`;
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
