from miubais import doctor
from miubais.cli import app
from miubais.requirements import REQUIREMENTS
from typer.testing import CliRunner


class Nothing:
    def has(self, req):
        return False


def test_report_lists_tools_and_every_requirement():
    rows = doctor.report(Nothing())
    names = [name for name, _, _ in rows]
    assert names[:4] == ["python", "uv", "node", "pnpm"]
    assert names[4:] == [req for req in REQUIREMENTS if req != "node"]
    assert names.count("node") == 1
    assert all(not ok and detail == "missing" for name, ok, detail in rows[4:])


def test_missing_binary_is_reported_not_raised(monkeypatch):
    monkeypatch.setattr(doctor.shutil, "which", lambda name: None)
    rows = {name: ok for name, ok, _ in doctor.report(Nothing())}
    assert rows["uv"] is False and rows["node"] is False and rows["pnpm"] is False


def test_cli_prints_table_and_exits_zero(monkeypatch):
    monkeypatch.setattr(doctor, "SystemProbe", Nothing)
    result = CliRunner().invoke(app, ["doctor"])
    assert result.exit_code == 0
    assert "docker" in result.output and "--" in result.output
