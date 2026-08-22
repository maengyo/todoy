"""macOS overlay backend: a wandering character with a reminder speech bubble.

Built on AppKit/pyobjc. This module is imported lazily -- only by
`todoy.display.overlay.base.create_backend()` once it has confirmed
`sys.platform == "darwin"` and that `AppKit` is importable -- so importing
`todoy.display.overlay` (or running the test suite) never requires pyobjc.

All AppKit calls happen on the main thread: `MacOSOverlayBackend.run()` is
expected to be called from the main thread, and every NSTimer callback below
runs on the main run loop by construction (no background threads are used).
"""

from __future__ import annotations

import math
import time
from contextlib import contextmanager
from typing import TYPE_CHECKING

import AppKit
import Foundation
import objc

from todoy.display import sanitize_text
from todoy.display.overlay.animations import GALLOP_HOP_PEAK_HEIGHT_PX, CharacterMovement
from todoy.display.overlay.core import (
    AlarmClock,
    build_alarm_flag_line,
    build_alarm_text,
    build_flag_line,
)
from todoy.display.overlay.personas import EntranceAnimation, FlourishAnimation, persona
from todoy.display.overlay.spritestate import (
    DEFAULT_USER_SPRITE_STRIDE_PX_PER_CYCLE,
    SPRITE_CODE_SCALE,
    SPRITE_IDLE_FPS,
    SPRITE_JUMP_FPS,
    SPRITE_STATES,
    SPRITE_WAVE_FPS,
    fit_code_sprite_scale,
    fit_scale_to_max_height,
    parse_palette_color,
    scan_user_sprite_state_files,
    sprite_frames_for_state,
    sprite_movement_hop_peak_px,
    sprite_state_for_tick,
    sprite_time_frame_index,
    sprite_walk_frame_index,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator
    from pathlib import Path

    from todoy.display.overlay.base import OverlayOptions, PanelActions
    from todoy.display.overlay.core import ReminderScheduler
    from todoy.display.overlay.personas import Persona
    from todoy.models import Todo

# --- tunables ----------------------------------------------------------------

FIRST_FIRE_DELAY_SECONDS = 5.0
WANDER_TICK_SECONDS = 1.0 / 30.0  # 30fps (M12 Task 29): smooth motion + squash-stretch
REMINDER_CHECK_INTERVAL_SECONDS = 1.0
BUBBLE_AUTO_HIDE_SECONDS = 30.0
BUBBLE_EFFECT_DURATION_SECONDS = 0.22  # pop/fade/slide entrance animations
BUBBLE_SHAKE_OSCILLATIONS = 3
BUBBLE_SHAKE_AMPLITUDE_PX = 8.0
BUBBLE_SHAKE_STEP_SECONDS = 0.04
BUBBLE_SLIDE_RISE_PX = 20.0

CHARACTER_MAX_IMAGE_PX = 96.0
CHARACTER_WINDOW_SIZE = 110.0
EMOJI_FONT_SIZE = 64.0
CHARACTER_BOTTOM_MARGIN = 24.0

# --- animated sprite characters (M14 Task 35) ---------------------------------
#
# Two independent sprite sources, resolved in `_OverlayController.
# _load_character_sprite` (most-specific-wins order): a user-supplied PNG
# folder (`options.sprite_folder`) beats a built-in code pixel-art pack
# (`options.sprite_name`, looked up in `todoy.display.pixelart` -- Task 34,
# a pure/stdlib module imported lazily below so this file never hard-depends
# on it existing/being importable), which beats the pre-existing static
# `character_image`, which beats the emoji glyph -- every fallback rung
# below it is completely unchanged, so a character with no sprite behaves
# exactly as before (contract: "no regressions for emoji characters").
#
# All the pure state-selection/frame-index/scale-fitting logic (constants
# included: `SPRITE_STATES`, `SPRITE_CODE_SCALE`, etc.) lives in
# `todoy.display.overlay.spritestate` (Codex review follow-up: it used to
# be inline here, but that meant its tests sat behind this module's AppKit
# skip gate and never ran on non-macOS CI) -- imported above. Only the
# AppKit-touching parts stay in this file: `_render_pixel_grid` (building
# the actual `NSImage`s) and `_OverlayController`'s wiring of it all into
# the window/view/timers.
#
# Sky zone (M13 Task 32): sky personas (persona.zone == "sky") cruise near
# the TOP of the screen instead of the bottom -- the screen's actual menu
# bar/notch clearance (`_OverlayController._sky_top_margin`, derived from
# `NSScreen.frame()` vs `visibleFrame()` -- Codex review follow-up: this
# used to be a hardcoded 24px guess, which undershoots on a notched
# MacBook or overshoots on an external display with no menu bar) plus a
# small fixed buffer, so the character never overlaps the menu bar. The
# movement preset's y_offset (normally a "lift up" amount for ground/water)
# is applied DOWNWARD from this cruise line instead, per contract section 2.
MENU_BAR_HEIGHT_PX = 24.0  # fallback only, when a screen can't be queried at all
SKY_TOP_BUFFER_PX = 8.0

# Gallop-only squash-stretch (M11 Task 28): a subtle vertical scale synced to
# the bounce phase (`y_offset`, 0..GALLOP_HOP_PEAK_HEIGHT_PX) -- stretched
# tall near the top of each beat, squashed at ground contact. Applied on top
# of the horizontal mirror flip in `_CharacterView.drawRect_`; every other
# movement keeps `squash_scale` pinned at 1.0.
GALLOP_SQUASH_SCALE_MIN = 0.95
GALLOP_SQUASH_SCALE_MAX = 1.05

BUBBLE_WIDTH = 320.0
# Deliberately NOT shrunk by the UI-polish compaction below: measured
# against `_build_reminder_attributed_text`'s real `boundingRectWithSize_
# options_` at BUBBLE_WIDTH, a common case (5 todos with reasonably
# descriptive text) already needs ~125-143px depending on which taunt gets
# picked (some wrap to 2 lines) -- shrinking this constant further clips
# real content, which the compaction's own "same content" goal rules out.
# All the actual height savings come from BUBBLE_PADDING/BUBBLE_BUTTON_ROW_
# HEIGHT/the taunt font below instead.
BUBBLE_TEXT_HEIGHT = 132.0
# UI-polish compaction (user feedback: "the bubble panel is too tall and
# the buttons are too big"): padding trimmed 18->12px, tighter line
# spacing in `_build_reminder_attributed_text`, and a smaller button row
# (below) -- together a visibly shorter panel with the same content.
BUBBLE_PADDING = 12.0
BUBBLE_GAP_ABOVE_CHARACTER = 6.0
# Sky zone (M13 Task 32): the bubble message style goes BELOW a sky
# character instead of above it (contract section 2) -- symmetric gap.
BUBBLE_GAP_BELOW_CHARACTER = 6.0

PANEL_CORNER_RADIUS = 16.0
PANEL_FILL_ALPHA = 0.97
PANEL_BORDER_ALPHA = 0.55

# A real drawn speech-bubble tail (NSBezierPath), pointing straight down at
# the character below. The window is taller than the panel by the tail's
# height; the panel occupies the top `BUBBLE_HEIGHT` px, the tail the bottom
# strip, centered on the panel's (and the character's) x.
BUBBLE_TAIL_HEIGHT = 12.0
BUBBLE_TAIL_WIDTH = 22.0

# Buttons: Snooze is the prominent accent action, Quit is a quiet text button.
# (`bubble` message style only -- `flag` below has no buttons at all.)
# UI-polish compaction: height trimmed 30->24px (still a comfortably
# tappable click target for a mouse-driven desktop control) with a smaller
# corner radius to match, and the button-row block below is now derived
# from BUTTON_HEIGHT plus a small breathing-room gap rather than a
# standalone magic number, so it shrinks along with the buttons.
BUTTON_HEIGHT = 24.0
BUBBLE_BUTTON_GAP_ABOVE = 8.0
BUBBLE_BUTTON_ROW_HEIGHT = BUTTON_HEIGHT + BUBBLE_BUTTON_GAP_ABOVE
BUBBLE_HEIGHT = BUBBLE_TEXT_HEIGHT + BUBBLE_BUTTON_ROW_HEIGHT + BUBBLE_PADDING * 2
BUTTON_CORNER_RADIUS = 7.0
SNOOZE_BUTTON_WIDTH = 140.0
QUIT_BUTTON_WIDTH = 76.0

# `flag` message style: NOT the bubble's panel content -- a small, single-
# line pennant (no buttons, no wrapping) with a real swallow-tail notch cut
# into its right edge, flying from a thin pole drawn inside the view's left
# edge that visually connects down toward the character it rides next to.
# The window is taller than the panel by the pole's height; the panel
# occupies the top `FLAG_PANEL_HEIGHT` px, the pole the bottom strip. Width
# is computed per-fire from the rendered text (see `_build_flag_window`),
# clamped to [FLAG_MIN_WIDTH, FLAG_MAX_WIDTH].
FLAG_PANEL_HEIGHT = 34.0
FLAG_CORNER_RADIUS = 8.0
FLAG_TEXT_FONT_SIZE = 13.0
FLAG_TEXT_PADDING_LEFT = 12.0
FLAG_TEXT_PADDING_RIGHT = 10.0
FLAG_MIN_WIDTH = 96.0
# The widest text `core.build_flag_line`/`build_alarm_flag_line` can ever
# legally produce is bounded at `core.FLAG_LINE_MAX_WIDTH` (38) *display*
# columns, but that bound says nothing about *pixels* -- a run of narrow
# glyphs that each still render wide in the system font (e.g. "%" at 13pt
# semibold) can measure well over 400px. An exhaustive scan of every
# printable-ASCII single-character repeat through both builders/both
# languages measured a worst case of ~435px of text alone (`⏰ 23:59` plus
# 28 "%"s, truncated) -- plus `FLAG_TEXT_PADDING_LEFT` + `_RIGHT` + the
# notch's `FLAG_NOTCH_DEPTH` puts the true worst-case content width at
# ~464px. `FLAG_MAX_WIDTH` must stay comfortably above that (regression-
# tested in `test_overlay_base.py`'s widest-legal-line scan) or the widest
# legal lines get their text clamped narrower than they need and visually
# overflow past the pennant's right edge.
FLAG_MAX_WIDTH = 500.0
FLAG_POLE_HEIGHT = 20.0
FLAG_POLE_WIDTH = 3.0
FLAG_POLE_INSET = 7.0
FLAG_GAP_ABOVE_CHARACTER = 2.0
FLAG_NOTCH_DEPTH = 7.0
FLAG_NOTCH_HEIGHT = 12.0
# The notch sits at the panel's vertical midpoint -- there's no button row
# to dodge on this compact style, unlike the bubble's tail-in-the-corner.
FLAG_NOTCH_OFFSET_FROM_PANEL_BOTTOM = FLAG_PANEL_HEIGHT / 2.0
FLAG_AUTO_HIDE_SECONDS = 10.0  # shorter than the bubble's 30s -- a glance, not a read

# Banner style (M13 Task 32, persona.banner True): the message panel hangs
# BELOW the character instead of riding the pole above it -- two thin string
# lines from the character's feet down to the panel's top corners, like a
# banner towed by a plane. Reuses most of `flag`'s panel geometry/flutter
# (FLAG_PANEL_HEIGHT, FLAG_CORNER_RADIUS, FLAG_NOTCH_*, FLAG_TEXT_*,
# FLAG_MIN_WIDTH/FLAG_MAX_WIDTH) -- only the string area above the panel and
# the below-character gap are banner-specific.
BANNER_STRING_HEIGHT_PX = 26.0
BANNER_STRING_INSET_PX = 18.0
BANNER_GAP_BELOW_CHARACTER = 2.0
# Codex review follow-up: the two strings used to both start from a single
# top-center point (a "V"), reading more like one string forking than two
# separate strings. Per the contract's visual intent ("two thin string
# lines from the character's feet"), they instead start from two spread
# points -- roughly the character's left/right foot -- symmetric around
# the window's horizontal center (where `_compute_message_origin` centers
# the banner under the character).
BANNER_FOOT_SPREAD_PX = 24.0

# Flutter: a small periodic "wind" wave in the pennant's swallow-tail notch
# depth while the flag is on screen -- kept to a small amplitude so it reads
# as gentle wind, not a glitch.
FLAG_FLUTTER_FREQUENCY_HZ = 6.0
FLAG_FLUTTER_AMPLITUDE_PX = 2.5
FLAG_FLUTTER_STEP_SECONDS = 1.0 / 30.0

# --- menu-bar quick-add panel -------------------------------------------------
#
# A borderless, non-activating NSPanel anchored under the NSStatusItem
# button. Laid out top-down (its content view and the list's document view
# both `isFlipped()`), unlike the bubble/flag windows above.

QUICKADD_PANEL_WIDTH = 320.0
QUICKADD_PANEL_PADDING = 16.0
QUICKADD_ROW_HEIGHT = 26.0
QUICKADD_ROW_GAP = 6.0
QUICKADD_TIME_FIELD_WIDTH = 64.0
QUICKADD_ADD_BUTTON_WIDTH = 52.0
QUICKADD_ERROR_HEIGHT = 16.0
QUICKADD_SECTION_LABEL_HEIGHT = 16.0
QUICKADD_SEPARATOR_HEIGHT = 1.0
QUICKADD_LIST_ROW_HEIGHT = 24.0
QUICKADD_LIST_VISIBLE_ROWS = 6
QUICKADD_LIST_VISIBLE_HEIGHT = QUICKADD_LIST_ROW_HEIGHT * QUICKADD_LIST_VISIBLE_ROWS
QUICKADD_ROW_BUTTON_SIZE = 20.0
QUICKADD_PANEL_GAP_BELOW_STATUS_ITEM = 4.0


class MacOSOverlayBackend:
    """AppKit-based `OverlayBackend`: floating character + reminder bubble."""

    def run(
        self,
        options: OverlayOptions,
        scheduler: ReminderScheduler,
        get_reminder_text: Callable[[], str],
        get_todos: Callable[[], list[Todo]],
        actions: PanelActions,
    ) -> int:
        app = AppKit.NSApplication.sharedApplication()
        app.setActivationPolicy_(AppKit.NSApplicationActivationPolicyAccessory)

        controller = _OverlayController.alloc().init()
        controller.configure(options, scheduler, get_reminder_text, get_todos, actions, app)
        controller.start()

        # `self` stays on the stack for the whole blocking app.run() call
        # below, which keeps `controller` (and its timers/windows) alive.
        self._controller = controller

        app.run()
        return 0


class _OverlayController(AppKit.NSObject):
    """Owns the character window, bubble window, and all NSTimers."""

    @objc.python_method
    def configure(
        self,
        options: OverlayOptions,
        scheduler: ReminderScheduler,
        get_reminder_text: Callable[[], str],
        get_todos: Callable[[], list[Todo]],
        actions: PanelActions,
        app: AppKit.NSApplication,
    ) -> _OverlayController:
        self.options = options
        self.scheduler = scheduler
        self.get_reminder_text = get_reminder_text
        self.get_todos = get_todos
        self.actions = actions
        self.alarm_clock = AlarmClock(scheduler.snooze_minutes)
        # This character's nature (M13 Task 31/32): zone, launch entrance,
        # fire-time flourish, banner-below message style, default movement --
        # looked up once here and never re-derived, so it's stable for the
        # life of this controller even if `todoy.display.overlay.personas`'s
        # catalog changes between runs.
        self.persona: Persona = persona(self.options.character.name)
        # Launch-entrance curve, driven a tick at a time from `onWanderTick_`
        # (the same 30fps timer that drives normal wandering -- see the
        # class docstring there) -- `None` once finished, at which point
        # `onWanderTick_` falls through to normal `CharacterMovement.step`.
        self.entrance: EntranceAnimation | None = None
        # Fire-time flourish curve, started additively by `_show_message`
        # (see `_start_flourish`) and likewise driven from `onWanderTick_`;
        # `None` when idle/finished. Deliberately does not preempt an
        # in-progress entrance (see `_start_flourish`) -- non-disruptive per
        # contract section 2.
        self.flourish: FlourishAnimation | None = None
        # True when a fire happened while the launch entrance was still in
        # progress -- `onWanderTick_` starts the deferred flourish the
        # instant the entrance finishes (see `_start_flourish`). One slot
        # is enough: a second fire before the entrance finishes just keeps
        # this True (same persona.flourish kind every time, so there is
        # nothing distinct to queue).
        self._pending_flourish = False
        # Whether the bubble currently on screen is an alarm (vs. the regular
        # interval reminder) -- decides what Snooze re-arms.
        self._showing_alarm = False
        self.app = app
        self.movement: CharacterMovement | None = None
        self.char_window: AppKit.NSWindow | None = None
        self.char_view: _CharacterView | None = None
        self.bubble_window: AppKit.NSWindow | None = None
        self.bubble_text_field: AppKit.NSTextField | None = None
        # Set only while a `flag`-style message window is on screen (rebuilt
        # fresh -- see `_build_flag_window` -- each time one fires, since its
        # width depends on that fire's text); `None` for `bubble`.
        self.flag_view: _FlagPanelView | _BannerPanelView | None = None
        self.hide_timer: AppKit.NSTimer | None = None
        self.shake_timer: AppKit.NSTimer | None = None
        # `flag`-only: drives the pennant's periodic "wind" flutter while it
        # is visible -- see `_start_flutter`/`_apply_flutter_frame`.
        self.flutter_timer: AppKit.NSTimer | None = None
        self._flutter_start: float = 0.0
        # `_message_base_origin` is where the message window rests with no
        # shake applied: for `flag`, refreshed every wander tick so it rides
        # along with the character; for `bubble`, set once at show time and
        # left alone (stays put until hidden), per the message-style contract.
        self._message_base_origin: AppKit.NSPoint | None = None
        # Current shake wiggle, added on top of `_message_base_origin` when
        # painting the window -- 0.0 when no shake is in progress. Keeping
        # this as an *offset* (rather than a stored absolute point to shake
        # around and restore to) lets a `flag` shake continue riding along
        # with a moving character instead of snapping back to a stale spot.
        self._shake_offset_px = 0.0
        self._shake_step_index = 0
        self.wander_timer: AppKit.NSTimer | None = None
        self.reminder_timer: AppKit.NSTimer | None = None
        self.first_fire_timer: AppKit.NSTimer | None = None
        self.test_timeout_timer: AppKit.NSTimer | None = None

        # --- menu-bar quick-add panel state ---------------------------------
        self.status_item: AppKit.NSStatusItem | None = None
        # Right-click (or control-click) menu on the status item -- just
        # "Quit todoy", reachable in both message styles; left-click keeps
        # toggling the quick-add panel below (see `onStatusItemClicked_`).
        self.status_menu: AppKit.NSMenu | None = None
        self.panel_window: _PanelWindow | None = None
        self.panel_text_field: AppKit.NSTextField | None = None
        self.panel_time_field: AppKit.NSTextField | None = None
        self.panel_error_label: AppKit.NSTextField | None = None
        self.panel_list_view: _FlippedListView | None = None
        self._panel_todos: list[Todo] = []
        self._panel_list_width = 0.0
        return self

    @objc.python_method
    def start(self) -> None:
        self._build_character_window()
        self._build_status_item()
        self.wander_timer = (
            AppKit.NSTimer.scheduledTimerWithTimeInterval_target_selector_userInfo_repeats_(
                WANDER_TICK_SECONDS, self, "onWanderTick:", None, True
            )
        )
        self.reminder_timer = (
            AppKit.NSTimer.scheduledTimerWithTimeInterval_target_selector_userInfo_repeats_(
                REMINDER_CHECK_INTERVAL_SECONDS, self, "onReminderTick:", None, True
            )
        )
        self.first_fire_timer = (
            AppKit.NSTimer.scheduledTimerWithTimeInterval_target_selector_userInfo_repeats_(
                FIRST_FIRE_DELAY_SECONDS, self, "onFirstFire:", None, False
            )
        )
        if self.options.test_seconds is not None:
            self.test_timeout_timer = (
                AppKit.NSTimer.scheduledTimerWithTimeInterval_target_selector_userInfo_repeats_(
                    self.options.test_seconds, self, "onTestTimeout:", None, False
                )
            )

    # --- window construction --------------------------------------------

    @objc.python_method
    def _screen_frame(self) -> AppKit.NSRect:
        screen = AppKit.NSScreen.mainScreen()
        return screen.frame() if screen is not None else Foundation.NSMakeRect(0, 0, 1440, 900)

    @objc.python_method
    def _sky_top_margin(self) -> float:
        """Clearance to keep between a sky persona's cruise line and the
        very top of the screen: the screen's real menu bar/notch height
        (Codex review follow-up, M13 Task 32 -- `_menu_bar_clearance_px`
        derived from the actual `NSScreen.frame()` vs `visibleFrame()`,
        replacing a hardcoded 24px guess that undershoots a notched
        display's menu bar and overshoots a display with none) plus a
        small fixed buffer. Falls back to `MENU_BAR_HEIGHT_PX` only when no
        screen can be queried, or the two frames don't actually indicate
        any top inset.
        """
        screen = AppKit.NSScreen.mainScreen()
        if screen is None:
            clearance = MENU_BAR_HEIGHT_PX
        else:
            clearance = _menu_bar_clearance_px(screen.frame(), screen.visibleFrame())
            if clearance <= 0.0:
                clearance = MENU_BAR_HEIGHT_PX
        return clearance + SKY_TOP_BUFFER_PX

    @objc.python_method
    def _character_zone_y(self, screen_frame: AppKit.NSRect, y_offset: float) -> float:
        """Baseline y-origin for the character window given the movement
        preset's `y_offset` for this tick (M13 Task 32, contract section 2).

        `ground`/`water` personas rest at the bottom edge with `y_offset`
        lifting UP from it -- unchanged pre-M13 behavior. `sky` personas
        instead cruise near the TOP of the screen (the real menu bar/notch
        clearance -- see `_sky_top_margin` -- plus a small buffer), with
        `y_offset` applied DOWNWARD from that cruise line, so their
        movement preset's bob reads as a gentle dip rather than pushing
        them into the menu bar.
        """
        if self.persona.zone == "sky":
            cruise_y = (
                screen_frame.origin.y
                + screen_frame.size.height
                - CHARACTER_WINDOW_SIZE
                - self._sky_top_margin()
            )
            return cruise_y - y_offset
        return screen_frame.origin.y + CHARACTER_BOTTOM_MARGIN + y_offset

    @objc.python_method
    def _build_character_window(self) -> None:
        screen_frame = self._screen_frame()
        size = CHARACTER_WINDOW_SIZE
        travel_width = max(0.0, screen_frame.size.width - size)
        self.movement = CharacterMovement(self.options.movement, travel_width=travel_width)

        x, y_offset = self.movement.step(0.0)

        # Launch entrance (M13 Task 32): sampled once here at t=0 so the
        # window's very first paint already shows the entrance's starting
        # pose (e.g. materialize's alpha 0, splash's below-baseline y)
        # instead of flashing the resting pose for one frame before the
        # first `onWanderTick_` tick picks it up.
        entrance = EntranceAnimation(self.persona.entrance, char_height=CHARACTER_WINDOW_SIZE)
        ex, ey, alpha, scale = entrance.step(0.0)
        self.entrance = None if entrance.finished else entrance

        start_x = screen_frame.origin.x + x + ex
        start_y = self._character_zone_y(screen_frame, y_offset) + ey
        frame = Foundation.NSMakeRect(start_x, start_y, size, size)

        window = AppKit.NSPanel.alloc().initWithContentRect_styleMask_backing_defer_(
            frame,
            AppKit.NSWindowStyleMaskBorderless | AppKit.NSWindowStyleMaskNonactivatingPanel,
            AppKit.NSBackingStoreBuffered,
            False,
        )
        window.setOpaque_(False)
        window.setBackgroundColor_(AppKit.NSColor.clearColor())
        window.setHasShadow_(False)
        window.setLevel_(AppKit.NSFloatingWindowLevel)
        window.setIgnoresMouseEvents_(False)
        window.setAlphaValue_(alpha)
        window.setCollectionBehavior_(
            AppKit.NSWindowCollectionBehaviorCanJoinAllSpaces
            | AppKit.NSWindowCollectionBehaviorStationary
        )

        content_view = _CharacterView.alloc().initWithFrame_(
            Foundation.NSMakeRect(0, 0, size, size)
        )
        content_view.controller = self
        content_view.set_image(self._load_character_image())
        content_view.emoji = self.options.character.emoji

        # Sprite animation clock/odometer (M14 Task 35): `_sprite_prev_x`
        # seeds from this same t=0 `x` so the very first `onWanderTick_`
        # call computes a correct (zero, unless movement is already in
        # motion at t=0 -- it never is, `step(0.0)` above is a no-op)
        # dx/distance delta instead of spuriously counting the character's
        # full starting offset as "distance walked". `_sprite_stride_px_
        # per_cycle`/`_sprite_draw_scale` are only meaningful once a sprite
        # actually loads below; 0.0/1.0 make `sprite_walk_frame_index` a
        # harmless no-op (always frame 0) if `_advance_sprite_animation`
        # were ever called with no sprite loaded (it isn't -- guarded by
        # `content_view.sprite_frames is None` -- but 0.0/1.0 keep it inert
        # regardless).
        self._sprite_distance_px = 0.0
        self._sprite_time = 0.0
        self._sprite_prev_x = x
        self._sprite_stride_px_per_cycle = 0.0
        self._sprite_draw_scale = 1.0
        loaded_sprite = self._load_character_sprite()
        if loaded_sprite is not None:
            frames, stride_px_per_cycle, draw_scale, pixel_perfect = loaded_sprite
            content_view.sprite_frames = frames
            content_view.sprite_pixel_perfect = pixel_perfect
            self._sprite_stride_px_per_cycle = stride_px_per_cycle
            self._sprite_draw_scale = draw_scale

        window.setContentView_(content_view)
        window.orderFrontRegardless()

        self.char_window = window
        self.char_view = content_view
        self._apply_character_orientation(y_offset, extra_scale=scale)
        self._advance_sprite_animation(x, y_offset)

    @objc.python_method
    def _load_character_image(self) -> AppKit.NSImage | None:
        path: Path | None = self.options.character_image
        if path is None:
            return None
        try:
            if not path.is_file():
                return None
            image = AppKit.NSImage.alloc().initWithContentsOfFile_(str(path))
        except OSError:
            return None
        if image is None:
            return None

        w, h = image.size().width, image.size().height
        if w <= 0 or h <= 0:
            return None
        scale = min(CHARACTER_MAX_IMAGE_PX / w, CHARACTER_MAX_IMAGE_PX / h, 1.0)
        image.setSize_(Foundation.NSMakeSize(w * scale, h * scale))
        return image

    @objc.python_method
    def _load_character_sprite(
        self,
    ) -> tuple[dict[str, list[AppKit.NSImage]], float, float, bool] | None:
        """Resolve this run's animated sprite source, if any (M14 Task 35,
        contract section 3): `(frames, stride_px_per_cycle, draw_scale,
        pixel_perfect)`, or `None` if neither source applies/loads -- the
        caller (`_build_character_window`) then leaves `content_view.
        sprite_frames` at its `None` default, so `_draw_content` falls
        through to `character_image`/emoji exactly as before this feature
        existed. Most-specific-wins order (see the module-level comment
        above `SPRITE_STATES`): `options.sprite_folder` (user PNGs) before
        `options.sprite_name` (a catalog character's built-in code pack).
        """
        sprite_folder: Path | None = self.options.sprite_folder
        if sprite_folder is not None:
            user_frames = self._load_user_sprite_frames(sprite_folder)
            if user_frames is not None:
                return (
                    user_frames,
                    DEFAULT_USER_SPRITE_STRIDE_PX_PER_CYCLE,
                    1.0,
                    False,
                )

        sprite_name: str | None = self.options.sprite_name
        if not sprite_name:
            return None
        try:
            # Lazy/deferred: `todoy.display.pixelart` is a pure/stdlib
            # module (Task 34) with no AppKit dependency of its own, so
            # this could just as well be a top-of-file import -- it's kept
            # here instead so a character with no sprite never even
            # attempts it, and so this module degrades gracefully (falls
            # through to character_image/emoji, never crashes overlay
            # startup) if that module is ever missing or a name it doesn't
            # recognize slips through.
            from todoy.display.pixelart import sprite as lookup_pixel_sprite
        except ImportError:
            return None
        try:
            sheet = lookup_pixel_sprite(sprite_name)
        except ValueError:
            return None

        draw_scale = fit_code_sprite_scale(sheet.states, SPRITE_CODE_SCALE, CHARACTER_WINDOW_SIZE)
        frames = {
            state: [_render_pixel_grid(frame, sheet.palette, draw_scale) for frame in state_frames]
            for state, state_frames in sheet.states.items()
        }
        return frames, float(sheet.stride_px_per_cycle), draw_scale, True

    @objc.python_method
    def _load_user_sprite_frames(self, folder: Path) -> dict[str, list[AppKit.NSImage]] | None:
        """Load a user sprite folder (contract section 3: `<state>_<n>.png`
        per `SPRITE_STATES`, `scan_user_sprite_state_files`). `None` if the
        folder doesn't exist, any listed PNG fails to load, or "idle" (the
        one state everything else can fall back to -- see
        `sprite_frames_for_state`) isn't present at all; a partial folder
        (e.g. idle + walk but no jump/wave) loads fine and leans on the
        fallback. All frames of all states share one uniform scale
        (`fit_scale_to_max_height`, derived from the single tallest loaded
        frame) so switching states never visibly resizes the character.
        """
        try:
            if not folder.is_dir():
                return None
        except OSError:
            return None

        raw: dict[str, list[AppKit.NSImage]] = {}
        max_h = 0.0
        for state in SPRITE_STATES:
            paths = scan_user_sprite_state_files(folder, state)
            if not paths:
                continue
            images: list[AppKit.NSImage] = []
            for path in paths:
                try:
                    image = AppKit.NSImage.alloc().initWithContentsOfFile_(str(path))
                except OSError:
                    return None
                if image is None:
                    return None
                w, h = image.size().width, image.size().height
                if w <= 0 or h <= 0:
                    return None
                images.append(image)
                max_h = max(max_h, h)
            raw[state] = images

        if "idle" not in raw:
            return None

        scale = fit_scale_to_max_height(max_h, CHARACTER_MAX_IMAGE_PX)
        for images in raw.values():
            for image in images:
                w, h = image.size().width, image.size().height
                image.setSize_(Foundation.NSMakeSize(w * scale, h * scale))
        return raw

    @objc.python_method
    def _advance_sprite_animation(self, x: float, y_offset: float) -> None:
        """Update the character view's `sprite_state`/`sprite_frame_index`
        for this tick (M14 Task 35, contract section 3's state machine).
        No-op (cheaply -- one attribute check) when no sprite is loaded, so
        this costs nothing for the far more common emoji/character_image
        path. Called from `_build_character_window` (t=0, so the very
        first paint already shows the right pose) and every
        `onWanderTick_`, mirroring how `_apply_character_orientation` is
        driven.

        `x` is `self.movement`'s own patrol position for this tick (i.e.
        the same `x` `onWanderTick_` just got back from `movement.step`) --
        NOT the window's final on-screen x, which also has the entrance/
        flourish curve's `ex` added on top. Odometer distance and the
        walk/idle state split are both about the character's own
        locomotion, not about the flourish/entrance overlay riding on top
        of it.

        `self.movement.is_turning` (Codex review follow-up) is passed
        straight through to `sprite_state_for_tick` -- see that function's
        docstring for why net per-tick `dx` alone can't reliably tell walk
        from idle while an eased edge-turn is in progress.
        """
        view = self.char_view
        if view is None or view.sprite_frames is None:
            return

        dx = x - self._sprite_prev_x
        self._sprite_prev_x = x
        self._sprite_distance_px += abs(dx)
        self._sprite_time += WANDER_TICK_SECONDS

        entrance_active = self.entrance is not None and not self.entrance.finished
        flourish_active = self.flourish is not None and not self.flourish.finished
        movement = self.movement
        state = sprite_state_for_tick(
            dx=dx,
            y_offset=y_offset,
            hop_peak_px=sprite_movement_hop_peak_px(self.options.movement),
            entrance_active=entrance_active,
            entrance_is_hop_or_splash=entrance_active
            and self.persona.entrance in ("hop_in", "splash"),
            flourish_active=flourish_active,
            is_turning=movement is not None and movement.is_turning,
        )

        frame_list = sprite_frames_for_state(view.sprite_frames, state)
        count = len(frame_list)
        if state == "walk":
            index = sprite_walk_frame_index(
                self._sprite_distance_px,
                self._sprite_stride_px_per_cycle,
                self._sprite_draw_scale,
                count,
            )
        elif state == "jump":
            index = sprite_time_frame_index(self._sprite_time, SPRITE_JUMP_FPS, count)
        elif state == "wave":
            index = sprite_time_frame_index(self._sprite_time, SPRITE_WAVE_FPS, count)
        else:
            index = sprite_time_frame_index(self._sprite_time, SPRITE_IDLE_FPS, count)

        if view.sprite_state != state or view.sprite_frame_index != index:
            view.sprite_state = state
            view.sprite_frame_index = index
            view.setNeedsDisplay_(True)

    @objc.python_method
    def _apply_character_orientation(self, y_offset: float, extra_scale: float = 1.0) -> None:
        """Mirror the character to face its travel direction, apply, for
        `gallop` only, a subtle squash-stretch synced to the bounce phase,
        and layer on `extra_scale` (the entrance/flourish curve's uniform
        scale, M13 Task 32 -- 1.0 when neither is active). Pure view-state
        -- doesn't touch the window frame, so it can't disturb click
        regions, flag/banner ride-along, or clamping."""
        view = self.char_view
        movement = self.movement
        if view is None or movement is None:
            return

        if self.options.movement == "gallop":
            ratio = 0.0
            if GALLOP_HOP_PEAK_HEIGHT_PX > 0.0:
                ratio = max(0.0, min(1.0, y_offset / GALLOP_HOP_PEAK_HEIGHT_PX))
            squash_scale = (
                GALLOP_SQUASH_SCALE_MIN
                + (GALLOP_SQUASH_SCALE_MAX - GALLOP_SQUASH_SCALE_MIN) * ratio
            )
        else:
            squash_scale = 1.0

        if (
            view.facing == movement.facing
            and view.squash_scale == squash_scale
            and view.extra_scale == extra_scale
        ):
            return
        view.facing = movement.facing
        view.squash_scale = squash_scale
        view.extra_scale = extra_scale
        view.setNeedsDisplay_(True)

    # --- wandering ---------------------------------------------------------

    def onWanderTick_(self, timer: AppKit.NSTimer) -> None:
        """Advance the character one 30fps tick: normal patrol movement, OR
        -- while a launch entrance or fire-time flourish is in progress
        (M13 Task 32) -- that curve's (x_off, y_off, alpha, scale) applied
        additively on top of the movement's resting position instead.

        Movement itself is held still (`movement.step(0.0)`, which returns
        the current position unchanged) for the duration of the entrance,
        so "movement starts once finished" per contract section 2 -- once
        `entrance.finished`, this falls through to the normal
        `movement.step(WANDER_TICK_SECONDS)` path on the very next tick. A
        flourish, in contrast, layers on top of movement that keeps
        advancing normally -- it must not disturb wandering, per contract.
        """
        window = self.char_window
        if window is None or self.movement is None:
            return

        screen_frame = self._screen_frame()

        if self.entrance is not None and not self.entrance.finished:
            x, y_offset = self.movement.step(0.0)
            ex, ey, alpha, scale = self.entrance.step(WANDER_TICK_SECONDS)
            if self.entrance.finished:
                self.entrance = None
                if self._pending_flourish:
                    # A message fired while the entrance was still running
                    # (see `_start_flourish`) -- start it now, the instant
                    # the entrance clears, instead of dropping it.
                    self._start_flourish()
        elif self.flourish is not None and not self.flourish.finished:
            x, y_offset = self.movement.step(WANDER_TICK_SECONDS)
            ex, ey, alpha, scale = self.flourish.step(WANDER_TICK_SECONDS)
            if self.flourish.finished:
                self.flourish = None
        else:
            x, y_offset = self.movement.step(WANDER_TICK_SECONDS)
            ex, ey, alpha, scale = 0.0, 0.0, 1.0, 1.0

        new_x = screen_frame.origin.x + x + ex
        new_y = self._character_zone_y(screen_frame, y_offset) + ey

        window.setFrameOrigin_(Foundation.NSMakePoint(new_x, new_y))
        window.setAlphaValue_(alpha)
        self._apply_character_orientation(y_offset, extra_scale=scale)
        self._advance_sprite_animation(x, y_offset)

        # Only `flag`/banner rides along with the character every tick;
        # `bubble` appears at show-time position and stays put until
        # hidden, per the message-style contract.
        if (
            self.bubble_window is not None
            and self.bubble_window.isVisible()
            and self.options.message_style == "flag"
        ):
            self._refresh_message_base_origin()
            self._apply_message_window_frame()

    # --- reminder scheduling -------------------------------------------------

    def onReminderTick_(self, timer: AppKit.NSTimer) -> None:
        self.alarm_clock.update(self.get_todos())
        due = self.alarm_clock.due()
        if due:
            # A timed alarm firing shows its own message immediately,
            # overriding whatever the bubble currently shows -- independent
            # of (and without disturbing) the interval scheduler's own
            # cadence below.
            self._show_alarm(due)
            return

        if self._alarm_is_blocking():
            # An alarm is still on screen from an earlier tick (not newly
            # due this tick, so the `due` branch above didn't run) -- hold
            # off on the interval reminder rather than clobbering it.
            # `scheduler.fired()` is deliberately NOT called here, so
            # `should_fire()` stays true and the very next tick after the
            # alarm clears (auto-hide/snooze/replaced by a newer alarm)
            # shows the deferred reminder and resumes normal cadence.
            return

        if self.scheduler.should_fire():
            self._show_reminder()
            self.scheduler.fired()

    def onFirstFire_(self, timer: AppKit.NSTimer) -> None:
        # Guaranteed early reminder so the user sees the overlay works,
        # regardless of the configured interval. Also resets the regular
        # schedule from this point so a second reminder does not double-fire.
        # Deferred (see onReminderTick_) if an alarm already claimed the
        # bubble by the time this one-shot timer fires -- the regular 1s
        # tick's should_fire()/blocking check picks up the slack from here.
        if self._alarm_is_blocking():
            return
        self._show_reminder()
        self.scheduler.fired()

    @objc.python_method
    def _alarm_is_blocking(self) -> bool:
        """Whether an alarm message is currently on screen and must not be
        replaced by an interval reminder (see `onReminderTick_`/`onFirstFire_`).
        """
        return (
            self._showing_alarm
            and self.bubble_window is not None
            and self.bubble_window.isVisible()
        )

    def onTestTimeout_(self, timer: AppKit.NSTimer) -> None:
        self._invalidate_all_timers()
        self.app.terminate_(None)

    @objc.python_method
    def _invalidate_all_timers(self) -> None:
        """Stop every scheduled NSTimer before quitting.

        Prevents leaked repeating/one-shot timers from firing into a
        terminating (or, in tests, a reused-process) run loop.
        """
        for timer in (
            self.wander_timer,
            self.reminder_timer,
            self.first_fire_timer,
            self.test_timeout_timer,
            self.hide_timer,
            self.shake_timer,
            self.flutter_timer,
        ):
            if timer is not None:
                timer.invalidate()
        self.wander_timer = None
        self.reminder_timer = None
        self.first_fire_timer = None
        self.test_timeout_timer = None
        self.hide_timer = None
        self.shake_timer = None
        self.flutter_timer = None
        if self.status_item is not None:
            AppKit.NSStatusBar.systemStatusBar().removeStatusItem_(self.status_item)
            self.status_item = None

    # --- reminder bubble ---------------------------------------------------

    @objc.python_method
    def _show_reminder(self) -> None:
        self._showing_alarm = False
        if self.options.message_style == "flag":
            text = build_flag_line(self.get_todos(), self.options.language)
        else:
            text = self.get_reminder_text()
        self._show_message(text)

    @objc.python_method
    def _show_alarm(self, due_todos: list[Todo]) -> None:
        self._showing_alarm = True
        if self.options.message_style == "flag":
            text = build_alarm_flag_line(due_todos, self.options.language)
        else:
            text = build_alarm_text(due_todos, self.options.language)
        self._show_message(text)

    @objc.python_method
    def _show_message(self, text: str) -> None:
        self._cancel_bubble_shake()
        self._cancel_flutter()
        if self.options.message_style == "flag":
            if self.persona.banner:
                self._build_banner_window(text)
            else:
                self._build_flag_window(text)
        else:
            if self.bubble_window is None:
                self._build_bubble_window()
            assert self.bubble_window is not None
            assert self.bubble_text_field is not None
            self.bubble_text_field.setAttributedStringValue_(_build_reminder_attributed_text(text))
        self._refresh_message_base_origin()
        self._apply_message_window_frame()
        self._apply_bubble_entrance_effect()
        self._reset_hide_timer()
        if self.options.message_style == "flag":
            self._start_flutter()
        self._start_flourish()

    @objc.python_method
    def _start_flourish(self) -> None:
        """Start this persona's fire-time flourish (M13 Task 32, contract
        section 2): additive on top of normal wandering via `onWanderTick_`,
        never disturbing click regions, snooze/quit, ride-along, clamps, or
        timers -- it only nudges the character window's origin/alpha/scale.

        Deferred (not dropped) while the launch entrance is still in
        progress -- a flourish must never preempt or fight the entrance for
        the same window frame, but an alarm CAN genuinely fire mid-entrance
        in practice (the 1s reminder-check tick races a 0.8-1.4s entrance;
        `FIRST_FIRE_DELAY_SECONDS`'s 5s guaranteed reminder is comfortably
        past it, but an earlier *alarm* is not bounded that way). Sets
        `self._pending_flourish`, which `onWanderTick_` checks the instant
        the entrance finishes and starts the flourish then (Codex review
        follow-up, M13 Task 32: this used to just skip the flourish
        entirely in that race, silently dropping it).
        """
        if self.entrance is not None and not self.entrance.finished:
            self._pending_flourish = True
            return
        self._pending_flourish = False
        flourish = FlourishAnimation(self.persona.flourish, char_height=CHARACTER_WINDOW_SIZE)
        self.flourish = None if flourish.finished else flourish

    @objc.python_method
    def _build_bubble_window(self) -> None:
        panel_bottom = BUBBLE_TAIL_HEIGHT
        window_height = BUBBLE_HEIGHT + panel_bottom

        frame = Foundation.NSMakeRect(0, 0, BUBBLE_WIDTH, window_height)
        window = AppKit.NSPanel.alloc().initWithContentRect_styleMask_backing_defer_(
            frame,
            AppKit.NSWindowStyleMaskBorderless | AppKit.NSWindowStyleMaskNonactivatingPanel,
            AppKit.NSBackingStoreBuffered,
            False,
        )
        window.setOpaque_(False)
        window.setBackgroundColor_(AppKit.NSColor.clearColor())
        window.setHasShadow_(True)
        window.setLevel_(AppKit.NSFloatingWindowLevel)
        window.setCollectionBehavior_(
            AppKit.NSWindowCollectionBehaviorCanJoinAllSpaces
            | AppKit.NSWindowCollectionBehaviorStationary
        )

        content = _MessagePanelView.alloc().initWithFrame_(frame)
        content.panel_bottom = panel_bottom

        # The panel content (text + Snooze/Quit), shifted up by
        # `panel_bottom` (the bubble's tail) at the bottom of the view.
        text_field = AppKit.NSTextField.alloc().initWithFrame_(
            Foundation.NSMakeRect(
                BUBBLE_PADDING,
                panel_bottom + BUBBLE_BUTTON_ROW_HEIGHT + BUBBLE_PADDING,
                BUBBLE_WIDTH - BUBBLE_PADDING * 2,
                BUBBLE_TEXT_HEIGHT,
            )
        )
        text_field.setEditable_(False)
        text_field.setSelectable_(False)
        text_field.setBezeled_(False)
        text_field.setDrawsBackground_(False)
        text_field.setLineBreakMode_(AppKit.NSLineBreakByWordWrapping)
        text_field.cell().setWraps_(True)
        content.addSubview_(text_field)

        snooze_label = f"Snooze {self.scheduler.snooze_minutes}m"
        snooze_button = _make_primary_button(
            snooze_label,
            Foundation.NSMakeRect(
                BUBBLE_PADDING, panel_bottom + BUBBLE_PADDING, SNOOZE_BUTTON_WIDTH, BUTTON_HEIGHT
            ),
            self,
            "onSnoozeClicked:",
        )
        quit_button = _make_quiet_button(
            "Quit",
            Foundation.NSMakeRect(
                BUBBLE_WIDTH - BUBBLE_PADDING - QUIT_BUTTON_WIDTH,
                panel_bottom + BUBBLE_PADDING,
                QUIT_BUTTON_WIDTH,
                BUTTON_HEIGHT,
            ),
            self,
            "onQuitClicked:",
        )
        content.addSubview_(snooze_button)
        content.addSubview_(quit_button)

        window.setContentView_(content)

        self.bubble_window = window
        self.bubble_text_field = text_field

    @objc.python_method
    def _compute_message_origin(self) -> AppKit.NSPoint | None:
        """The message window's resting origin (no shake offset applied).

        For `flag`/banner this is clamped to the screen (contract: "the
        flag/banner must stay fully on screen"); `bubble` is left
        unclamped, matching its pre-existing behavior.

        Vertical placement (M13 Task 32, contract section 2):
        - `flag` + `persona.banner`: hangs BELOW the character (two
          strings from its feet down to the panel), not above on a pole.
        - `bubble` + `persona.zone == "sky"`: goes BELOW a sky character
          (which cruises near the top) instead of above it.
        - Every other combination keeps the pre-M13 above-the-character
          placement.
        """
        if self.char_window is None or self.bubble_window is None:
            return None
        char_frame = self.char_window.frame()
        window_frame = self.bubble_window.frame()
        window_width = window_frame.size.width
        x = char_frame.origin.x + char_frame.size.width / 2 - window_width / 2

        if self.options.message_style == "flag":
            if self.persona.banner:
                y = char_frame.origin.y - window_frame.size.height - BANNER_GAP_BELOW_CHARACTER
            else:
                y = char_frame.origin.y + char_frame.size.height + FLAG_GAP_ABOVE_CHARACTER
            x = self._clamp_x_to_screen(x, window_width)
        elif self.persona.zone == "sky":
            y = char_frame.origin.y - window_frame.size.height - BUBBLE_GAP_BELOW_CHARACTER
        else:
            y = char_frame.origin.y + char_frame.size.height + BUBBLE_GAP_ABOVE_CHARACTER

        return Foundation.NSMakePoint(x, y)

    @objc.python_method
    def _refresh_message_base_origin(self) -> None:
        """Recompute and store `self._message_base_origin` from the
        character's current position. Call at show-time (both styles) and,
        for `flag` only, on every wander tick -- see `onWanderTick_`.
        """
        origin = self._compute_message_origin()
        if origin is not None:
            self._message_base_origin = origin

    @objc.python_method
    def _apply_message_window_frame(self) -> None:
        """Paint `self.bubble_window` at `_message_base_origin` plus any
        active shake offset, re-clamping to the screen for `flag` every
        time -- so a shake near a screen edge can never push the flag off
        screen, even mid-oscillation.
        """
        window = self.bubble_window
        base = self._message_base_origin
        if window is None or base is None:
            return

        x = base.x + self._shake_offset_px
        if self.options.message_style == "flag":
            x = self._clamp_x_to_screen(x, window.frame().size.width)

        window.setFrameOrigin_(Foundation.NSMakePoint(x, base.y))

    @objc.python_method
    def _clamp_x_to_screen(self, x: float, width: float) -> float:
        """Clamp `x` so a `width`-wide window stays fully within the screen."""
        screen_frame = self._screen_frame()
        min_x = screen_frame.origin.x
        max_x = screen_frame.origin.x + screen_frame.size.width - width
        if max_x < min_x:
            return min_x
        return min(max(x, min_x), max_x)

    @objc.python_method
    def _apply_bubble_entrance_effect(self) -> None:
        """Show `self.bubble_window` using `self.options.bubble_effect`.

        `_apply_message_window_frame()` must already have set the window's
        *target* frame before this runs. pop/fade/slide animate via
        `NSAnimationContext` (<= `BUBBLE_EFFECT_DURATION_SECONDS`); shake
        appears instantly and then wiggles horizontally with chained
        one-shot `NSTimer`s; none appears instantly with no animation.

        Bug fix (user report: "고래를 보면 메시지가 캐릭터를 안따라가" --
        reproduced with whale + `flag` style): `flag`/banner windows ride
        along with the character every ~33ms wander tick
        (`onWanderTick_` -> `_apply_message_window_frame` ->
        `setFrameOrigin_`, a direct/instant set). `pop` and `slide` drive
        the window's FRAME through `.animator()`, which schedules its own
        ~`BUBBLE_EFFECT_DURATION_SECONDS`-long implicit Core Animation on
        that same window -- competing with every ride-along tick during
        that window, so the message visibly freezes/lags behind a moving
        character (worst on a constantly-walking persona like whale) until
        the animation finishes and the two reconcile. `fade`/`shake`/`none`
        never touch the frame via `.animator()` and were never affected.
        For a riding-along style, `pop`/`slide` are downgraded to `fade`'s
        alpha-only entrance (frame set once, directly, to the target --
        never interpolated) so there is nothing left to fight the ride-along
        ticks; `bubble` (which shows once and stays put) is unaffected.
        """
        window = self.bubble_window
        assert window is not None
        effect = self.options.bubble_effect
        if self.options.message_style == "flag" and effect in ("pop", "slide"):
            effect = "fade"
        target_frame = window.frame()

        if effect == "pop":
            window.setAlphaValue_(1.0)
            window.setFrame_display_(_scaled_frame(target_frame, 0.85), False)
            window.orderFrontRegardless()
            with _animation_group(BUBBLE_EFFECT_DURATION_SECONDS):
                window.animator().setFrame_display_(target_frame, True)
            return

        if effect == "fade":
            window.setAlphaValue_(0.0)
            window.setFrame_display_(target_frame, False)
            window.orderFrontRegardless()
            with _animation_group(BUBBLE_EFFECT_DURATION_SECONDS):
                window.animator().setAlphaValue_(1.0)
            return

        if effect == "slide":
            start_frame = Foundation.NSMakeRect(
                target_frame.origin.x,
                target_frame.origin.y - BUBBLE_SLIDE_RISE_PX,
                target_frame.size.width,
                target_frame.size.height,
            )
            window.setAlphaValue_(0.0)
            window.setFrame_display_(start_frame, False)
            window.orderFrontRegardless()
            with _animation_group(BUBBLE_EFFECT_DURATION_SECONDS):
                window.animator().setAlphaValue_(1.0)
                window.animator().setFrame_display_(target_frame, True)
            return

        if effect == "shake":
            window.setAlphaValue_(1.0)
            window.setFrame_display_(target_frame, False)
            window.orderFrontRegardless()
            self._start_bubble_shake()
            return

        # "none" (and any future unvalidated fallback): appear instantly.
        window.setAlphaValue_(1.0)
        window.setFrame_display_(target_frame, False)
        window.orderFrontRegardless()

    @objc.python_method
    def _start_bubble_shake(self) -> None:
        """Begin the shake wiggle around the *current* `_message_base_origin`.

        Each step just sets `_shake_offset_px` and repaints via
        `_apply_message_window_frame()`, which re-derives the base origin
        (updated live every wander tick for `flag`) and re-clamps to the
        screen -- so a `flag` shake tracks a moving/galloping character and
        never wiggles the window off screen.
        """
        self._shake_step_index = 0
        self._shake_offset_px = 0.0
        self._fire_bubble_shake_step()

    @objc.python_method
    def _fire_bubble_shake_step(self) -> None:
        if self.bubble_window is None or self._message_base_origin is None:
            return

        total_steps = BUBBLE_SHAKE_OSCILLATIONS * 2
        if self._shake_step_index >= total_steps:
            self._shake_offset_px = 0.0
            self._apply_message_window_frame()
            return

        direction = 1.0 if self._shake_step_index % 2 == 0 else -1.0
        self._shake_offset_px = direction * BUBBLE_SHAKE_AMPLITUDE_PX
        self._apply_message_window_frame()
        self._shake_step_index += 1

        self.shake_timer = (
            AppKit.NSTimer.scheduledTimerWithTimeInterval_target_selector_userInfo_repeats_(
                BUBBLE_SHAKE_STEP_SECONDS, self, "onBubbleShakeStep:", None, False
            )
        )

    def onBubbleShakeStep_(self, timer: AppKit.NSTimer) -> None:
        self._fire_bubble_shake_step()

    @objc.python_method
    def _cancel_bubble_shake(self) -> None:
        if self.shake_timer is not None:
            self.shake_timer.invalidate()
            self.shake_timer = None
        if self._shake_offset_px != 0.0:
            self._shake_offset_px = 0.0
            self._apply_message_window_frame()

    @objc.python_method
    def _reset_hide_timer(self) -> None:
        if self.hide_timer is not None:
            self.hide_timer.invalidate()
        duration = (
            FLAG_AUTO_HIDE_SECONDS
            if self.options.message_style == "flag"
            else BUBBLE_AUTO_HIDE_SECONDS
        )
        self.hide_timer = (
            AppKit.NSTimer.scheduledTimerWithTimeInterval_target_selector_userInfo_repeats_(
                duration, self, "onHideBubble:", None, False
            )
        )

    def onHideBubble_(self, timer: AppKit.NSTimer) -> None:
        self._hide_bubble()

    @objc.python_method
    def _hide_bubble(self) -> None:
        self._cancel_bubble_shake()
        self._cancel_flutter()
        if self.bubble_window is not None:
            self.bubble_window.orderOut_(None)
        if self.hide_timer is not None:
            self.hide_timer.invalidate()
            self.hide_timer = None

    # --- flag pennant construction + flutter --------------------------------

    @objc.python_method
    def _build_flag_window(self, text: str) -> None:
        """Rebuild `self.bubble_window` as a compact `flag` pennant sized to
        `text`. Rebuilt fresh on every fire (rather than resized in place)
        since each fire's text -- and therefore the pennant's width -- can
        differ; flag fires are infrequent enough (once per reminder interval,
        or on an alarm) that this is cheap.
        """
        attributed = _build_flag_attributed_text(text)
        text_width = attributed.size().width
        content_width = (
            text_width + FLAG_TEXT_PADDING_LEFT + FLAG_TEXT_PADDING_RIGHT + FLAG_NOTCH_DEPTH
        )
        panel_width = min(max(content_width, FLAG_MIN_WIDTH), FLAG_MAX_WIDTH)
        window_height = FLAG_PANEL_HEIGHT + FLAG_POLE_HEIGHT

        if self.bubble_window is not None:
            self.bubble_window.orderOut_(None)

        frame = Foundation.NSMakeRect(0, 0, panel_width, window_height)
        window = AppKit.NSPanel.alloc().initWithContentRect_styleMask_backing_defer_(
            frame,
            AppKit.NSWindowStyleMaskBorderless | AppKit.NSWindowStyleMaskNonactivatingPanel,
            AppKit.NSBackingStoreBuffered,
            False,
        )
        window.setOpaque_(False)
        window.setBackgroundColor_(AppKit.NSColor.clearColor())
        window.setHasShadow_(True)
        window.setLevel_(AppKit.NSFloatingWindowLevel)
        window.setCollectionBehavior_(
            AppKit.NSWindowCollectionBehaviorCanJoinAllSpaces
            | AppKit.NSWindowCollectionBehaviorStationary
        )

        content = _FlagPanelView.alloc().initWithFrame_(frame)
        content.controller = self
        content.panel_bottom = FLAG_POLE_HEIGHT
        content.pole_inset = FLAG_POLE_INSET
        content.pole_width = FLAG_POLE_WIDTH
        content.set_text(attributed, FLAG_TEXT_PADDING_LEFT)
        window.setContentView_(content)

        self.bubble_window = window
        self.bubble_text_field = None
        self.flag_view = content

    @objc.python_method
    def _build_banner_window(self, text: str) -> None:
        """Rebuild `self.bubble_window` as a banner-below pennant sized to
        `text` (M13 Task 32, `persona.banner`): the same pennant panel as
        `_build_flag_window`, but hanging BELOW the character from two thin
        strings instead of riding a pole above it. Rebuilt fresh on every
        fire, same rationale as `_build_flag_window`.
        """
        attributed = _build_flag_attributed_text(text)
        text_width = attributed.size().width
        content_width = (
            text_width + FLAG_TEXT_PADDING_LEFT + FLAG_TEXT_PADDING_RIGHT + FLAG_NOTCH_DEPTH
        )
        panel_width = min(max(content_width, FLAG_MIN_WIDTH), FLAG_MAX_WIDTH)
        window_height = FLAG_PANEL_HEIGHT + BANNER_STRING_HEIGHT_PX

        if self.bubble_window is not None:
            self.bubble_window.orderOut_(None)

        frame = Foundation.NSMakeRect(0, 0, panel_width, window_height)
        window = AppKit.NSPanel.alloc().initWithContentRect_styleMask_backing_defer_(
            frame,
            AppKit.NSWindowStyleMaskBorderless | AppKit.NSWindowStyleMaskNonactivatingPanel,
            AppKit.NSBackingStoreBuffered,
            False,
        )
        window.setOpaque_(False)
        window.setBackgroundColor_(AppKit.NSColor.clearColor())
        window.setHasShadow_(True)
        window.setLevel_(AppKit.NSFloatingWindowLevel)
        window.setCollectionBehavior_(
            AppKit.NSWindowCollectionBehaviorCanJoinAllSpaces
            | AppKit.NSWindowCollectionBehaviorStationary
        )

        content = _BannerPanelView.alloc().initWithFrame_(frame)
        content.controller = self
        content.panel_height = FLAG_PANEL_HEIGHT
        content.string_inset = BANNER_STRING_INSET_PX
        content.set_text(attributed, FLAG_TEXT_PADDING_LEFT)
        window.setContentView_(content)

        self.bubble_window = window
        self.bubble_text_field = None
        # Reused as the generic flutter-target attribute -- `_apply_flutter_
        # frame` only needs `.flutter_offset`/`setNeedsDisplay_`, which both
        # `_FlagPanelView` and `_BannerPanelView` provide.
        self.flag_view = content

    @objc.python_method
    def _start_flutter(self) -> None:
        """Begin the pennant's periodic "wind" flutter (notch-depth wobble,
        see `_flutter_notch_offset`) on a dedicated repeating timer, stored
        + invalidated like the other timers (`_cancel_flutter`,
        `_invalidate_all_timers`). No-op outside `flag` style.
        """
        if self.options.message_style != "flag":
            return
        self._flutter_start = time.monotonic()
        self._apply_flutter_frame()
        self.flutter_timer = (
            AppKit.NSTimer.scheduledTimerWithTimeInterval_target_selector_userInfo_repeats_(
                FLAG_FLUTTER_STEP_SECONDS, self, "onFlutterStep:", None, True
            )
        )

    def onFlutterStep_(self, timer: AppKit.NSTimer) -> None:
        self._apply_flutter_frame()

    @objc.python_method
    def _apply_flutter_frame(self) -> None:
        view = self.flag_view
        if view is None:
            return
        elapsed = time.monotonic() - self._flutter_start
        view.flutter_offset = _flutter_notch_offset(elapsed)
        view.setNeedsDisplay_(True)

    @objc.python_method
    def _cancel_flutter(self) -> None:
        if self.flutter_timer is not None:
            self.flutter_timer.invalidate()
            self.flutter_timer = None

    # --- bubble button actions ----------------------------------------------

    def onSnoozeClicked_(self, sender: AppKit.NSButton) -> None:
        if self._showing_alarm:
            self.alarm_clock.snooze_last()
        else:
            self.scheduler.snooze()
        self._hide_bubble()

    def onQuitClicked_(self, sender: AppKit.NSButton) -> None:
        # Ends this process only; the overlay returns on next `todoy overlay`
        # launch. No permanent mute / no todo-completion controls here.
        self._invalidate_all_timers()
        self.app.terminate_(None)

    # --- menu-bar quick-add panel --------------------------------------------

    @objc.python_method
    def _build_status_item(self) -> None:
        status_bar = AppKit.NSStatusBar.systemStatusBar()
        item = status_bar.statusItemWithLength_(AppKit.NSVariableStatusItemLength)
        button = item.button()
        button.setTitle_(self.options.character.emoji)
        button.setTarget_(self)
        button.setAction_("onStatusItemClicked:")
        # Left-click keeps toggling the quick-add panel (below); right-click
        # (or control-click) instead shows the Quit menu -- both routed
        # through the one action handler, disambiguated by the click event
        # it's dispatched with (see `onStatusItemClicked_`).
        button.sendActionOn_(AppKit.NSEventMaskLeftMouseUp | AppKit.NSEventMaskRightMouseUp)
        self.status_item = item
        self.status_menu = _build_status_menu(self)

    def onStatusItemClicked_(self, sender: AppKit.NSObject) -> None:
        event = self.app.currentEvent()
        if event is not None and event.type() == AppKit.NSEventTypeRightMouseUp:
            self._show_status_menu(event)
            return
        if self.panel_window is not None and self.panel_window.isVisible():
            self._hide_panel()
        else:
            self._show_panel()

    @objc.python_method
    def _show_status_menu(self, event: AppKit.NSEvent) -> None:
        if self.status_menu is None or self.status_item is None:
            return
        button = self.status_item.button()
        AppKit.NSMenu.popUpContextMenu_withEvent_forView_(self.status_menu, event, button)

    @objc.python_method
    def _show_panel(self) -> None:
        if self.panel_window is None:
            self._build_panel_window()
        assert self.panel_window is not None
        self._set_panel_error(None)
        self._refresh_panel_list()
        self._position_panel_window()
        # Non-activating panels default to not becoming key (see
        # `_PanelWindow.canBecomeKeyWindow`), so without activating the app
        # here the text field could not receive keystrokes -- per the
        # contract, we activate only while the panel is open; closing it
        # (`_hide_panel`, `_PanelWindow.resignKeyWindow`) does not otherwise
        # hold onto activation.
        self.app.activateIgnoringOtherApps_(True)
        self.panel_window.makeKeyAndOrderFront_(None)
        self.panel_window.makeFirstResponder_(self.panel_text_field)

    @objc.python_method
    def _hide_panel(self) -> None:
        if self.panel_window is not None:
            self.panel_window.orderOut_(None)

    @objc.python_method
    def _panel_total_height(self) -> float:
        return (
            QUICKADD_PANEL_PADDING
            + QUICKADD_ROW_HEIGHT
            + QUICKADD_ROW_GAP
            + QUICKADD_ERROR_HEIGHT
            + QUICKADD_ROW_GAP
            + QUICKADD_SEPARATOR_HEIGHT
            + QUICKADD_ROW_GAP
            + QUICKADD_SECTION_LABEL_HEIGHT
            + QUICKADD_ROW_GAP
            + QUICKADD_LIST_VISIBLE_HEIGHT
            + QUICKADD_PANEL_PADDING
        )

    @objc.python_method
    def _build_panel_window(self) -> None:
        total_height = self._panel_total_height()
        frame = Foundation.NSMakeRect(0, 0, QUICKADD_PANEL_WIDTH, total_height)
        panel = _PanelWindow.alloc().initWithContentRect_styleMask_backing_defer_(
            frame,
            AppKit.NSWindowStyleMaskBorderless | AppKit.NSWindowStyleMaskNonactivatingPanel,
            AppKit.NSBackingStoreBuffered,
            False,
        )
        panel.controller = self
        panel.setOpaque_(False)
        panel.setBackgroundColor_(AppKit.NSColor.clearColor())
        panel.setHasShadow_(True)
        panel.setLevel_(AppKit.NSFloatingWindowLevel)
        panel.setCollectionBehavior_(
            AppKit.NSWindowCollectionBehaviorCanJoinAllSpaces
            | AppKit.NSWindowCollectionBehaviorStationary
        )

        content = _QuickAddPanelView.alloc().initWithFrame_(frame)
        content_width = QUICKADD_PANEL_WIDTH - QUICKADD_PANEL_PADDING * 2
        y = QUICKADD_PANEL_PADDING

        text_field_width = (
            content_width - QUICKADD_TIME_FIELD_WIDTH - QUICKADD_ADD_BUTTON_WIDTH - 8.0
        )
        text_field = AppKit.NSTextField.alloc().initWithFrame_(
            Foundation.NSMakeRect(QUICKADD_PANEL_PADDING, y, text_field_width, QUICKADD_ROW_HEIGHT)
        )
        text_field.setPlaceholderString_("Add a todo…")
        text_field.setBezelStyle_(AppKit.NSTextFieldRoundedBezel)
        text_field.setTarget_(self)
        text_field.setAction_("onAddClicked:")
        content.addSubview_(text_field)

        time_x = text_field.frame().origin.x + text_field.frame().size.width + 4.0
        time_field = AppKit.NSTextField.alloc().initWithFrame_(
            Foundation.NSMakeRect(time_x, y, QUICKADD_TIME_FIELD_WIDTH, QUICKADD_ROW_HEIGHT)
        )
        time_field.setPlaceholderString_("HH:MM")
        time_field.setBezelStyle_(AppKit.NSTextFieldRoundedBezel)
        time_field.setTarget_(self)
        time_field.setAction_("onAddClicked:")
        content.addSubview_(time_field)

        add_x = time_field.frame().origin.x + time_field.frame().size.width + 4.0
        add_button = _make_primary_button(
            "Add",
            Foundation.NSMakeRect(add_x, y, QUICKADD_ADD_BUTTON_WIDTH, QUICKADD_ROW_HEIGHT),
            self,
            "onAddClicked:",
        )
        content.addSubview_(add_button)

        y += QUICKADD_ROW_HEIGHT + QUICKADD_ROW_GAP
        error_label = AppKit.NSTextField.alloc().initWithFrame_(
            Foundation.NSMakeRect(QUICKADD_PANEL_PADDING, y, content_width, QUICKADD_ERROR_HEIGHT)
        )
        _configure_static_label(error_label)
        error_label.setFont_(AppKit.NSFont.systemFontOfSize_(11.0))
        error_label.setTextColor_(AppKit.NSColor.systemRedColor())
        content.addSubview_(error_label)

        y += QUICKADD_ERROR_HEIGHT + QUICKADD_ROW_GAP
        separator = AppKit.NSBox.alloc().initWithFrame_(
            Foundation.NSMakeRect(
                QUICKADD_PANEL_PADDING, y, content_width, QUICKADD_SEPARATOR_HEIGHT
            )
        )
        separator.setBoxType_(AppKit.NSBoxSeparator)
        content.addSubview_(separator)

        y += QUICKADD_ROW_GAP
        section_label = AppKit.NSTextField.alloc().initWithFrame_(
            Foundation.NSMakeRect(
                QUICKADD_PANEL_PADDING, y, content_width, QUICKADD_SECTION_LABEL_HEIGHT
            )
        )
        _configure_static_label(section_label)
        section_label.setFont_(
            AppKit.NSFont.systemFontOfSize_weight_(11.0, AppKit.NSFontWeightSemibold)
        )
        section_label.setTextColor_(AppKit.NSColor.secondaryLabelColor())
        section_label.setStringValue_("TODAY")
        content.addSubview_(section_label)

        y += QUICKADD_SECTION_LABEL_HEIGHT + QUICKADD_ROW_GAP
        scroll_view = AppKit.NSScrollView.alloc().initWithFrame_(
            Foundation.NSMakeRect(
                QUICKADD_PANEL_PADDING, y, content_width, QUICKADD_LIST_VISIBLE_HEIGHT
            )
        )
        scroll_view.setHasVerticalScroller_(True)
        scroll_view.setDrawsBackground_(False)
        scroll_view.setBorderType_(AppKit.NSNoBorder)
        list_view = _FlippedListView.alloc().initWithFrame_(
            Foundation.NSMakeRect(0, 0, content_width, QUICKADD_LIST_VISIBLE_HEIGHT)
        )
        scroll_view.setDocumentView_(list_view)
        content.addSubview_(scroll_view)

        panel.setContentView_(content)

        self.panel_window = panel
        self.panel_text_field = text_field
        self.panel_time_field = time_field
        self.panel_error_label = error_label
        self.panel_list_view = list_view
        self._panel_list_width = content_width

    @objc.python_method
    def _position_panel_window(self) -> None:
        panel = self.panel_window
        if panel is None or self.status_item is None:
            return
        button = self.status_item.button()
        button_window = button.window() if button is not None else None
        if button is None or button_window is None:
            return

        button_frame_screen = button_window.convertRectToScreen_(button.frame())
        panel_width = panel.frame().size.width
        x = button_frame_screen.origin.x + button_frame_screen.size.width / 2 - panel_width / 2
        x = self._clamp_x_to_screen(x, panel_width)
        y = (
            button_frame_screen.origin.y
            - panel.frame().size.height
            - (QUICKADD_PANEL_GAP_BELOW_STATUS_ITEM)
        )
        panel.setFrameOrigin_(Foundation.NSMakePoint(x, y))

    @objc.python_method
    def _refresh_panel_list(self) -> None:
        list_view = self.panel_list_view
        if list_view is None:
            return

        todos = self.get_todos()
        self._panel_todos = todos

        for view in list(list_view.subviews()):
            view.removeFromSuperview()

        content_height = max(QUICKADD_LIST_VISIBLE_HEIGHT, len(todos) * QUICKADD_LIST_ROW_HEIGHT)
        list_view.setFrame_(Foundation.NSMakeRect(0, 0, self._panel_list_width, content_height))
        for index, todo in enumerate(todos):
            list_view.addSubview_(self._build_panel_row(todo, index))

    @objc.python_method
    def _build_panel_row(self, todo: Todo, index: int) -> AppKit.NSView:
        y = index * QUICKADD_LIST_ROW_HEIGHT
        row_width = self._panel_list_width
        row = AppKit.NSView.alloc().initWithFrame_(
            Foundation.NSMakeRect(0, y, row_width, QUICKADD_LIST_ROW_HEIGHT)
        )

        pinned = todo.pinned
        text = sanitize_text(todo.text)
        if pinned:
            text = f"{text} 📌"

        if todo.id is None:
            # Read-only (non-builtin, e.g. markdown) row: text only, no
            # controls -- there is nothing here that can be done/deleted/
            # pinned.
            label = _make_row_label(
                text,
                Foundation.NSMakeRect(4.0, 0.0, row_width - 8.0, QUICKADD_LIST_ROW_HEIGHT),
                secondary=True,
            )
            row.addSubview_(label)
            return row

        button_size = QUICKADD_ROW_BUTTON_SIZE
        button_y = (QUICKADD_LIST_ROW_HEIGHT - button_size) / 2.0
        x = row_width - button_size
        delete_button = _make_icon_button(
            "✕",
            Foundation.NSMakeRect(x, button_y, button_size, button_size),
            self,
            "onRowDeleteClicked:",
            todo.id,
        )
        x -= button_size
        done_button = _make_icon_button(
            "✓",
            Foundation.NSMakeRect(x, button_y, button_size, button_size),
            self,
            "onRowDoneClicked:",
            todo.id,
        )
        x -= button_size
        pin_button = _make_icon_button(
            "📌",
            Foundation.NSMakeRect(x, button_y, button_size, button_size),
            self,
            "onRowPinClicked:",
            todo.id,
        )
        label_width = x - 4.0
        label = _make_row_label(
            text,
            Foundation.NSMakeRect(4.0, 0.0, label_width, QUICKADD_LIST_ROW_HEIGHT),
            secondary=False,
        )
        row.addSubview_(label)
        row.addSubview_(pin_button)
        row.addSubview_(done_button)
        row.addSubview_(delete_button)
        return row

    @objc.python_method
    def _set_panel_error(self, message: str | None) -> None:
        if self.panel_error_label is None:
            return
        self.panel_error_label.setStringValue_(sanitize_text(message) if message else "")

    @objc.python_method
    def _todo_pinned(self, todo_id: int) -> bool:
        for todo in self._panel_todos:
            if todo.id == todo_id:
                return todo.pinned
        return False

    def onAddClicked_(self, sender: AppKit.NSObject) -> None:
        if self.panel_text_field is None or self.panel_time_field is None:
            return
        text = str(self.panel_text_field.stringValue()).strip()
        at_raw = str(self.panel_time_field.stringValue()).strip()
        at = at_raw if at_raw else None

        if not text:
            self._set_panel_error("Enter todo text")
            return

        error = self.actions.add(text, at)
        if error is None:
            self.panel_text_field.setStringValue_("")
            self.panel_time_field.setStringValue_("")
        self._set_panel_error(error)
        self._refresh_panel_list()

    def onRowDoneClicked_(self, sender: AppKit.NSButton) -> None:
        error = self.actions.set_done(sender.tag())
        self._set_panel_error(error)
        self._refresh_panel_list()

    def onRowDeleteClicked_(self, sender: AppKit.NSButton) -> None:
        error = self.actions.delete(sender.tag())
        self._set_panel_error(error)
        self._refresh_panel_list()

    def onRowPinClicked_(self, sender: AppKit.NSButton) -> None:
        todo_id = sender.tag()
        error = self.actions.set_pinned(todo_id, not self._todo_pinned(todo_id))
        self._set_panel_error(error)
        self._refresh_panel_list()


def _menu_bar_clearance_px(screen_frame: AppKit.NSRect, visible_frame: AppKit.NSRect) -> float:
    """The vertical gap between `screen_frame`'s top edge and `visible_
    frame`'s top edge -- i.e. the menu bar (or notch) height reserved at
    the top of the screen (`NSScreen.frame()` vs `NSScreen.visibleFrame()`
    -- Codex review follow-up, M13 Task 32 sky-zone cruise clearance).

    Module-level and struct-only (no `NSScreen` object needed) so it's
    directly unit-testable with fake rects, independent of the real
    display's actual menu bar height. Returns 0.0 (never negative) if the
    two frames don't indicate any top inset at all -- callers apply their
    own hardcoded fallback in that case (see `_OverlayController.
    _sky_top_margin`).
    """
    top = screen_frame.origin.y + screen_frame.size.height
    visible_top = visible_frame.origin.y + visible_frame.size.height
    return max(0.0, top - visible_top)


def _scaled_frame(frame: AppKit.NSRect, scale: float) -> AppKit.NSRect:
    """`frame` shrunk/grown by `scale`, keeping the same center point."""
    new_width = frame.size.width * scale
    new_height = frame.size.height * scale
    new_x = frame.origin.x + (frame.size.width - new_width) / 2.0
    new_y = frame.origin.y + (frame.size.height - new_height) / 2.0
    return Foundation.NSMakeRect(new_x, new_y, new_width, new_height)


def _build_status_menu(controller: _OverlayController) -> AppKit.NSMenu:
    """The status item's right-click menu: a single "Quit todoy" item,
    wired to the same `onQuitClicked_` the bubble's Quit button uses --
    reachable in both message styles, alongside the (unchanged) left-click
    quick-add panel toggle (see `onStatusItemClicked_`).
    """
    menu = AppKit.NSMenu.alloc().init()
    quit_item = AppKit.NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
        "Quit todoy", "onQuitClicked:", ""
    )
    quit_item.setTarget_(controller)
    menu.addItem_(quit_item)
    return menu


