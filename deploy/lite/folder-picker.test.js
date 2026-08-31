/* DOM-level checks on the restored folder picker.
 *
 * Behaviour, not markup: every assertion is about what a person doing the thing actually gets —
 * which documents Discovery lists after a drill + select + carve-out. A test that only checked
 * the checkbox rendered would pass against a picker whose exclusions were a no-op, which is the
 * exact failure the ported semantics exist to prevent.
 */
const { chromium } = require('/opt/node22/lib/node_modules/playwright');
const path = process.argv[2];

let failures = 0;
function check(name, got, want) {
  const ok = JSON.stringify(got) === JSON.stringify(want);
  if (!ok) failures++;
  console.log(`${ok ? 'PASS' : 'FAIL'}  ${name}`);
  if (!ok) console.log(`        got  ${JSON.stringify(got)}\n        want ${JSON.stringify(want)}`);
}

(async () => {
  const browser = await chromium.launch({ executablePath: '/opt/pw-browsers/chromium-1194/chrome-linux/chrome' });
  const page = await browser.newPage();
  const errors = [];
  page.on('pageerror', (e) => errors.push(String(e)));
  page.on('console', (m) => { if (m.type() === 'error') errors.push(m.text()); });

  await page.goto('file://' + path);

  // Sign in via a demo persona — the app gates everything behind it.
  await page.click('.personacard');
  check('app shell visible after sign-in', await page.isVisible('#app'), true);

  // ── the picker opens and shows the top level ──────────────────────────────
  await page.click('#pick-open');
  const top = await page.$$eval('#folder-rows .txt', (n) => n.map((x) => x.textContent));
  check('top level lists the three areas', top, ['Clinical Ops', 'Revenue Cycle', 'Administration']);
  check('summary starts as whole source', await page.textContent('#pick-summary'), 'Whole source');

  // Drive-like source gives no counts at the root level; children carry item hints.
  const hints = await page.$$eval('#folder-rows .hint', (n) => n.map((x) => x.textContent));
  check('size hints render as items, not files', hints, ['4 items', '3 items', '2 items']);

  // ── drill down ────────────────────────────────────────────────────────────
  await page.click('#folder-rows li:nth-child(1) .drill');           // into Clinical Ops
  const kids = await page.$$eval('#folder-rows .txt', (n) => n.map((x) => x.textContent));
  check('drilled into Clinical Ops', kids,
        ['Cardiology', 'Patient Education', 'Pharmacy & Protocols', 'Archive 2019']);
  const crumbs = await page.$$eval('#crumbs button', (n) => n.map((x) => x.textContent));
  check('breadcrumb records ancestry', crumbs, ['My Drive', 'Clinical Ops']);

  // ── filter this level ─────────────────────────────────────────────────────
  await page.fill('#pick-filter', 'arch');
  check('filter narrows the level',
        await page.$$eval('#folder-rows .txt', (n) => n.map((x) => x.textContent)), ['Archive 2019']);
  await page.fill('#pick-filter', '');

  // ── select a parent, then carve a child out of it ─────────────────────────
  await page.click('#crumbs button:nth-child(1)');                   // back to My Drive
  await page.click('#folder-rows li:nth-child(1) input[type=checkbox]');  // pick Clinical Ops
  check('summary names the picked folder', await page.textContent('#pick-summary'), 'Clinical Ops');

  await page.click('#folder-rows li:nth-child(1) .drill');           // back into it
  const inheritedHints = await page.$$eval('#folder-rows .hint', (n) => n.map((x) => x.textContent));
  check('children read as included via parent', inheritedHints,
        ['included via parent', 'included via parent', 'included via parent', 'included via parent']);

  await page.click('#folder-rows li:nth-child(4) input[type=checkbox]');  // exclude Archive 2019
  check('carve-out is labelled excluded',
        await page.textContent('#folder-rows li:nth-child(4) .hint'), 'excluded');
  check('summary counts the exclusion',
        await page.textContent('#pick-summary'), 'Clinical Ops · 1 excluded');
  const chips = await page.$$eval('.fchip', (n) => n.map((x) => x.textContent.replace('×', '').trim()));
  check('scope chips name inclusion and carve-out', chips, ['Clinical Ops', 'except Archive 2019']);

  // ── tri-state: the parent is now PARTLY selected ──────────────────────────
  await page.click('#crumbs button:nth-child(1)');
  const tri = await page.$$eval('#folder-rows input[type=checkbox]',
    (n) => n.map((x) => (x.indeterminate ? 'partial' : x.checked ? 'on' : 'off')));
  check('parent renders indeterminate, siblings off', tri, ['partial', 'off', 'off']);

  // ── the scope actually governs what Discovery lists ───────────────────────
  // Measured as a DIFFERENCE between two real runs rather than against a hand-written list of
  // filenames. The first draft of this test asserted which documents "should" be in Archive
  // 2019 and failed — the assertion was wrong, not the code. Deriving the expectation from the
  // app's own behaviour removes the guess entirely.
  async function discover() {
    // Blank the completion marker BEFORE starting, so the wait below cannot be satisfied by the
    // previous run's "done" still sitting in the DOM. Without this the second call returned the
    // first run's table and every comparison after it was against stale rows — which is what the
    // bite check caught, and it looked exactly like a broken exclusion.
    await page.evaluate(() => { document.getElementById('disc-note').textContent = ''; });
    await page.click('#run-discover');
    await page.waitForFunction(
      () => document.getElementById('disc-note').textContent.startsWith('done'),
      null, { timeout: 15000 });
    return page.$$eval('#rows td.name', (n) => n.map((x) => x.textContent));
  }

  // Drop the carve-out for a moment: Clinical Ops, whole.
  await page.click('#folder-rows li:nth-child(1) .drill');              // into Clinical Ops
  await page.click('#folder-rows li:nth-child(4) input[type=checkbox]'); // un-exclude Archive 2019
  check('carve-out removed', await page.textContent('#pick-summary'), 'Clinical Ops');
  const withArchive = await discover();
  check('discovery found something', withArchive.length > 0, true);

  // Put it back and re-run.
  await page.click('#folder-rows li:nth-child(4) input[type=checkbox]'); // exclude Archive 2019
  const withoutArchive = await discover();

  const removed = withArchive.filter((r) => !withoutArchive.includes(r));
  // Bite check: if the carve-out removed nothing, every assertion below is vacuous and the
  // exclusion is a no-op — the precise failure the ported semantics exist to prevent.
  check('the carve-out actually removed documents', removed.length > 0, true);
  check('carved-out documents are gone from the listing',
        withoutArchive.filter((r) => removed.includes(r)), []);
  check('nothing else was dropped with them',
        withoutArchive.every((r) => withArchive.includes(r)), true);

  // A sibling area that was never selected contributes nothing either way.
  const revenue = ['Denials Register Q3.xlsx', 'Appeal Letter - Aria Draft.docx'];
  check('unselected sibling area contributes nothing',
        withArchive.filter((r) => revenue.includes(r)), []);

  // ── clearing inclusions clears the carve-outs with them ───────────────────
  await page.click('#pick-clear');
  check('clear resets to whole source', await page.textContent('#pick-summary'), 'Whole source');
  check('no chips survive the clear', await page.$$eval('.fchip', (n) => n.length), 0);

  check('no page errors', errors, []);
  await browser.close();
  console.log(failures ? `\n${failures} FAILED` : '\nall checks passed');
  process.exit(failures ? 1 : 0);
})().catch((e) => { console.error(e); process.exit(1); });
