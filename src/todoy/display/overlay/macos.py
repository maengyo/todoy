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
from todoy.display.overlay.animations import CharacterMovement
from todoy.display.overlay.core import (
    AlarmClock,
    build_alarm_flag_line,
    build_alarm_text,
    build_flag_line,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator
    from pathlib import Path

    from todoy.display.overlay.base import OverlayOptions, PanelActions
    from todoy.display.overlay.core import ReminderScheduler
    from todoy.models import Todo

# --- tunables ----------------------------------------------------------------

FIRST_FIRE_DELAY_SECONDS = 5.0
WANDER_TICK_SECONDS = 0.15
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

BUBBLE_WIDTH = 320.0
BUBBLE_TEXT_HEIGHT = 132.0
BUBBLE_BUTTON_ROW_HEIGHT = 44.0
BUBBLE_PADDING = 18.0
BUBBLE_HEIGHT = BUBBLE_TEXT_HEIGHT + BUBBLE_BUTTON_ROW_HEIGHT + BUBBLE_PADDING * 2
BUBBLE_GAP_ABOVE_CHARACTER = 6.0

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
BUTTON_HEIGHT = 30.0
BUTTON_CORNER_RADIUS = 8.0
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
        self.flag_view: _FlagPanelView | None = None
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
    def _build_character_window(self) -> None:
        screen_frame = self._screen_frame()
        size = CHARACTER_WINDOW_SIZE
        travel_width = max(0.0, screen_frame.size.width - size)
        self.movement = CharacterMovement(self.options.movement, travel_width=travel_width)

        x, y_offset = self.movement.step(0.0)
        start_x = screen_frame.origin.x + x
        start_y = screen_frame.origin.y + CHARACTER_BOTTOM_MARGIN + y_offset
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
        window.setContentView_(content_view)
        window.orderFrontRegardless()

        self.char_window = window
        self.char_view = content_view

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

    # --- wandering ---------------------------------------------------------

    def onWanderTick_(self, timer: AppKit.NSTimer) -> None:
        window = self.char_window
        if window is None or self.movement is None:
            return

        screen_frame = self._screen_frame()
        x, y_offset = self.movement.step(WANDER_TICK_SECONDS)
        new_x = screen_frame.origin.x + x
        new_y = screen_frame.origin.y + CHARACTER_BOTTOM_MARGIN + y_offset

        window.setFrameOrigin_(Foundation.NSMakePoint(new_x, new_y))

        # Only `flag` rides along with the character every tick; `bubble`
        # appears at show-time position and stays put until hidden, per the
        # message-style contract.
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

        For `flag` this is clamped to the screen (contract: "the flag must
        stay fully on screen"); `bubble` is left unclamped, matching its
        pre-existing behavior.
        """
        if self.char_window is None or self.bubble_window is None:
            return None
        char_frame = self.char_window.frame()
        window_width = self.bubble_window.frame().size.width
        x = char_frame.origin.x + char_frame.size.width / 2 - window_width / 2

        if self.options.message_style == "flag":
            y = char_frame.origin.y + char_frame.size.height + FLAG_GAP_ABOVE_CHARACTER
            x = self._clamp_x_to_screen(x, window_width)
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
        """
        window = self.bubble_window
        assert window is not None
        effect = self.options.bubble_effect
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
    font = AppKit.NSFont.systemFontOfSize_weight_(13.0, AppKit.NSFontWeightSemibold)
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
    font = AppKit.NSFont.systemFontOfSize_weight_(13.0, AppKit.NSFontWeightRegular)
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
    """
    taunt_font = AppKit.NSFont.systemFontOfSize_weight_(15.0, AppKit.NSFontWeightSemibold)
    body_font = AppKit.NSFont.systemFontOfSize_weight_(13.0, AppKit.NSFontWeightRegular)

    paragraph_style = AppKit.NSMutableParagraphStyle.alloc().init()
    paragraph_style.setLineSpacing_(3.0)
    paragraph_style.setParagraphSpacing_(2.0)

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


class _CharacterView(AppKit.NSView):
    """Draws the character (user image or large emoji) and handles clicks."""

    controller: _OverlayController
    emoji: str = ""
    _image: AppKit.NSImage | None = None

    @objc.python_method
    def set_image(self, image: AppKit.NSImage | None) -> None:
        self._image = image

    def drawRect_(self, rect: AppKit.NSRect) -> None:
        bounds = self.bounds()
        if self._image is not None:
            size = self._image.size()
            origin = Foundation.NSMakePoint(
                (bounds.size.width - size.width) / 2,
                (bounds.size.height - size.height) / 2,
            )
            self._image.drawAtPoint_fromRect_operation_fraction_(
                origin,
                Foundation.NSZeroRect,
                AppKit.NSCompositingOperationSourceOver,
                1.0,
            )
            return

        font = AppKit.NSFont.systemFontOfSize_(EMOJI_FONT_SIZE)
        attrs = {AppKit.NSFontAttributeName: font}
        text = Foundation.NSString.stringWithString_(self.emoji)
        text_size = text.sizeWithAttributes_(attrs)
        origin = Foundation.NSMakePoint(
            (bounds.size.width - text_size.width) / 2,
            (bounds.size.height - text_size.height) / 2,
        )
        text.drawAtPoint_withAttributes_(origin, attrs)

    def mouseDown_(self, event: AppKit.NSEvent) -> None:
        # Clicking the character shows the current reminder on demand
        # (no state change beyond what showing-a-bubble already implies).
        controller = self.controller
        controller._show_reminder()

    def isFlipped(self) -> bool:
        return False