@contextmanager
def _animation_group(duration: float) -> Iterator[None]:
    """Run an `.animator()`-proxied change over `duration` seconds."""
    AppKit.NSAnimationContext.beginGrouping()
    try:
        AppKit.NSAnimationContext.currentContext().setDuration_(duration)
        yield
    finally:
        AppKit.NSAnimationContext.endGrouping()


def _make_primary_button(
    title: str,
    frame: AppKit.NSRect,
    target: AppKit.NSObject,
    selector: str,
) -> AppKit.NSButton:
    """The prominent accent action (Snooze): a filled, rounded, accent-toned pill."""
    button = AppKit.NSButton.alloc().initWithFrame_(frame)
    button.setBordered_(False)
    button.setButtonType_(AppKit.NSButtonTypeMomentaryChange)
    button.setWantsLayer_(True)
    button.layer().setBackgroundColor_(AppKit.NSColor.controlAccentColor().CGColor())
    button.layer().setCornerRadius_(BUTTON_CORNER_RADIUS)
    font = AppKit.NSFont.systemFontOfSize_weight_(12.0, AppKit.NSFontWeightSemibold)
    attrs = {
        AppKit.NSFontAttributeName: font,
        AppKit.NSForegroundColorAttributeName: AppKit.NSColor.whiteColor(),
    }
    button.setAttributedTitle_(
        AppKit.NSAttributedString.alloc().initWithString_attributes_(title, attrs)
    )
    button.setTarget_(target)
    button.setAction_(selector)
    return button


