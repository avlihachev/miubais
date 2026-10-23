from miubais import doctor
from miubais.cli import app
from miubais.requirements import REQUIREMENTS
from typer.testing import CliRunner


class Nothing:
    def has(self, req):
        return False


def test_report_lists_tools_and_every_requirement():
    rows = doctor.report(Nothing(), exercises=[])
    names = [name for name, _, _ in rows]
    assert names[:4] == ["python", "uv", "node", "pnpm"]
    assert names[4:] == [req for req in REQUIREMENTS if req != "node"]
    assert names.count("node") == 1
    assert all(not ok and detail.startswith("missing") for name, ok, detail in rows[4:])


def test_missing_binary_is_reported_not_raised(monkeypatch):
    monkeypatch.setattr(doctor.shutil, "which", lambda name: None)
    rows = {name: ok for name, ok, _ in doctor.report(Nothing(), exercises=[])}
    assert rows["uv"] is False and rows["node"] is False and rows["pnpm"] is False


def test_missing_requirement_names_its_users(monkeypatch, sample_ex):
    monkeypatch.setattr(doctor.shutil, "which", lambda name: None)
    rows = {name: detail for name, _, detail in doctor.report(Nothing(), exercises=[sample_ex])}
    assert rows["claude-auth"] == "missing; used by x, hint"
    assert rows["docker"] == "missing"
    assert rows["pnpm"] == "not found; used by local site"


def test_cli_prints_table_and_exits_zero(monkeypatch):
    monkeypatch.setattr(doctor, "SystemProbe", Nothing)
    result = CliRunner().invoke(app, ["doctor"])
    assert result.exit_code == 0
    assert "docker" in result.output and "--" in result.output
    assert "only skips the stages that use it" in result.output
