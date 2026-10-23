from miubais.exercises import list_exercises
from miubais.paths import course_dir, site_docs_dir


def test_every_stage_lesson_is_a_lesson_of_its_module():
    for ex in list_exercises(course_dir()):
        for stage in ex.stages:
            assert stage.lesson, (ex.id, stage.id)
            assert stage.lesson.startswith(f"{ex.module}/"), (ex.id, stage.id, stage.lesson)
            found = [site_docs_dir() / f"{stage.lesson}{suffix}" for suffix in (".md", ".mdx")]
            assert any(p.is_file() for p in found), (ex.id, stage.id, stage.lesson)