def _make_quiet_button(
    title: str,
    frame: AppKit.NSRect,
    target: AppKit.NSObject,
    selector: str,
) -> AppKit.NSButton:
    """The secondary action (Quit): borderless, secondary-colored plain text."""
    button = AppKit.NSButton.alloc().initWithFrame_(frame)
    button.setBordered_(False)
    button.setButtonType_(AppKit.NSButtonTypeMomentaryChange)
    font = AppKit.NSFont.systemFontOfSize_weight_(12.0, AppKit.NSFontWeightRegular)
    attrs = {
        AppKit.NSFontAttributeName: font,
        AppKit.NSForegroundColorAttributeName: AppKit.NSColor.secondaryLabelColor(),
    }
    button.setAttributedTitle_(
        AppKit.NSAttributedString.alloc().initWithString_attributes_(title, attrs)
    )
    button.setTarget_(target)
    button.setAction_(selector)
    return button


def _configure_static_label(label: AppKit.NSTextField) -> None:
    """Shared setup for a non-editable, non-interactive text label."""
    label.setEditable_(False)
    label.setSelectable_(False)
    label.setBezeled_(False)
    label.setDrawsBackground_(False)
    label.setLineBreakMode_(AppKit.NSLineBreakByTruncatingTail)


def _make_row_label(text: str, frame: AppKit.NSRect, secondary: bool) -> AppKit.NSTextField:
    """A single-line todo-list row label: primary `labelColor`, or
    `secondaryLabelColor` for read-only (non-builtin) rows -- the visual
    hierarchy that marks them as not actionable.
    """
    label = AppKit.NSTextField.alloc().initWithFrame_(frame)
    _configure_static_label(label)
    label.setFont_(AppKit.NSFont.systemFontOfSize_(12.0))
    label.setTextColor_(
        AppKit.NSColor.secondaryLabelColor() if secondary else AppKit.NSColor.labelColor()
    )
    label.setStringValue_(text)
    return label


