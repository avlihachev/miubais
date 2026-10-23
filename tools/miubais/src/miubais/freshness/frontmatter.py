from datetime import date
from pathlib import Path
from typing import Literal

import frontmatter
import yaml
from pydantic import BaseModel, ConfigDict, Field, HttpUrl, ValidationError

PIN_KINDS = ("pypi", "npm", "github", "model")
SKIP_NAMES = {"index.md", "index.mdx"}


class FrontmatterError(Exception):
    pass


class Source(BaseModel):
    url: HttpUrl
    title: str
    published: date | None = None
    checked: date


class Lesson(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    path: Path
    title: str
    module: str
    order: int
    verified_on: date
    executed: Literal["local", "docker", "cloud", "none"]
    pins: dict[str, str] = Field(default_factory=dict)
    sources: list[Source] = Field(default_factory=list)
    docs_dir: Path | None = None

    @property
    def slug(self) -> str:
        if self.docs_dir is None:
            return self.path.stem
        return self.path.relative_to(self.docs_dir).with_suffix("").as_posix()


def parse_pin_key(key: str) -> tuple[str, str]:
    kind, sep, name = key.partition(":")
    if not sep or not name or kind not in PIN_KINDS:
        raise FrontmatterError(
            f"invalid pin key {key!r}: expected one of {PIN_KINDS} as <kind>:<name>"
        )
    return kind, name


def _read(path: Path) -> dict:
    try:
        return frontmatter.load(path).metadata
    except (yaml.YAMLError, OSError) as exc:
        raise FrontmatterError(f"{path}: cannot read frontmatter: {exc}") from exc


def parse_lesson(path: Path, docs_dir: Path | None = None) -> Lesson:
    meta = _read(path)
    try:
        lesson = Lesson(
            **{k: v for k, v in meta.items() if k in Lesson.model_fields},
            path=path,
            docs_dir=docs_dir,
        )
    except ValidationError as exc:
        details = "; ".join(f"{'.'.join(map(str, e['loc']))}: {e['msg']}" for e in exc.errors())
        raise FrontmatterError(f"{path}: {details}") from exc
    for key in lesson.pins:
        try:
            parse_pin_key(key)
        except FrontmatterError as exc:
            raise FrontmatterError(f"{path}: pins: {exc}") from exc
    return lesson


def load_lessons(docs_dir: Path) -> list[Lesson]:
    lessons = []
    for path in sorted(p for p in docs_dir.rglob("*") if p.suffix in (".md", ".mdx")):
        if path.name in SKIP_NAMES or _read(path).get("freshness") == "skip":
            continue
        lessons.append(parse_lesson(path, docs_dir=docs_dir))
    return lessons
