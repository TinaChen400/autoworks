from __future__ import annotations

import math
import random
import string
import time
from dataclasses import dataclass
from typing import Any

from . import mouse_keyboard


@dataclass(frozen=True)
class HumanSimulatorConfig:
    humanize_mouse: bool = True
    humanize_typing: bool = True
    deterministic: bool = True
    seed: int = 1337
    min_mouse_steps: int = 8
    max_mouse_steps: int = 18
    mouse_step_delay_ms: int = 4
    typing_min_delay_ms: int = 15
    typing_max_delay_ms: int = 55
    typo_rate: float = 0.0
    typo_alphabet: str = string.ascii_lowercase
    scroll_wheel_delta: int = 120


class HumanSimulator:
    def __init__(
        self,
        mouse_api: Any = mouse_keyboard,
        config: HumanSimulatorConfig | None = None,
    ) -> None:
        self.mouse_api = mouse_api
        self.config = config or HumanSimulatorConfig()
        self._rng = random.Random(self.config.seed if self.config.deterministic else None)

    def click_screen_point(self, x: int, y: int, pause_ms: int = 120) -> dict[str, int]:
        x = int(x)
        y = int(y)
        if not self.config.humanize_mouse or not self._has_motion_api():
            return self.mouse_api.click_screen_point(x, y, pause_ms=pause_ms)
        self._move_humanized(x, y)
        if pause_ms > 0:
            time.sleep(pause_ms / 1000.0)
        actual_position = self.mouse_api.get_cursor_position()
        if actual_position != {"x": x, "y": y}:
            raise mouse_keyboard.MouseKeyboardError(
                "Cursor landed at "
                f"({actual_position['x']}, {actual_position['y']}) instead of ({x}, {y})."
            )
        self.mouse_api.left_click()
        return actual_position

    def type_text(self, text: str) -> None:
        if not hasattr(self.mouse_api, "_send_unicode_char") and self.config.typo_rate <= 0:
            self.mouse_api.type_text(str(text))
            return
        for char in str(text):
            if self._should_typo(char):
                typo = self._typo_char(char)
                self._send_char(typo)
                self._typing_pause()
                self._backspace()
                self._typing_pause()
            self._send_char(char)
            self._typing_pause()

    def drag_screen_points(
        self,
        start_point: dict[str, int],
        end_point: dict[str, int],
        pause_ms: int = 120,
    ) -> dict[str, dict[str, int]]:
        start = self._point(start_point)
        end = self._point(end_point)
        if not self.config.humanize_mouse or not self._has_drag_api():
            if hasattr(self.mouse_api, "drag_screen_points"):
                return self.mouse_api.drag_screen_points(start, end, pause_ms=pause_ms)
            self.mouse_api.click_screen_point(start["x"], start["y"], pause_ms=pause_ms)
            self.mouse_api.click_screen_point(end["x"], end["y"], pause_ms=pause_ms)
            return {"start_position": start, "end_position": end}

        self._move_humanized(start["x"], start["y"])
        if pause_ms > 0:
            time.sleep(pause_ms / 1000.0)
        self.mouse_api.mouse_down()
        self._move_humanized(end["x"], end["y"])
        self.mouse_api.mouse_up()
        return {"start_position": start, "end_position": self.mouse_api.get_cursor_position()}

    def scroll(self, amount: int, x: int | None = None, y: int | None = None) -> dict[str, int]:
        if x is not None and y is not None:
            self._move_or_clickless(int(x), int(y))
        delta = int(amount) * int(self.config.scroll_wheel_delta)
        if hasattr(self.mouse_api, "scroll_wheel"):
            self.mouse_api.scroll_wheel(delta)
        elif hasattr(self.mouse_api, "scroll"):
            try:
                self.mouse_api.scroll(amount, x, y)
            except TypeError:
                self.mouse_api.scroll(amount)
        else:
            raise mouse_keyboard.MouseKeyboardError("Mouse API does not support scrolling.")
        if hasattr(self.mouse_api, "get_cursor_position"):
            return self.mouse_api.get_cursor_position()
        return {}

    def _has_motion_api(self) -> bool:
        names = ("get_cursor_position", "move_to", "left_click")
        return all(hasattr(self.mouse_api, name) for name in names)

    def _has_drag_api(self) -> bool:
        names = ("get_cursor_position", "move_to", "mouse_down", "mouse_up")
        return all(hasattr(self.mouse_api, name) for name in names)

    def _move_or_clickless(self, x: int, y: int) -> None:
        if self._has_motion_api():
            self._move_humanized(x, y)
        elif hasattr(self.mouse_api, "move_to"):
            self.mouse_api.move_to(x, y)

    def _move_humanized(self, x: int, y: int) -> None:
        start = self.mouse_api.get_cursor_position()
        sx = int(start["x"])
        sy = int(start["y"])
        distance = math.hypot(x - sx, y - sy)
        steps = self._steps_for_distance(distance)
        c1, c2 = self._control_points(sx, sy, x, y, distance)
        for index in range(1, steps + 1):
            t = index / steps
            px, py = self._bezier((sx, sy), c1, c2, (x, y), t)
            self.mouse_api.move_to(int(round(px)), int(round(py)))
            delay = self.config.mouse_step_delay_ms
            if delay > 0:
                time.sleep(delay / 1000.0)

    def _steps_for_distance(self, distance: float) -> int:
        base = max(
            self.config.min_mouse_steps,
            min(self.config.max_mouse_steps, int(distance / 35) + 1),
        )
        if self.config.deterministic:
            return base
        return self._rng.randint(max(2, base - 2), max(2, base + 2))

    def _control_points(
        self,
        sx: int,
        sy: int,
        ex: int,
        ey: int,
        distance: float,
    ) -> tuple[tuple[float, float], tuple[float, float]]:
        dx = ex - sx
        dy = ey - sy
        normal = (-dy, dx)
        length = math.hypot(*normal) or 1.0
        bend = min(max(distance * 0.18, 12.0), 80.0)
        if not self.config.deterministic:
            bend *= self._rng.uniform(0.6, 1.4)
            if self._rng.random() < 0.5:
                bend *= -1
        nx = normal[0] / length * bend
        ny = normal[1] / length * bend
        return (
            (sx + dx * 0.33 + nx, sy + dy * 0.33 + ny),
            (sx + dx * 0.66 - nx, sy + dy * 0.66 - ny),
        )

    @staticmethod
    def _bezier(
        p0: tuple[float, float],
        p1: tuple[float, float],
        p2: tuple[float, float],
        p3: tuple[float, float],
        t: float,
    ) -> tuple[float, float]:
        inv = 1.0 - t
        x = (
            inv**3 * p0[0]
            + 3 * inv**2 * t * p1[0]
            + 3 * inv * t**2 * p2[0]
            + t**3 * p3[0]
        )
        y = (
            inv**3 * p0[1]
            + 3 * inv**2 * t * p1[1]
            + 3 * inv * t**2 * p2[1]
            + t**3 * p3[1]
        )
        return x, y

    def _should_typo(self, char: str) -> bool:
        return (
            self.config.humanize_typing
            and self.config.typo_rate > 0
            and char.isprintable()
            and not char.isspace()
            and self._rng.random() < self.config.typo_rate
        )

    def _typo_char(self, char: str) -> str:
        alphabet = self.config.typo_alphabet or string.ascii_lowercase
        if char.isupper():
            alphabet = alphabet.upper()
        return self._rng.choice(alphabet)

    def _send_char(self, char: str) -> None:
        if hasattr(self.mouse_api, "_send_unicode_char"):
            self.mouse_api._send_unicode_char(char)
        else:
            self.mouse_api.type_text(char)

    def _backspace(self) -> None:
        if hasattr(self.mouse_api, "press_backspace"):
            self.mouse_api.press_backspace()
        elif hasattr(self.mouse_api, "type_text"):
            self.mouse_api.type_text("\b")
        else:
            raise mouse_keyboard.MouseKeyboardError("Mouse API does not support backspace.")

    def _typing_pause(self) -> None:
        if not self.config.humanize_typing:
            return
        low = max(0, self.config.typing_min_delay_ms)
        high = max(low, self.config.typing_max_delay_ms)
        delay = low if self.config.deterministic else self._rng.randint(low, high)
        if delay > 0:
            time.sleep(delay / 1000.0)

    @staticmethod
    def _point(point: dict[str, int]) -> dict[str, int]:
        return {"x": int(round(float(point["x"]))), "y": int(round(float(point["y"])))}