def _make_icon_button(
    title: str,
    frame: AppKit.NSRect,
    target: AppKit.NSObject,
    selector: str,
    tag: int,
) -> AppKit.NSButton:
    """A small borderless icon/emoji button for a todo-list row (✓/✕/📌),
    tagged with the builtin todo id it acts on.
    """
    button = AppKit.NSButton.alloc().initWithFrame_(frame)
    button.setBordered_(False)
    button.setButtonType_(AppKit.NSButtonTypeMomentaryChange)
    font = AppKit.NSFont.systemFontOfSize_(13.0)
    attrs = {
        AppKit.NSFontAttributeName: font,
        AppKit.NSForegroundColorAttributeName: AppKit.NSColor.labelColor(),
    }
    button.setAttributedTitle_(
        AppKit.NSAttributedString.alloc().initWithString_attributes_(title, attrs)
    )
    button.setTarget_(target)
    button.setAction_(selector)
    button.setTag_(tag)
    return button


class _PanelWindow(AppKit.NSPanel):
    """The quick-add panel's window.

    A borderless `NSWindowStyleMaskNonactivatingPanel` defaults to never
    becoming key (so its text fields could never accept keystrokes without
    it) -- `canBecomeKeyWindow` overrides that. `resignKeyWindow` hides the
    panel when the user clicks elsewhere, matching a standard popover's
    click-away-to-dismiss behavior.
    """

    controller: _OverlayController | None = None

    def canBecomeKeyWindow(self) -> bool:
        return True

    def resignKeyWindow(self) -> None:
        AppKit.NSPanel.resignKeyWindow(self)
        if self.controller is not None:
            self.controller._hide_panel()


