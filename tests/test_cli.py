from typer.testing import CliRunner

from csanalysis.cli import app

runner = CliRunner()


def test_synth_then_info(tmp_path):
    out = runner.invoke(app, ["synth", "-d", str(tmp_path), "-n", "3"])
    assert out.exit_code == 0, out.output
    out = runner.invoke(app, ["info", "-d", str(tmp_path)])
    assert out.exit_code == 0, out.output
    assert "de_synth_alpha" in out.output


def test_parse_with_empty_catalog(tmp_path):
    out = runner.invoke(app, ["parse", "-d", str(tmp_path)])
    assert out.exit_code == 0 and "nothing to parse" in out.output


def test_parse_records_failures(tmp_path):
    demo = tmp_path / "corrupt.dem"
    demo.write_bytes(b"PBDEMS2\0garbage")
    assert runner.invoke(app, ["ingest", str(demo), "-d", str(tmp_path / "data")]).exit_code == 0
    out = runner.invoke(app, ["parse", "-d", str(tmp_path / "data"), "-j", "1"])
    assert out.exit_code == 1
    out = runner.invoke(app, ["info", "-d", str(tmp_path / "data")])
    assert "failed=1" in out.output
