"""macOS-gated tests for the menu-bar quick-add panel controller logic.

Everything here exercises `_OverlayController` methods directly (no real
clicks, no `app.run()` loop) -- similar in spirit to the alarm/reminder
interleaving test in `test_overlay_base.py`. Skipped on any non-macOS
platform or when pyobjc isn't installed, so it never breaks CI elsewhere.
"""

from __future__ import annotations

import sys
import types
from collections.abc import Callable

import pytest

from todoy.display.characters import Character
from todoy.display.overlay.base import OverlayOptions, PanelActions
from todoy.models import Todo


class _FakeSender:
    """Stand-in for an NSButton row-action sender: only `.tag()` is used."""

    def __init__(self, tag: int) -> None:
        self._tag = tag

    def tag(self) -> int:
        return self._tag


def _noop_actions() -> PanelActions:
    return PanelActions(
        add=lambda text, at: None,
        set_done=lambda todo_id: None,
        delete=lambda todo_id: None,
        set_pinned=lambda todo_id, pinned: None,
    )


def _build_started_controller(get_todos: Callable[[], list], actions: PanelActions):
    """Skip on non-macOS/no-pyobjc; otherwise build+start a real
    `_OverlayController` wired to `get_todos`/`actions` for panel testing.

    Caller is responsible for invalidating timers (`controller.
    _invalidate_all_timers()`) in a `finally` block when done, same as the
    alarm-interleaving test in `test_overlay_base.py`.
    """
    if sys.platform != "darwin":
        pytest.skip("AppKit only available on macOS")
    pytest.importorskip("AppKit")

    import AppKit

    from todoy.display.overlay.macos import _OverlayController

    options = OverlayOptions(
        character=Character(name="cat", emoji="🐱", ascii_art="(=^.^=)"),
        character_image=None,
        language="en",
        test_seconds=None,
    )
    scheduler = types.SimpleNamespace(snooze_minutes=5)

    app = AppKit.NSApplication.sharedApplication()
    app.setActivationPolicy_(AppKit.NSApplicationActivationPolicyAccessory)

    controller = _OverlayController.alloc().init()
    controller.configure(options, scheduler, lambda: "", get_todos, actions, app)
    controller.start()
    return controller


def test_start_creates_a_status_item_showing_the_character_emoji() -> None:
    controller = _build_started_controller(lambda: [], _noop_actions())
    try:
        assert controller.status_item is not None
        assert str(controller.status_item.button().title()) == "🐱"
    finally:
        controller._invalidate_all_timers()


def test_status_item_click_toggles_the_panel_open_and_closed() -> None:
    controller = _build_started_controller(lambda: [], _noop_actions())
    try:
        assert controller.panel_window is None

        controller.onStatusItemClicked_(None)
        assert controller.panel_window is not None
        assert controller.panel_window.isVisible() is True

        controller.onStatusItemClicked_(None)
        assert controller.panel_window.isVisible() is False
    finally:
        controller._invalidate_all_timers()


def test_opening_the_panel_refreshes_the_todo_list() -> None:
    calls: list[int] = []

    def get_todos() -> list:
        calls.append(1)
        return [Todo(text="A", id=1)]

    controller = _build_started_controller(get_todos, _noop_actions())
    try:
        before = len(calls)
        controller.onStatusItemClicked_(None)  # opens -> should refresh
        assert len(calls) > before
        assert len(controller.panel_list_view.subviews()) == 1
    finally:
        controller._invalidate_all_timers()


def test_add_success_clears_fields_and_refreshes_list() -> None:
    state: list[Todo] = []
    add_calls: list[tuple[str, str | None]] = []

    def add(text: str, at: str | None) -> str | None:
        add_calls.append((text, at))
        state.append(Todo(text=text, id=1))
        return None

    actions = PanelActions(
        add=add,
        set_done=lambda todo_id: None,
        delete=lambda todo_id: None,
        set_pinned=lambda todo_id, pinned: None,
    )
    controller = _build_started_controller(lambda: list(state), actions)
    try:
        controller._show_panel()
        controller.panel_text_field.setStringValue_("패널 테스트")
        controller.panel_time_field.setStringValue_("09:30")

        controller.onAddClicked_(None)

        assert add_calls == [("패널 테스트", "09:30")]
        assert str(controller.panel_text_field.stringValue()) == ""
        assert str(controller.panel_time_field.stringValue()) == ""
        assert str(controller.panel_error_label.stringValue()) == ""
        assert len(controller.panel_list_view.subviews()) == 1
    finally:
        controller._invalidate_all_timers()