class _QuickAddPanelView(AppKit.NSView):
    """The quick-add panel's rounded background, laid out top-down."""

    def drawRect_(self, rect: AppKit.NSRect) -> None:
        bounds = self.bounds()
        path = AppKit.NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(
            bounds, PANEL_CORNER_RADIUS, PANEL_CORNER_RADIUS
        )
        AppKit.NSColor.windowBackgroundColor().colorWithAlphaComponent_(PANEL_FILL_ALPHA).setFill()
        path.fill()
        AppKit.NSColor.separatorColor().colorWithAlphaComponent_(PANEL_BORDER_ALPHA).setStroke()
        path.setLineWidth_(1.0)
        path.stroke()

    def isFlipped(self) -> bool:
        return True


class _FlippedListView(AppKit.NSView):
    """The todo list's scroll-view document view: top-down row stacking."""

    def isFlipped(self) -> bool:
        return True


def _build_reminder_attributed_text(text: str) -> AppKit.NSAttributedString:
    """Typographic hierarchy for the reminder panel's text field.

    Line 0 (the taunt) is bold/larger and uses `labelColor`; a trailing
    "(+N more)" line uses `secondaryLabelColor`; every other line (todo
    items, and the blank spacer line `core.build_reminder_text` inserts) is
    regular-weight `labelColor`. Content and line order are untouched -- only
    per-line font/color attributes are applied.

    UI-polish compaction (user feedback: "the bubble panel is too tall"):
    the taunt shrunk one step (15pt -> 14pt, still the largest/boldest line
    for hierarchy) and line/paragraph spacing tightened, contributing to a
    visibly shorter panel alongside `BUBBLE_PADDING`/`BUTTON_HEIGHT`.
    """
    taunt_font = AppKit.NSFont.systemFontOfSize_weight_(14.0, AppKit.NSFontWeightSemibold)
    body_font = AppKit.NSFont.systemFontOfSize_weight_(13.0, AppKit.NSFontWeightRegular)

    paragraph_style = AppKit.NSMutableParagraphStyle.alloc().init()
    paragraph_style.setLineSpacing_(1.0)
    paragraph_style.setParagraphSpacing_(1.0)

    result = AppKit.NSMutableAttributedString.alloc().init()
    lines = text.split("\n")
    for index, line in enumerate(lines):
        is_taunt = index == 0
        is_more_suffix = line.startswith("(+") and line.endswith("more)")
        font = taunt_font if is_taunt else body_font
        color = (
            AppKit.NSColor.secondaryLabelColor() if is_more_suffix else AppKit.NSColor.labelColor()
        )
        chunk = line + ("\n" if index < len(lines) - 1 else "")
        attrs = {
            AppKit.NSFontAttributeName: font,
            AppKit.NSForegroundColorAttributeName: color,
            AppKit.NSParagraphStyleAttributeName: paragraph_style,
        }
        result.appendAttributedString_(
            AppKit.NSAttributedString.alloc().initWithString_attributes_(chunk, attrs)
        )
    return result


