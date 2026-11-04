"""V1-37: the Star-Whale comes back (02 §7.2, shared with V1-35's finale).

After the finale, the Celestial Star-Whale is a witnessed legendary that can be seen again:
on a clear Nebula night inside its window, with the Skipper anchored and still by the calm
reflection (V1-36's `star_whale` requirements), and not yet seen this game week.
- **Waiting.** Once every requirement holds, `WAIT_S` real seconds of stillness bring it up.
  Moving resets the wait.
- **The rise.** It uses the finale's staging (`staging.PLAY_STAGES["whale_return"]`). It rises
  out of the water ahead on the same curve as `story_c5_whale`, holds, then sinks as it does
  after "Draw it". The view lifts with it under a letterbox, and the HUD steps aside.
- **The record.** It is written when the whale has fully risen with the Skipper still there:
  a witnessed record on its page, once a week (`legendary.record_witnessed`). Moving off
  before that lets it sink early, unrecorded.
- **Skipping.** Every return is a repeat of the finale, so Esc (B) skips to its end and
  records it.
- **Reduced Motion** shows it risen and still throughout, and the camera holds.
"""

from __future__ import annotations

WAIT_S = 15.0     # real seconds of stillness before it rises, as long as Settle In's first cue
RISEN_S = 8.5     # the staging's time when it has fully risen: the sighting is recorded


def can_return(state, world) -> bool:
    """Every requirement holds for a return sighting right now."""
    from . import legendary
    from .quests import scene_state
    if world.id != "nebula" or scene_state(state, "story_c5_whale") != "done":
        return False
    if legendary.caught_this_week(state, "star_whale"):
        return False
    return bool(legendary.evaluate_requirements(state, "star_whale", world=world)["met"])


def settled(state, world) -> bool:
    from .story import settle_near
    return bool(state.anchored and abs(state.speed) < 0.1 and settle_near(state, world))


def record(state, world) -> bool:
    """Write the sighting to its page, once a week."""
    from . import legendary
    if legendary.caught_this_week(state, "star_whale"):
        return False
    if not legendary.record_witnessed(state, "star_whale", world):
        return False
    state.toast("The Star-Whale came back. The book has it.")
    return True
