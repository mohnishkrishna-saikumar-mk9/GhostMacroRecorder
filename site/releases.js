// Keeps the page in step with GitHub Releases: the version line in the hero, the installer size in the
// close, and the release notes list. The HTML already holds the current values, so the page reads right
// without this script or when GitHub's API is unreachable (60 requests an hour per visitor IP).
const REPO = 'mohnishkrishna-saikumar-mk9/GhostMacroRecorder';
const ASSET = 'GhostMacroRecorder-Setup.exe';
const SHOW = 3;

const fmtDate = (iso) =>
  new Date(iso).toLocaleDateString('en-GB', { day: 'numeric', month: 'short', year: 'numeric' });
const fmtMB = (bytes) => `${(bytes / 1e6).toFixed(1)} MB`;

// Release notes come from the tag message (see .github/workflows/release.yml). GitHub's generated
// "Full Changelog" line and headings are dropped; the first two plain lines are kept.
function notesOf(body) {
  return (body || '')
    .split('\n')
    .map((l) => l.replace(/^[#>*\-\s]+/, '').trim())
    .filter((l) => l && !/^full changelog|^what's changed|^new contributors|^\*\*full/i.test(l))
    .slice(0, 2)
    .join(' ');
}

async function main() {
  let releases;
  try {
    const res = await fetch(`https://api.github.com/repos/${REPO}/releases?per_page=${SHOW}`, {
      headers: { Accept: 'application/vnd.github+json' },
    });
    if (!res.ok) return;
    releases = (await res.json()).filter((r) => !r.draft && !r.prerelease);
  } catch {
    return;
  }
  if (!releases.length) return;

  const latest = releases[0];
  const version = latest.tag_name.replace(/^v/, '');
  const asset = latest.assets.find((a) => a.name === ASSET) || latest.assets[0];

  const line = document.querySelector('[data-latest-line]');
  if (line) line.textContent = `Version ${version}, free for Windows 10 and 11`;
  const closeLine = document.querySelector('#close-h + .t-lead');
  if (closeLine && asset) closeLine.textContent = `Free, ${fmtMB(asset.size)}, for Windows 10 and 11.`;

  const list = document.querySelector('[data-releases]');
  if (!list) return;
  const known = new Map([...list.querySelectorAll('li')].map((li) => [
    li.querySelector('.rel__tag')?.textContent.trim(),
    li.querySelector('.rel__notes')?.textContent.trim(),
  ]));
  list.replaceChildren(...releases.map((r) => {
    const li = document.createElement('li');
    const tag = Object.assign(document.createElement('span'), { className: 'rel__tag', textContent: r.tag_name });
    const date = Object.assign(document.createElement('span'), { className: 'rel__date', textContent: fmtDate(r.published_at) });
    const link = Object.assign(document.createElement('a'), {
      className: 'link', href: r.html_url, textContent: `Get ${r.tag_name}`,
    });
    li.append(tag, date, link);
    const text = notesOf(r.body) || known.get(r.tag_name) || '';
    if (text) li.append(Object.assign(document.createElement('p'), { className: 'rel__notes', textContent: text }));
    return li;
  }));
}

main();