class _MessagePanelView(AppKit.NSView):
    """`bubble` message-window content: a rounded-rect panel (holding the
    reminder text + Snooze/Quit buttons, added as subviews by the caller)
    occupying the top `bounds.height - panel_bottom` of the view, with a real
    speech-bubble tail (an `NSBezierPath` triangle merged into the panel
    outline) pointing straight down at the character below.

    `flag`'s compact pennant is a different, unrelated content view -- see
    `_FlagPanelView` below.
    """

    panel_bottom: float = 0.0

    def drawRect_(self, rect: AppKit.NSRect) -> None:
        bounds = self.bounds()
        panel_rect = Foundation.NSMakeRect(
            0.0,
            self.panel_bottom,
            bounds.size.width,
            bounds.size.height - self.panel_bottom,
        )

        path = _bubble_tail_path(panel_rect, PANEL_CORNER_RADIUS, BUBBLE_TAIL_WIDTH)

        AppKit.NSColor.windowBackgroundColor().colorWithAlphaComponent_(PANEL_FILL_ALPHA).setFill()
        path.fill()

        AppKit.NSColor.separatorColor().colorWithAlphaComponent_(PANEL_BORDER_ALPHA).setStroke()
        path.setLineWidth_(1.0)
        path.stroke()

    def isFlipped(self) -> bool:
        return False


