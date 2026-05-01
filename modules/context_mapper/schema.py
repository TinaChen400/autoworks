from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True)
class AnchorFrame:
    x: int
    y: int
    width: int
    height: int

    def validate(self) -> None:
        if self.width <= 0 or self.height <= 0:
            raise ValueError("anchor_frame width and height must be positive")


@dataclass(frozen=True)
class ImageSize:
    width: int
    height: int

    def validate(self) -> None:
        if self.width <= 0 or self.height <= 0:
            raise ValueError("image_size width and height must be positive")


@dataclass(frozen=True)
class CoordinatePoint:
    x: float
    y: float


@dataclass(frozen=True)
class BoundingBox:
    x: float
    y: float
    width: float
    height: float

    def validate_positive(self, name: str = "bounding_box") -> None:
        if self.width <= 0 or self.height <= 0:
            raise ValueError(f"{name} width and height must be positive")


@dataclass(frozen=True)
class QuestionStem:
    text: str
    bbox: BoundingBox | None = None


@dataclass(frozen=True)
class InstructionBlock:
    text: str
    bbox: BoundingBox | None = None


@dataclass(frozen=True)
class AnswerOption:
    label: str
    text: str
    bbox: BoundingBox | None = None


@dataclass(frozen=True)
class InputField:
    field_id: str
    field_type: str
    label: str = ""
    bbox: BoundingBox | None = None


@dataclass(frozen=True)
class MediaContent:
    media_id: str
    media_type: str
    description: str = ""
    bbox: BoundingBox | None = None


@dataclass(frozen=True)
class NavigationButton:
    label: str
    action: str
    bbox: BoundingBox | None = None


@dataclass(frozen=True)
class ParsedQuestion:
    question_id: str
    question_type: str
    stem: QuestionStem | None = None
    instructions: list[InstructionBlock] = field(default_factory=list)
    answer_options: list[AnswerOption] = field(default_factory=list)
    input_fields: list[InputField] = field(default_factory=list)
    media: list[MediaContent] = field(default_factory=list)


@dataclass(frozen=True)
class ParsedPage:
    questions: list[ParsedQuestion] = field(default_factory=list)
    navigation_buttons: list[NavigationButton] = field(default_factory=list)


@dataclass(frozen=True)
class TaskContext:
    task_id: str
    task_type: str
    task_family: str
    inherits: list[str]
    supported_question_types: list[str]
    effective_context: dict[str, Any]


@dataclass(frozen=True)
class RuntimeContext:
    task_id: str
    task_type: str
    screenshot_path: str
    anchor_frame: AnchorFrame
    image_size: ImageSize
    raw_screenshot: BoundingBox
    content_region: BoundingBox
    ignore_regions: list[BoundingBox]
    model_input_region: BoundingBox
    effective_task_context: dict[str, Any]
    vision_prompt: str
    answer_prompt: str
    coordinate_policy: dict[str, Any]
    supported_question_types: list[str]
    created_at: str

    def to_json_dict(self) -> dict[str, Any]:
        data = asdict(self)
        return data
