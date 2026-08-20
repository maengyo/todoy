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

from contextlib import contextmanager
from typing import TYPE_CHECKING

import AppKit
import Foundation
import objc

from todoy.display.overlay.animations import CharacterMovement

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator
    from pathlib import Path

    from todoy.display.overlay.base import OverlayOptions
    from todoy.display.overlay.core import ReminderScheduler

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

BUBBLE_WIDTH = 300.0
BUBBLE_TEXT_HEIGHT = 120.0
BUBBLE_BUTTON_ROW_HEIGHT = 40.0
BUBBLE_PADDING = 12.0
BUBBLE_HEIGHT = BUBBLE_TEXT_HEIGHT + BUBBLE_BUTTON_ROW_HEIGHT + BUBBLE_PADDING * 2
BUBBLE_GAP_ABOVE_CHARACTER = 8.0


class MacOSOverlayBackend:
    """AppKit-based `OverlayBackend`: floating character + reminder bubble."""

    def run(
        self,
        options: OverlayOptions,
        scheduler: ReminderScheduler,
        get_reminder_text: Callable[[], str],
    ) -> int:
        app = AppKit.NSApplication.sharedApplication()
        app.setActivationPolicy_(AppKit.NSApplicationActivationPolicyAccessory)

        controller = _OverlayController.alloc().init()
        controller.configure(options, scheduler, get_reminder_text, app)
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
        app: AppKit.NSApplication,
    ) -> _OverlayController:
        self.options = options
        self.scheduler = scheduler
        self.get_reminder_text = get_reminder_text
        self.app = app
        self.movement: CharacterMovement | None = None
        self.char_window: AppKit.NSWindow | None = None
        self.char_view: _CharacterView | None = None
        self.bubble_window: AppKit.NSWindow | None = None
        self.bubble_text_field: AppKit.NSTextField | None = None
        self.hide_timer: AppKit.NSTimer | None = None
        self.shake_timer: AppKit.NSTimer | None = None
        self._shake_base_origin: AppKit.NSPoint | None = None
        self._shake_step_index = 0
        self.wander_timer: AppKit.NSTimer | None = None
        self.reminder_timer: AppKit.NSTimer | None = None
        self.first_fire_timer: AppKit.NSTimer | None = None
        self.test_timeout_timer: AppKit.NSTimer | None = None
        return self

    @objc.python_method
    def start(self) -> None:
        self._build_character_window()
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
        if self.bubble_window is not None and self.bubble_window.isVisible():
            self._position_bubble()

    # --- reminder scheduling -------------------------------------------------

    def onReminderTick_(self, timer: AppKit.NSTimer) -> None:
        if self.scheduler.should_fire():
            self._show_reminder()
            self.scheduler.fired()

    def onFirstFire_(self, timer: AppKit.NSTimer) -> None:
        # Guaranteed early reminder so the user sees the overlay works,
        # regardless of the configured interval. Also resets the regular
        # schedule from this point so a second reminder does not double-fire.
        self._show_reminder()
        self.scheduler.fired()

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
        ):
            if timer is not None:
                timer.invalidate()
        self.wander_timer = None
        self.reminder_timer = None
        self.first_fire_timer = None
        self.test_timeout_timer = None
        self.hide_timer = None
        self.shake_timer = None

    # --- reminder bubble ---------------------------------------------------

    @objc.python_method
    def _show_reminder(self) -> None:
        text = self.get_reminder_text()
        if self.bubble_window is None:
            self._build_bubble_window()
        assert self.bubble_window is not None
        assert self.bubble_text_field is not None
        self._cancel_bubble_shake()
        self.bubble_text_field.setStringValue_(text)
        self._position_bubble()
        self._apply_bubble_entrance_effect()
        self._reset_hide_timer()

    @objc.python_method
    def _build_bubble_window(self) -> None:
        frame = Foundation.NSMakeRect(0, 0, BUBBLE_WIDTH, BUBBLE_HEIGHT)
        window = AppKit.NSPanel.alloc().initWithContentRect_styleMask_backing_defer_(
            frame,
            AppKit.NSWindowStyleMaskBorderless | AppKit.NSWindowStyleMaskNonactivatingPanel,
            AppKit.NSBackingStoreBuffered,
            False,
        )
        window.setOpaque_(False)
        window.setBackgroundColor_(AppKit.NSColor.clearColor())
        window.setLevel_(AppKit.NSFloatingWindowLevel)
        window.setCollectionBehavior_(
            AppKit.NSWindowCollectionBehaviorCanJoinAllSpaces
            | AppKit.NSWindowCollectionBehaviorStationary
        )

        content = AppKit.NSView.alloc().initWithFrame_(frame)
        content.setWantsLayer_(True)
        content.layer().setBackgroundColor_(
            AppKit.NSColor.windowBackgroundColor().colorWithAlphaComponent_(0.97).CGColor()
        )
        content.layer().setCornerRadius_(12.0)

        text_field = AppKit.NSTextField.alloc().initWithFrame_(
            Foundation.NSMakeRect(
                BUBBLE_PADDING,
                BUBBLE_BUTTON_ROW_HEIGHT + BUBBLE_PADDING,
                BUBBLE_WIDTH - BUBBLE_PADDING * 2,
                BUBBLE_TEXT_HEIGHT,
            )
        )
        text_field.setEditable_(False)
        text_field.setSelectable_(False)
        text_field.setBezeled_(False)
        text_field.setDrawsBackground_(False)
        text_field.setFont_(AppKit.NSFont.systemFontOfSize_(13.0))
        text_field.setLineBreakMode_(AppKit.NSLineBreakByWordWrapping)
        text_field.cell().setWraps_(True)
        content.addSubview_(text_field)

        snooze_label = f"Snooze {self.scheduler.snooze_minutes}m"
        snooze_button = _make_button(
            snooze_label,
            Foundation.NSMakeRect(BUBBLE_PADDING, BUBBLE_PADDING, 130, 28),
            self,
            "onSnoozeClicked:",
        )
        quit_button = _make_button(
            "Quit",
            Foundation.NSMakeRect(BUBBLE_WIDTH - BUBBLE_PADDING - 80, BUBBLE_PADDING, 80, 28),
            self,
            "onQuitClicked:",
        )
        content.addSubview_(snooze_button)
        content.addSubview_(quit_button)

        window.setContentView_(content)

        self.bubble_window = window
        self.bubble_text_field = text_field

    @objc.python_method
    def _position_bubble(self) -> None:
        if self.char_window is None or self.bubble_window is None:
            return
        char_frame = self.char_window.frame()
        x = char_frame.origin.x + char_frame.size.width / 2 - BUBBLE_WIDTH / 2
        y = char_frame.origin.y + char_frame.size.height + BUBBLE_GAP_ABOVE_CHARACTER
        self.bubble_window.setFrameOrigin_(Foundation.NSMakePoint(x, y))

    @objc.python_method
    def _apply_bubble_entrance_effect(self) -> None:
        """Show `self.bubble_window` using `self.options.bubble_effect`.

        `_position_bubble()` must already have set the window's *target*
        frame before this runs. pop/fade/slide animate via
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
            self._start_bubble_shake(target_frame.origin)
            return

        # "none" (and any future unvalidated fallback): appear instantly.
        window.setAlphaValue_(1.0)
        window.setFrame_display_(target_frame, False)
        window.orderFrontRegardless()

    @objc.python_method
    def _start_bubble_shake(self, base_origin: AppKit.NSPoint) -> None:
        self._shake_base_origin = base_origin
        self._shake_step_index = 0
        self._fire_bubble_shake_step()

    @objc.python_method
    def _fire_bubble_shake_step(self) -> None:
        window = self.bubble_window
        base_origin = self._shake_base_origin
        if window is None or base_origin is None:
            return

        total_steps = BUBBLE_SHAKE_OSCILLATIONS * 2
        if self._shake_step_index >= total_steps:
            window.setFrameOrigin_(base_origin)
            self._shake_base_origin = None
            return

        direction = 1.0 if self._shake_step_index % 2 == 0 else -1.0
        x = base_origin.x + direction * BUBBLE_SHAKE_AMPLITUDE_PX
        window.setFrameOrigin_(Foundation.NSMakePoint(x, base_origin.y))
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
        self._shake_base_origin = None

    @objc.python_method
    def _reset_hide_timer(self) -> None:
        if self.hide_timer is not None:
            self.hide_timer.invalidate()
        self.hide_timer = (
            AppKit.NSTimer.scheduledTimerWithTimeInterval_target_selector_userInfo_repeats_(
                BUBBLE_AUTO_HIDE_SECONDS, self, "onHideBubble:", None, False
            )
        )

    def onHideBubble_(self, timer: AppKit.NSTimer) -> None:
        self._hide_bubble()

    @objc.python_method
    def _hide_bubble(self) -> None:
        self._cancel_bubble_shake()
        if self.bubble_window is not None:
            self.bubble_window.orderOut_(None)
        if self.hide_timer is not None:
            self.hide_timer.invalidate()
            self.hide_timer = None

    # --- bubble button actions ----------------------------------------------

    def onSnoozeClicked_(self, sender: AppKit.NSButton) -> None:
        self.scheduler.snooze()
        self._hide_bubble()

    def onQuitClicked_(self, sender: AppKit.NSButton) -> None:
        # Ends this process only; the overlay returns on next `todoy overlay`
        # launch. No permanent mute / no todo-completion controls here.
        self._invalidate_all_timers()
        self.app.terminate_(None)


def _scaled_frame(frame: AppKit.NSRect, scale: float) -> AppKit.NSRect:
    """`frame` shrunk/grown by `scale`, keeping the same center point."""
    new_width = frame.size.width * scale
    new_height = frame.size.height * scale
    new_x = frame.origin.x + (frame.size.width - new_width) / 2.0
    new_y = frame.origin.y + (frame.size.height - new_height) / 2.0
    return Foundation.NSMakeRect(new_x, new_y, new_width, new_height)


@contextmanager
def _animation_group(duration: float) -> Iterator[None]:
    """Run an `.animator()`-proxied change over `duration` seconds."""
    AppKit.NSAnimationContext.beginGrouping()
    try:
        AppKit.NSAnimationContext.currentContext().setDuration_(duration)
        yield
    finally:
        AppKit.NSAnimationContext.endGrouping()


def _make_button(
    title: str,
    frame: AppKit.NSRect,
    target: AppKit.NSObject,
    selector: str,
) -> AppKit.NSButton:
    button = AppKit.NSButton.alloc().initWithFrame_(frame)
    button.setTitle_(title)
    button.setBezelStyle_(AppKit.NSBezelStyleRounded)
    button.setTarget_(target)
    button.setAction_(selector)
    return button


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