def _bubble_tail_path(rect: AppKit.NSRect, radius: float, tail_width: float) -> AppKit.NSBezierPath:
    """A rounded-rect outline with a triangular tail merged into the bottom
    edge, centered on `rect`'s x, pointing down from `rect`'s bottom edge to
    the view's origin (y=0) -- toward the character below.
    """
    min_x, min_y = rect.origin.x, rect.origin.y
    max_x, max_y = min_x + rect.size.width, min_y + rect.size.height
    mid_x = min_x + rect.size.width / 2.0
    tail_half = tail_width / 2.0

    path = AppKit.NSBezierPath.bezierPath()
    path.moveToPoint_(Foundation.NSMakePoint(min_x + radius, max_y))
    path.lineToPoint_(Foundation.NSMakePoint(max_x - radius, max_y))
    path.appendBezierPathWithArcWithCenter_radius_startAngle_endAngle_clockwise_(
        Foundation.NSMakePoint(max_x - radius, max_y - radius), radius, 90.0, 0.0, True
    )
    path.lineToPoint_(Foundation.NSMakePoint(max_x, min_y + radius))
    path.appendBezierPathWithArcWithCenter_radius_startAngle_endAngle_clockwise_(
        Foundation.NSMakePoint(max_x - radius, min_y + radius), radius, 0.0, -90.0, True
    )
    path.lineToPoint_(Foundation.NSMakePoint(mid_x + tail_half, min_y))
    path.lineToPoint_(Foundation.NSMakePoint(mid_x, 0.0))
    path.lineToPoint_(Foundation.NSMakePoint(mid_x - tail_half, min_y))
    path.lineToPoint_(Foundation.NSMakePoint(min_x + radius, min_y))
    path.appendBezierPathWithArcWithCenter_radius_startAngle_endAngle_clockwise_(
        Foundation.NSMakePoint(min_x + radius, min_y + radius), radius, -90.0, -180.0, True
    )
    path.lineToPoint_(Foundation.NSMakePoint(min_x, max_y - radius))
    path.appendBezierPathWithArcWithCenter_radius_startAngle_endAngle_clockwise_(
        Foundation.NSMakePoint(min_x + radius, max_y - radius), radius, 180.0, 90.0, True
    )
    path.closePath()
    return path


def _pennant_path(
    rect: AppKit.NSRect,
    radius: float,
    notch_depth: float,
    notch_height: float,
    notch_offset_from_bottom: float,
) -> AppKit.NSBezierPath:
    """A rounded-rect outline with a swallow-tail notch cut into the right
    edge -- the pennant "flutter" flying from the pole drawn separately at
    the view's left edge. `notch_depth` is re-passed every flutter frame
    (see `_FlagPanelView.drawRect_`) so the cut visibly waves in place.
    """
    min_x, min_y = rect.origin.x, rect.origin.y
    max_x, max_y = min_x + rect.size.width, min_y + rect.size.height
    mid_y = min_y + notch_offset_from_bottom
    notch_half = notch_height / 2.0

    path = AppKit.NSBezierPath.bezierPath()
    path.moveToPoint_(Foundation.NSMakePoint(min_x + radius, max_y))
    path.lineToPoint_(Foundation.NSMakePoint(max_x - radius, max_y))
    path.appendBezierPathWithArcWithCenter_radius_startAngle_endAngle_clockwise_(
        Foundation.NSMakePoint(max_x - radius, max_y - radius), radius, 90.0, 0.0, True
    )
    path.lineToPoint_(Foundation.NSMakePoint(max_x, mid_y + notch_half))
    path.lineToPoint_(Foundation.NSMakePoint(max_x - notch_depth, mid_y))
    path.lineToPoint_(Foundation.NSMakePoint(max_x, mid_y - notch_half))
    path.lineToPoint_(Foundation.NSMakePoint(max_x, min_y + radius))
    path.appendBezierPathWithArcWithCenter_radius_startAngle_endAngle_clockwise_(
        Foundation.NSMakePoint(max_x - radius, min_y + radius), radius, 0.0, -90.0, True
    )
    path.lineToPoint_(Foundation.NSMakePoint(min_x + radius, min_y))
    path.appendBezierPathWithArcWithCenter_radius_startAngle_endAngle_clockwise_(
        Foundation.NSMakePoint(min_x + radius, min_y + radius), radius, -90.0, -180.0, True
    )
    path.lineToPoint_(Foundation.NSMakePoint(min_x, max_y - radius))
    path.appendBezierPathWithArcWithCenter_radius_startAngle_endAngle_clockwise_(
        Foundation.NSMakePoint(min_x + radius, max_y - radius), radius, 180.0, 90.0, True
    )
    path.closePath()
    return path


def _build_flag_attributed_text(text: str) -> AppKit.NSAttributedString:
    """Single-line semibold text for the compact flag pennant -- a lighter
    typographic treatment than the bubble's taunt/body hierarchy
    (`_build_reminder_attributed_text`), since there's only ever one line.
    """
    font = AppKit.NSFont.systemFontOfSize_weight_(FLAG_TEXT_FONT_SIZE, AppKit.NSFontWeightSemibold)
    attrs = {
        AppKit.NSFontAttributeName: font,
        AppKit.NSForegroundColorAttributeName: AppKit.NSColor.labelColor(),
    }
    return AppKit.NSAttributedString.alloc().initWithString_attributes_(text, attrs)


def _flutter_notch_offset(elapsed_seconds: float) -> float:
    """The pennant's notch-depth wobble at `elapsed_seconds` into its
    flutter -- a small sine wave so the swallow-tail visibly waves like
    cloth in the wind, not a glitch. Pure and AppKit-free by design (though
    this module still requires pyobjc to import), so it's trivial to sample
    at arbitrary times for verification without a real timer/event loop.
    """
    phase = 2.0 * math.pi * FLAG_FLUTTER_FREQUENCY_HZ * elapsed_seconds
    return FLAG_FLUTTER_AMPLITUDE_PX * math.sin(phase)


class _FlagPanelView(AppKit.NSView):
    """Compact `flag` message-window content: a single-line pennant with a
    real swallow-tail notch cut into its right edge (see `_pennant_path`),
    flying from a thin pole strip at the view's left edge that connects down
    toward the character, plus the fire's text drawn directly onto the panel
    (no subviews -- see `set_text`). No buttons on this style: the whole
    panel is clickable, and a click snoozes exactly like the bubble's Snooze
    button (`mouseDown_` below, wired to the same `onSnoozeClicked_`).

    `flutter_offset`, refreshed every flutter frame by the controller (see
    `_OverlayController._apply_flutter_frame`), nudges the notch depth to
    animate the "wind" flutter; `0.0` (its default) draws the notch at its
    resting depth.
    """

    controller: _OverlayController | None = None
    panel_bottom: float = 0.0
    pole_inset: float = 0.0
    pole_width: float = 0.0
    flutter_offset: float = 0.0
    _text: AppKit.NSAttributedString | None = None
    _text_x: float = 0.0

    @objc.python_method
    def set_text(self, attributed: AppKit.NSAttributedString, text_x: float) -> None:
        self._text = attributed
        self._text_x = text_x

    def drawRect_(self, rect: AppKit.NSRect) -> None:
        bounds = self.bounds()
        panel_rect = Foundation.NSMakeRect(
            0.0,
            self.panel_bottom,
            bounds.size.width,
            bounds.size.height - self.panel_bottom,
        )

        notch_depth = max(1.0, FLAG_NOTCH_DEPTH + self.flutter_offset)
        path = _pennant_path(
            panel_rect,
            FLAG_CORNER_RADIUS,
            notch_depth,
            FLAG_NOTCH_HEIGHT,
            FLAG_NOTCH_OFFSET_FROM_PANEL_BOTTOM,
        )

        AppKit.NSColor.windowBackgroundColor().colorWithAlphaComponent_(PANEL_FILL_ALPHA).setFill()
        path.fill()

        AppKit.NSColor.separatorColor().colorWithAlphaComponent_(PANEL_BORDER_ALPHA).setStroke()
        path.setLineWidth_(1.0)
        path.stroke()

        if self.panel_bottom > 0.0:
            pole_rect = Foundation.NSMakeRect(
                self.pole_inset, 0.0, self.pole_width, self.panel_bottom
            )
            AppKit.NSColor.windowBackgroundColor().colorWithAlphaComponent_(
                PANEL_FILL_ALPHA
            ).setFill()
            AppKit.NSBezierPath.bezierPathWithRect_(pole_rect).fill()

        if self._text is not None:
            text_height = self._text.size().height
            available = bounds.size.height - self.panel_bottom - text_height
            text_y = self.panel_bottom + available / 2.0
            self._text.drawAtPoint_(Foundation.NSMakePoint(self._text_x, text_y))

    def isFlipped(self) -> bool:
        return False

    def mouseDown_(self, event: AppKit.NSEvent) -> None:
        # No buttons on the compact flag -- clicking anywhere on the
        # pennant snoozes, alarm-aware exactly like the bubble's Snooze
        # button.
        if self.controller is not None:
            self.controller.onSnoozeClicked_(self)


