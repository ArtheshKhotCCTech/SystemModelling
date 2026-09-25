# Purpose: pins the plots (FR-08 req 5) — one PNG per compared signal group (continuous signals
# by unit, Boolean signals, one state trace per machine), the reference overlaid where one was
# compared, the variable map's outputs when there is no reference, and NOT RUN with a reason when
# verification.json or the simulation result is missing (R-REP-3).
import shutil

import pytest

from specalive.report import artefacts, plots
from tests._report_support import build_run

PNG = b"\x89PNG\r\n\x1a\n"


@pytest.fixture(scope="module")
def verified_run(tmp_path_factory):
    mp = pytest.MonkeyPatch()
    try:
        yield build_run(tmp_path_factory.mktemp("plots") / "run", mp)
    finally:
        mp.undo()


def _copy(run, tmp_path):
    target = tmp_path / "run"
    shutil.copytree(run, target)
    return target


def test_one_figure_per_signal_group_with_the_reference_overlaid(verified_run, tmp_path):
    result = plots.write_plots(artefacts.load_run(verified_run), tmp_path / "plots")
    assert result.status == "ok", result.reason
    files = {f.file: f for f in result.figures}
    assert set(files) == {"continuous_m.png", "boolean.png", "state_plc_101_sequence.png"}
    for name, figure in files.items():
        assert (tmp_path / "plots" / name).read_bytes().startswith(PNG)
        assert figure.reference
    assert files["continuous_m.png"].signals == ["tank1_level_m"]
    assert files["state_plc_101_sequence.png"].signals == ["controller_state"]
    assert files["continuous_m.png"].y_label.endswith("[m]")
    assert files["boolean.png"].signals == ["valve1_open"]


def test_without_a_reference_the_mapped_outputs_are_plotted(tmp_path, monkeypatch):
    run = build_run(tmp_path / "run", monkeypatch, reference=False)
    result = plots.write_plots(artefacts.load_run(run), tmp_path / "plots")
    assert result.status == "ok", result.reason
    files = {f.file: f for f in result.figures}
    assert "state_plc_101_sequence.png" in files
    assert not any(f.reference for f in result.figures)
    assert "continuous_m.png" in files and "tk_101_level_out" in files["continuous_m.png"].signals


def test_without_verification_plots_are_not_run(verified_run, tmp_path):
    run = _copy(verified_run, tmp_path)
    (run / "verification.json").unlink()
    result = plots.write_plots(artefacts.load_run(run), tmp_path / "plots")
    assert result.status == artefacts.NOT_RUN and "verification.json" in result.reason
    assert result.figures == []


def test_without_a_simulation_result_plots_are_not_run(verified_run, tmp_path):
    run = _copy(verified_run, tmp_path)
    (run / "sim" / "result.csv").unlink()
    result = plots.write_plots(artefacts.load_run(run), tmp_path / "plots")
    assert result.status == artefacts.NOT_RUN and "result.csv" in result.reason


def test_plots_are_reproducible(verified_run, tmp_path):
    plots.write_plots(artefacts.load_run(verified_run), tmp_path / "a")
    plots.write_plots(artefacts.load_run(verified_run), tmp_path / "b")
    for f in (tmp_path / "a").iterdir():
        assert f.read_bytes() == (tmp_path / "b" / f.name).read_bytes()
