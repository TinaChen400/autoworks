from __future__ import annotations

from modules.action_executor.human_simulator import HumanSimulator, HumanSimulatorConfig


class MotionMouse:
    def __init__(self) -> None:
        self.position = {"x": 0, "y": 0}
        self.moves: list[tuple[int, int]] = []
        self.clicks = 0
        self.downs = 0
        self.ups = 0
        self.chars: list[str] = []
        self.backspaces = 0
        self.scrolls: list[int] = []

    def get_cursor_position(self) -> dict[str, int]:
        return dict(self.position)

    def move_to(self, x: int, y: int) -> None:
        self.position = {"x": x, "y": y}
        self.moves.append((x, y))

    def left_click(self) -> None:
        self.clicks += 1

    def mouse_down(self) -> None:
        self.downs += 1

    def mouse_up(self) -> None:
        self.ups += 1

    def _send_unicode_char(self, char: str) -> None:
        self.chars.append(char)

    def press_backspace(self) -> None:
        self.backspaces += 1

    def scroll_wheel(self, delta: int) -> None:
        self.scrolls.append(delta)


def _config(**overrides) -> HumanSimulatorConfig:
    return HumanSimulatorConfig(
        mouse_step_delay_ms=0,
        typing_min_delay_ms=0,
        typing_max_delay_ms=0,
        **overrides,
    )


def test_click_uses_bezier_motion_before_click() -> None:
    mouse = MotionMouse()
    simulator = HumanSimulator(mouse, _config())

    position = simulator.click_screen_point(120, 80, pause_ms=0)

    assert position == {"x": 120, "y": 80}
    assert mouse.clicks == 1
    assert len(mouse.moves) >= 8
    assert mouse.moves[-1] == (120, 80)
    assert len(set(mouse.moves)) > 2


def test_drag_uses_mouse_down_humanized_motion_mouse_up() -> None:
    mouse = MotionMouse()
    simulator = HumanSimulator(mouse, _config())

    result = simulator.drag_screen_points({"x": 10, "y": 20}, {"x": 90, "y": 70}, pause_ms=0)

    assert mouse.downs == 1
    assert mouse.ups == 1
    assert result["start_position"] == {"x": 10, "y": 20}
    assert result["end_position"] == {"x": 90, "y": 70}
    assert mouse.moves[-1] == (90, 70)


def test_type_text_can_insert_typo_and_backspace_deterministically() -> None:
    mouse = MotionMouse()
    simulator = HumanSimulator(mouse, _config(typo_rate=1.0, typo_alphabet="z"))

    simulator.type_text("ab")

    assert mouse.chars == ["z", "a", "z", "b"]
    assert mouse.backspaces == 2


def test_scroll_moves_to_point_and_sends_wheel_delta() -> None:
    mouse = MotionMouse()
    simulator = HumanSimulator(mouse, _config())

    simulator.scroll(-3, 20, 30)

    assert mouse.moves[-1] == (20, 30)
    assert mouse.scrolls == [-360]
