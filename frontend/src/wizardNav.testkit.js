// Walk the discovery wizard to a step, the way a person does — by clicking Continue.
//
// The wizard became three steps (Source and folders → Lifecycle rules → Review and run), so the
// review contract, the metadata-only promise and the run button are no longer on the screen the
// wizard opens on. A dozen existing cases assert things about that content and were written when
// it was all one page.
//
// THEY ARE NOT WEAKENED TO MATCH. Every one of those assertions is still exactly right — that the
// promise is stated before a run, that a failed rule read renders no row rather than "None
// enabled", that an empty narrowing blocks the primary action. What changed is where the user has
// to be standing. So the fix is navigation, not a softer expectation: each case now walks to its
// step first, and a test that stops being able to REACH step 3 fails here, loudly, instead of
// quietly asserting less than it used to.
//
// Clicking the real control rather than reaching into component state is deliberate. `[data-
// wizard-forward]` being disabled is itself a behaviour under test (#502 — an empty folder list
// under "Specific folders" falls through to the whole source), and a helper that set `step`
// directly would sail straight past the gate it exists to respect.

/** The forward control, or null. Exposed so a case can assert on it directly. */
export const forwardBtn = (c) => c.querySelector('button[data-wizard-forward]')
/** The back control — absent on step 1, where the same slot holds Cancel. */
export const backBtn = (c) => c.querySelector('button[data-wizard-back]')

/**
 * Click Continue until the wizard reaches step `n` (1-based).
 *
 * Throws rather than returning quietly when the control is missing or disabled: a helper that gave
 * up silently would leave the caller asserting against step 1's DOM while believing it was on
 * step 3, and every "not present" expectation would pass for the wrong reason.
 */
export async function gotoStep(container, act, n) {
  for (let at = 1; at < n; at += 1) {
    const btn = forwardBtn(container)
    if (!btn) throw new Error(`wizard: no forward control on step ${at} (wanted step ${n})`)
    if (btn.disabled) {
      throw new Error(`wizard: forward blocked on step ${at} — ${btn.title || 'no reason given'}`)
    }
    // eslint-disable-next-line no-await-in-loop
    await act(async () => { btn.click() })
  }
  return container
}

/** The rail's current step title, for a case that wants to prove where it ended up. */
export function currentStepTitle(c) {
  const el = c.querySelector('[aria-current="step"]')
  return el ? el.textContent.replace(/\s*—.*$/, '').trim() : null
}

/**
 * Walk BACK to step 1 by clicking Back, whatever step we are on.
 *
 * Back is deliberately never disabled (see ScanScopeWizard's footer), so this cannot wedge — but
 * it is bounded anyway: a Back button that stopped advancing would otherwise spin forever, and an
 * infinite loop in a test reads as a hung suite rather than as the bug it is.
 */
export async function backToStart(container, act, max = 5) {
  for (let i = 0; i < max; i += 1) {
    const b = backBtn(container)
    if (!b) return container          // step 1: the slot holds Cancel, not Back
    // eslint-disable-next-line no-await-in-loop
    await act(async () => { b.click() })
  }
  throw new Error('wizard: still not at step 1 after ' + max + ' Back clicks')
}