def test_add_error_shows_inline_message_and_keeps_fields() -> None:
    def add(text: str, at: str | None) -> str | None:
        return "invalid time '25:99'"

    actions = PanelActions(
        add=add,
        set_done=lambda todo_id: None,
        delete=lambda todo_id: None,
        set_pinned=lambda todo_id, pinned: None,
    )
    controller = _build_started_controller(lambda: [], actions)
    try:
        controller._show_panel()
        controller.panel_text_field.setStringValue_("x")
        controller.panel_time_field.setStringValue_("25:99")

        controller.onAddClicked_(None)

        assert str(controller.panel_error_label.stringValue()) == "invalid time '25:99'"
        assert str(controller.panel_text_field.stringValue()) == "x"
        assert str(controller.panel_time_field.stringValue()) == "25:99"
    finally:
        controller._invalidate_all_timers()


def test_add_with_blank_text_shows_error_without_calling_the_action() -> None:
    add_calls: list[tuple[str, str | None]] = []

    actions = PanelActions(
        add=lambda text, at: add_calls.append((text, at)),
        set_done=lambda todo_id: None,
        delete=lambda todo_id: None,
        set_pinned=lambda todo_id, pinned: None,
    )
    controller = _build_started_controller(lambda: [], actions)
    try:
        controller._show_panel()
        controller.panel_text_field.setStringValue_("   ")

        controller.onAddClicked_(None)

        assert add_calls == []
        assert str(controller.panel_error_label.stringValue()) != ""
    finally:
        controller._invalidate_all_timers()


def test_builtin_row_has_three_tagged_buttons_and_pinned_marker() -> None:
    todos = [
        Todo(text="Buy milk", id=5, pinned=True),
        Todo(text="Read-only note", id=None),
    ]
    # `_build_started_controller` runs the skip/importorskip gate below, so
    # AppKit itself must not be imported until after that call returns --
    # importing it any earlier would raise ModuleNotFoundError (instead of
    # cleanly skipping) on non-macOS/no-pyobjc CI legs.
    controller = _build_started_controller(lambda: todos, _noop_actions())
    try:
        import AppKit

        controller._show_panel()  # builds the panel and refreshes the list
        rows = controller.panel_list_view.subviews()
        assert len(rows) == 2

        builtin_row_views = rows[0].subviews()
        buttons = [v for v in builtin_row_views if isinstance(v, AppKit.NSButton)]
        labels = [v for v in builtin_row_views if isinstance(v, AppKit.NSTextField)]
        assert len(buttons) == 3
        assert {b.tag() for b in buttons} == {5}
        assert "📌" in str(labels[0].stringValue())

        readonly_row_views = rows[1].subviews()
        readonly_buttons = [v for v in readonly_row_views if isinstance(v, AppKit.NSButton)]
        readonly_labels = [v for v in readonly_row_views if isinstance(v, AppKit.NSTextField)]
        assert readonly_buttons == []
        assert len(readonly_labels) == 1
        assert "Read-only note" in str(readonly_labels[0].stringValue())
    finally:
        controller._invalidate_all_timers()


def test_row_buttons_call_actions_with_the_todos_id() -> None:
    calls: list[tuple] = []

    actions = PanelActions(
        add=lambda text, at: None,
        set_done=lambda todo_id: calls.append(("done", todo_id)),
        delete=lambda todo_id: calls.append(("delete", todo_id)),
        set_pinned=lambda todo_id, pinned: calls.append(("pin", todo_id, pinned)),
    )
    todos = [Todo(text="A", id=7, pinned=False)]
    controller = _build_started_controller(lambda: todos, actions)
    try:
        controller._show_panel()  # populates _panel_todos for the pin lookup

        controller.onRowDoneClicked_(_FakeSender(7))
        controller.onRowDeleteClicked_(_FakeSender(7))
        controller.onRowPinClicked_(_FakeSender(7))

        assert calls == [("done", 7), ("delete", 7), ("pin", 7, True)]
    finally:
        controller._invalidate_all_timers()


def test_row_action_error_is_shown_and_list_still_refreshes() -> None:
    refresh_calls: list[int] = []

    def get_todos() -> list:
        refresh_calls.append(1)
        return [Todo(text="A", id=7)]

    actions = PanelActions(
        add=lambda text, at: None,
        set_done=lambda todo_id: "no such todo",
        delete=lambda todo_id: None,
        set_pinned=lambda todo_id, pinned: None,
    )
    controller = _build_started_controller(get_todos, actions)
    try:
        controller._show_panel()
        before = len(refresh_calls)
        controller.onRowDoneClicked_(_FakeSender(7))

        assert str(controller.panel_error_label.stringValue()) == "no such todo"
        assert len(refresh_calls) > before
    finally:
        controller._invalidate_all_timers()
