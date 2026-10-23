import asyncio
import json
from collections.abc import Callable, Iterator
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from miubais.exercises import Exercise, list_exercises
from miubais.grader import Runner, StageResult, run_exercise
from miubais.model import ModelClient, default_client
from miubais.paths import repo_root
from miubais.progress import load_progress
from miubais.requirements import Probe
from miubais.tutor.hint import HintError, build_context, generate_hint

SITE_ORIGIN = "http://localhost:4321"


class CheckRequest(BaseModel):
    stage: str | None = None


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps({'event': event, **data})}\n\n"


def _stage_event(result: StageResult) -> str:
    return _sse(
        "stage",
        {
            "stage": result.stage.id,
            "title": result.stage.title,
            "status": result.status,
            "missing": list(result.missing),
            "reason": result.reason,
        },
    )


def create_app(
    *,
    course_dir: Path,
    home: Path,
    workspace: Path,
    client_factory: Callable[[], ModelClient] = default_client,
    runner: Runner | None = None,
    probe: Probe | None = None,
    freshness_path: Path | None = None,
) -> FastAPI:
    app = FastAPI(title="miubais")
    app.add_middleware(CORSMiddleware, allow_origins=[SITE_ORIGIN], allow_methods=["*"])
    freshness_file = freshness_path or repo_root() / "freshness" / "latest.json"

    def started_exercise(exercise_id: str) -> Exercise:
        ex = next((e for e in list_exercises(course_dir) if e.id == exercise_id), None)
        if ex is None:
            raise HTTPException(404, f"unknown exercise: {exercise_id}")
        if not (workspace / ex.id).exists():
            raise HTTPException(409, f"run `uv run miubais start {ex.id}` first")
        return ex

    @app.get("/progress")
    def progress() -> dict:
        return load_progress(home).model_dump(mode="json")

    @app.get("/exercises")
    def exercises() -> list[dict]:
        return [
            {
                "id": ex.id,
                "module": ex.module,
                "title": ex.title,
                "started": (workspace / ex.id).exists(),
                "stages": [
                    {
                        "id": s.id,
                        "title": s.title,
                        "live": s.live,
                        "requires": list(s.requires),
                    }
                    for s in ex.stages
                ],
            }
            for ex in list_exercises(course_dir)
        ]

    @app.post("/check/{exercise_id}")
    def check(exercise_id: str, payload: CheckRequest | None = None):
        body = payload or CheckRequest()
        ex = started_exercise(exercise_id)
        if body.stage is not None and body.stage not in {s.id for s in ex.stages}:
            raise HTTPException(404, f"unknown stage: {body.stage}")

        def events() -> Iterator[str]:
            try:
                result = run_exercise(
                    ex,
                    workspace / ex.id,
                    only=body.stage,
                    probe=probe,
                    runner=runner,
                    home=home,
                )
            except Exception as err:  # noqa: BLE001
                yield _sse("error", {"message": str(err)})
                return
            for stage_result in result.results:
                yield _stage_event(stage_result)
            failure = result.first_failure
            yield _sse(
                "done",
                {
                    "passed": result.passed_stages,
                    "failed": failure.stage.id if failure else None,
                },
            )

        return StreamingResponse(events(), media_type="text/event-stream")

    @app.post("/hint/{exercise_id}")
    async def hint(exercise_id: str) -> dict:
        ex = started_exercise(exercise_id)
        try:
            ctx = await asyncio.to_thread(build_context, ex, workspace / ex.id, home)
        except HintError as err:
            raise HTTPException(422, str(err)) from err
        result = await generate_hint(ctx, client_factory())
        return {
            "text": result.text,
            "source": result.source,
            "leaks_rejected": result.leaks_rejected,
        }

    @app.get("/freshness")
    def freshness() -> dict:
        if not freshness_file.is_file():
            return {}
        return json.loads(freshness_file.read_text())

    return app