class _BannerPanelView(AppKit.NSView):
    """Banner-below message-window content (M13 Task 32, `persona.banner`):
    the same single-line pennant panel as `_FlagPanelView` (swallow-tail
    notch, flutter, click-anywhere-to-snooze), but occupying the BOTTOM of
    the view -- `[0, panel_height]` -- with two thin string lines drawn
    above it, from two spread points at the view's top (roughly the
    character's left/right foot, just off the top of this window -- see
    `BANNER_FOOT_SPREAD_PX`) down to the panel's top-left and top-right
    corners. Reads as a banner towed by a plane rather than a pennant on a
    pole.

    `flutter_offset`/`set_text` match `_FlagPanelView` exactly, so the
    controller's flutter/text plumbing (`_start_flutter`,
    `_apply_flutter_frame`) works unchanged against either view.
    """

    controller: _OverlayController | None = None
    panel_height: float = 0.0
    string_inset: float = 0.0
    flutter_offset: float = 0.0
    _text: AppKit.NSAttributedString | None = None
    _text_x: float = 0.0

    @objc.python_method
    def set_text(self, attributed: AppKit.NSAttributedString, text_x: float) -> None:
        self._text = attributed
        self._text_x = text_x

    def drawRect_(self, rect: AppKit.NSRect) -> None:
        bounds = self.bounds()
        panel_rect = Foundation.NSMakeRect(0.0, 0.0, bounds.size.width, self.panel_height)

        notch_depth = max(1.0, FLAG_NOTCH_DEPTH + self.flutter_offset)
        path = _pennant_path(
            panel_rect,
            FLAG_CORNER_RADIUS,
            notch_depth,
            FLAG_NOTCH_HEIGHT,
            FLAG_NOTCH_OFFSET_FROM_PANEL_BOTTOM,
        )

        AppKit.NSColor.windowBackgroundColor().colorWithAlphaComponent_(PANEL_FILL_ALPHA).setFill()
        path.fill()

        AppKit.NSColor.separatorColor().colorWithAlphaComponent_(PANEL_BORDER_ALPHA).setStroke()
        path.setLineWidth_(1.0)
        path.stroke()

        if bounds.size.height > self.panel_height:
            top_y = bounds.size.height
            center_x = bounds.size.width / 2.0
            # Two spread top attach points (left-foot/right-foot), not one
            # shared top-center point -- see BANNER_FOOT_SPREAD_PX.
            half_spread = min(BANNER_FOOT_SPREAD_PX / 2.0, center_x)
            left_foot_x = center_x - half_spread
            right_foot_x = center_x + half_spread
            left_x = self.string_inset
            right_x = bounds.size.width - self.string_inset
            strings = AppKit.NSBezierPath.bezierPath()
            strings.moveToPoint_(Foundation.NSMakePoint(left_foot_x, top_y))
            strings.lineToPoint_(Foundation.NSMakePoint(left_x, self.panel_height))
            strings.moveToPoint_(Foundation.NSMakePoint(right_foot_x, top_y))
            strings.lineToPoint_(Foundation.NSMakePoint(right_x, self.panel_height))
            AppKit.NSColor.secondaryLabelColor().setStroke()
            strings.setLineWidth_(1.0)
            strings.stroke()

        if self._text is not None:
            text_height = self._text.size().height
            available = self.panel_height - text_height
            text_y = available / 2.0
            self._text.drawAtPoint_(Foundation.NSMakePoint(self._text_x, text_y))

    def isFlipped(self) -> bool:
        return False

    def mouseDown_(self, event: AppKit.NSEvent) -> None:
        # No buttons on the compact banner -- clicking anywhere on the
        # panel snoozes, alarm-aware exactly like the bubble's Snooze
        # button (same behavior as `_FlagPanelView.mouseDown_`).
        if self.controller is not None:
            self.controller.onSnoozeClicked_(self)


# --- sprite animation: NSImage construction (the one AppKit-touching part) ----


def _render_pixel_grid(
    rows: tuple[str, ...], palette: dict[str, str], scale: float
) -> AppKit.NSImage:
    """Render one pixel-art frame (a tuple of equal-length row strings, per
    `SpriteSheet.states`) to an `NSImage`: an `NSBitmapImageRep` built at
    native (1 source char = 1 pixel) resolution, then wrapped in an
    `NSImage` sized up by `scale` -- drawing at that larger size with
    nearest-neighbor interpolation (`_CharacterView._draw_image_centered`,
    `pixel_perfect=True`) is what keeps the blown-up pixels crisp instead of
    blurred. `palette[' ']` is never consulted -- a space is always fully
    transparent, per contract section 1 ("' ' = transparent"), regardless of
    whether the sheet's palette dict happens to define a ' ' entry.

    Row 0 is the frame's TOP row (matches how the pixel grids read visually
    in pixelart.py's source, top-to-bottom) -- `NSBitmapImageRep.
    setColor_atX_y_` addresses pixel (0, 0) at the top-left, so no y-flip is
    needed to keep that orientation.
    """
    height = len(rows)
    width = len(rows[0]) if height else 0
    rep_cls = AppKit.NSBitmapImageRep
    # fmt: off
    bitmap = rep_cls.alloc().initWithBitmapDataPlanes_pixelsWide_pixelsHigh_bitsPerSample_samplesPerPixel_hasAlpha_isPlanar_colorSpaceName_bytesPerRow_bitsPerPixel_(  # noqa: E501
        None,
        max(width, 1),
        max(height, 1),
        8,
        4,
        True,
        False,
        AppKit.NSDeviceRGBColorSpace,
        0,
        32,
    )
    # fmt: on
    transparent = AppKit.NSColor.colorWithDeviceRed_green_blue_alpha_(0.0, 0.0, 0.0, 0.0)
    for y, row in enumerate(rows):
        for x, ch in enumerate(row):
            if ch == " ":
                color = transparent
            else:
                r, g, b, a = parse_palette_color(palette[ch])
                color = AppKit.NSColor.colorWithDeviceRed_green_blue_alpha_(
                    r / 255.0, g / 255.0, b / 255.0, a / 255.0
                )
            bitmap.setColor_atX_y_(color, x, y)

    image = AppKit.NSImage.alloc().initWithSize_(
        Foundation.NSMakeSize(width * scale, height * scale)
    )
    image.addRepresentation_(bitmap)
    return image


_cached_emoji_draw_attrs: dict[str, AppKit.NSFont] | None = None


def _emoji_draw_attrs() -> dict[str, AppKit.NSFont]:
    """Lazily build, then cache, the font/attributes dict used to draw the
    character's emoji (`_CharacterView._draw_content`). `EMOJI_FONT_SIZE`
    never changes at runtime, so there's nothing to invalidate -- built
    once, on the main thread the first time a character view draws, and
    reused for the life of the process. Avoids reallocating an `NSFont` +
    dict on every `drawRect_` call, which -- with gallop's continuously
    varying squash-stretch -- happens on essentially every 30fps wander
    tick (Codex review follow-up, M12 Task 29 nit)."""
    global _cached_emoji_draw_attrs
    if _cached_emoji_draw_attrs is None:
        font = AppKit.NSFont.systemFontOfSize_(EMOJI_FONT_SIZE)
        _cached_emoji_draw_attrs = {AppKit.NSFontAttributeName: font}
    return _cached_emoji_draw_attrs


class _CharacterView(AppKit.NSView):
    """Draws the character (user image or large emoji) and handles clicks.

    `facing`/`squash_scale`/`extra_scale` (set by `_OverlayController.
    _apply_character_orientation`, driven by `CharacterMovement.facing`/
    gallop's `y_offset`/the active entrance-or-flourish curve's `scale`) are
    purely cosmetic -- they only affect what `drawRect_` paints, applied as
    a graphics-state transform saved/restored around the draw calls. They
    never touch the view's frame/bounds, so hit-testing (`mouseDown_`, and
    AppKit's own click routing) is completely unaffected.
    """

    controller: _OverlayController
    emoji: str = ""
    _image: AppKit.NSImage | None = None
    # +1 (moving right) draws mirrored, -1 (left) draws normal -- Apple's
    # animal/vehicle emoji all face left, per contract section 4.
    facing: int = 1
    # Gallop-only squash-stretch, synced to bounce phase; 1.0 (no-op) for
    # every other movement -- see GALLOP_SQUASH_SCALE_MIN/MAX above.
    squash_scale: float = 1.0
    # Launch-entrance / fire-time-flourish uniform scale (M13 Task 32):
    # `personas.EntranceAnimation`/`FlourishAnimation`'s `scale` output,
    # applied on top of `squash_scale`; 1.0 (no-op) when neither is active.
    extra_scale: float = 1.0
    # Emoji draw-call cache (Codex review follow-up, M12 Task 29 nit): with
    # gallop's squash-stretch continuously varying `squash_scale`,
    # `drawRect_` fires on essentially every 30fps wander tick -- caching
    # the built-once NSString (per `self.emoji`, which is set once at
    # construction and never changes) avoids reallocating it on every draw.
    # The font/attrs dict is cached module-wide, below.
    _cached_emoji_text: AppKit.NSString | None = None
    _cached_emoji_source: str = ""

    # Sprite mode (M14 Task 35): `state -> [NSImage, ...]` built once by
    # `_OverlayController._load_character_sprite` (either a code pixel-art
    # pack or a user PNG folder) and set directly here, like `facing`/
    # `emoji` -- `None` (the default) means "no sprite", so an emoji/
    # character_image character never even looks at these fields. When set,
    # `_draw_content` prefers it over `_image`/`emoji` (see there).
    # `sprite_pixel_perfect` selects nearest-neighbor scaling (code pixel
    # art, always blocky by design) vs. the normal smooth interpolation
    # (user PNGs, which may not be pixel art at all) -- `_draw_image_
    # centered`. `sprite_state`/`sprite_frame_index` are updated every
    # wander tick by `_OverlayController._advance_sprite_animation`.
    sprite_frames: dict[str, list] | None = None
    sprite_pixel_perfect: bool = False
    sprite_state: str = "idle"
    sprite_frame_index: int = 0

    @objc.python_method
    def set_image(self, image: AppKit.NSImage | None) -> None:
        self._image = image

    def drawRect_(self, rect: AppKit.NSRect) -> None:
        bounds = self.bounds()
        context = AppKit.NSGraphicsContext.currentContext()
        context.saveGraphicsState()
        try:
            center_x = bounds.size.width / 2.0
            center_y = bounds.size.height / 2.0
            transform = AppKit.NSAffineTransform.transform()
            transform.translateXBy_yBy_(center_x, center_y)
            transform.scaleXBy_yBy_(
                (-1.0 if self.facing >= 0 else 1.0) * self.extra_scale,
                self.squash_scale * self.extra_scale,
            )
            transform.translateXBy_yBy_(-center_x, -center_y)
            transform.concat()
            self._draw_content(bounds)
        finally:
            context.restoreGraphicsState()

    @objc.python_method
    def _draw_content(self, bounds: AppKit.NSRect) -> None:
        if self.sprite_frames is not None:
            frame_list = sprite_frames_for_state(self.sprite_frames, self.sprite_state)
            if frame_list:
                index = self.sprite_frame_index % len(frame_list)
                self._draw_image_centered(bounds, frame_list[index], self.sprite_pixel_perfect)
                return

        if self._image is not None:
            self._draw_image_centered(bounds, self._image, pixel_perfect=False)
            return

        attrs = _emoji_draw_attrs()
        if self._cached_emoji_text is None or self._cached_emoji_source != self.emoji:
            self._cached_emoji_text = Foundation.NSString.stringWithString_(self.emoji)
            self._cached_emoji_source = self.emoji
        text = self._cached_emoji_text
        text_size = text.sizeWithAttributes_(attrs)
        origin = Foundation.NSMakePoint(
            (bounds.size.width - text_size.width) / 2,
            (bounds.size.height - text_size.height) / 2,
        )
        text.drawAtPoint_withAttributes_(origin, attrs)

    @objc.python_method
    def _draw_image_centered(
        self, bounds: AppKit.NSRect, image: AppKit.NSImage, pixel_perfect: bool
    ) -> None:
        """Draw `image` centered in `bounds`. `pixel_perfect` (code sprite
        frames only -- see `sprite_pixel_perfect`) forces nearest-neighbor
        interpolation for the duration of this one draw call so the blown-up
        pixel grid stays crisp; static `character_image`/user sprite PNGs
        keep AppKit's normal smooth interpolation, unchanged from before
        this sprite work (the `_image` path below used to draw inline here
        with no interpolation override at all)."""
        size = image.size()
        origin = Foundation.NSMakePoint(
            (bounds.size.width - size.width) / 2,
            (bounds.size.height - size.height) / 2,
        )
        if not pixel_perfect:
            image.drawAtPoint_fromRect_operation_fraction_(
                origin,
                Foundation.NSZeroRect,
                AppKit.NSCompositingOperationSourceOver,
                1.0,
            )
            return

        context = AppKit.NSGraphicsContext.currentContext()
        previous = context.imageInterpolation()
        context.setImageInterpolation_(AppKit.NSImageInterpolationNone)
        try:
            image.drawAtPoint_fromRect_operation_fraction_(
                origin,
                Foundation.NSZeroRect,
                AppKit.NSCompositingOperationSourceOver,
                1.0,
            )
        finally:
            context.setImageInterpolation_(previous)

    def mouseDown_(self, event: AppKit.NSEvent) -> None:
        # Clicking the character shows the current reminder on demand
        # (no state change beyond what showing-a-bubble already implies).
        controller = self.controller
        controller._show_reminder()

    def isFlipped(self) -> bool:
        return False
