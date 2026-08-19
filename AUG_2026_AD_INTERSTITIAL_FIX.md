# NYT Ad Interstitial Fix - August 2026

## Problem

Starting approximately 1-2 weeks before August 20, 2026, the daily Wordle
videos produced by this bot were ~33 seconds long and contained NO actual
gameplay. Frame-by-frame analysis of the broken video
(`YTDown.com_YouTube_Wordle-answer-today-August-20-2026-...mp4`) shows:

| Time | Content |
|------|---------|
| 0-5s  | `intro.png` splash (correct) |
| 5-19s | NYT "Subscribe Now" / "Games is included in a Times subscription" ad |
| 19-26s| NYT subscription ad (different banner) |
| 26-33s| `outro.png` splash (correct) |

The Wordle game itself never appears. Letters typed by the bot went into
the void because an ad overlay was intercepting focus.

## Root Cause

NYT introduced a new **"Advertisement" interstitial** that appears
immediately after clicking the Play button on the Wordle landing page.

Diagnostic dump confirms the modal:

```
role="dialog"
aria-label="Advertisement"
class="AdInterstitial-module_modalOverlay__LZ_UW AdInterstitial-module_shortenFadeIn__a..."
z-index: 2000
text: "ADVERTISEMENT" + button "Continue to Wordle"
```

The original script tried to close post-Play modals with these selectors:

```python
page.locator('button[aria-label="Close"]')      # does not exist on this modal
page.locator('[data-testid="close-icon"]')        # does not exist on this modal
```

Neither selector matches the new ad interstitial, so the dismissal logic
silently did nothing. The bot then attempted to type 6 guesses, but the
keystrokes were absorbed by the ad overlay. The Wordle board never
received any letters, `feedback` was always `None`, the loop exited
without solving, and the resulting video was just the ad sandwiched
between intro and outro.

## Fix Applied

### 1. New helper: `dismiss_ad_interstitial(page, max_wait=15, max_retries=3)`

Added at module scope in `script.py`. Detects the
`div[role="dialog"][aria-label="Advertisement"]` modal and clicks the
"Continue to Wordle" button via a layered selector strategy:

1. `page.get_by_role("button", name="Continue to Wordle")` (best)
2. `div[role="dialog"][aria-label="Advertisement"] button:has-text("Continue to Wordle")`
3. `page.get_by_text("Continue to Wordle", exact=True)`
4. JS fallback: enumerate all elements and click any with matching text

Retries up to `max_retries` times if the dialog persists after a click.

### 2. New helper: `wait_for_wordle_board(page, max_wait=15)`

Waits for `div[aria-label^="Row"]` to appear, then verifies that the
keyboard (`button[data-key]`) is present. Returns True only when both
are detected. This catches any future regression where the game board
fails to render (e.g., paywall re-design, JS error, etc.).

### 3. Main flow updated

The section between "Click Play" and the start of the solver loop was
restructured:

```
Click Play button
  ↓
[NEW] dismiss_ad_interstitial(page)            ← dismisses the post-Play ad
  ↓
[NEW] wait_for_wordle_board(page)             ← verifies the game is ready
  ↓
[MOVED] start_trim = time.time() - video_start_time
        ↑ was previously set BEFORE the Play click (so the ad was in the video)
  ↓
Close any legacy "How to Play" / "Stats" modal (unchanged)
  ↓
Solver loop
```

### 4. `clean_up_ui()` now also targets the new modal class

Added CSS rules:

```css
div[role="dialog"][aria-label="Advertisement"],
div[class*="AdInterstitial-module_modalOverlay__"],
div[class*="AdInterstitial-module_shortenFadeIn__"] {
    display: none !important;
    visibility: hidden !important;
}
```

This ensures that if the ad somehow re-appears during gameplay or after
solving, it is visually hidden before the final frames are recorded.

### 5. Proactive CSS injection (`add_init_script`) refined

The previous CSS injection used jQuery-style `:contains()` selectors
inside `:has()` — these are not valid CSS and never actually matched
anything. The legacy `.Modal-module_modalOverlay__eaFhH` rule was
preserved (it does work for that class).

We deliberately do NOT add a global `div[role="dialog"] { display: none }`
rule to the init script, because that would also hide the ad interstitial
**before** it can be dismissed by clicking "Continue to Wordle". A
hidden-but-present overlay would still intercept keyboard focus and
re-introduce the original bug. The ad must be explicitly dismissed, not
merely hidden.

## Verification

A standalone test (`scripts/test_fix.py`, lifted into the repo during
debugging) was used to verify the fix end-to-end:

```
=== Step 2: Click Play button ===
Clicked Play button

=== Step 3: Dismiss Ad Interstitial (THE FIX) ===
  [dismiss_ad] Ad interstitial detected. Attempting to click 'Continue to Wordle'...
  [dismiss_ad] Clicked via role button text
  [dismiss_ad] Ad interstitial dismissed successfully
  dismiss_ad_interstitial returned: True

=== Step 4: Wait for Wordle Board ===
  [wait_board] Wordle board ready: 6 rows, 28 keyboard keys
  Wordle board ready: True
```

After the fix:
- The ad interstitial is dismissed within ~2 seconds of clicking Play.
- The Wordle board (6 rows × 5 tiles, 28-key keyboard) is detected and ready.
- Letters typed via `button[data-key]` are correctly received by the game.
- Feedback is read successfully via `div[data-testid="tile"][data-state]`.

## Files Modified

| File | Change |
|------|--------|
| `script.py` | Added `dismiss_ad_interstitial()` and `wait_for_wordle_board()` helpers; restructured Play→Solver flow; updated `clean_up_ui()` CSS to target `AdInterstitial-module_modalOverlay__`; removed jQuery-style `:contains()` selectors from init-script CSS (they were no-ops). |
| `IMPLEMENTATION_SUMMARY.md` | Existing doc — left untouched (describes the February 2026 popup fix, which is still relevant). |
| `AUG_2026_AD_INTERSTITIAL_FIX.md` | This file. |

## Rollback

If the fix causes issues, revert with:

```bash
git revert HEAD
```

The previous (broken) behavior will be restored. Note that the broken
behavior was the result of an external NYT site change, not a code
regression — reverting will not bring back working videos, it will
simply restore the documented broken state.
