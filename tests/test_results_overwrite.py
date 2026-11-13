"""The results-file overwrite switch chooses a safe final path."""

from neuropilot.controller.pipeline_controller import stamped_results_filename


def test_overwrite_defaults_to_on(controller):
    assert controller.overwrite_results is True


def test_overwrite_on_uses_the_selected_path(controller, tmp_path):
    path = tmp_path / "results.csv"
    path.write_text("old")
    controller.set_results_filename(str(path))
    controller.set_overwrite_results(True)
    assert controller._results_output_path() == str(path)


def test_overwrite_off_keeps_an_existing_file(controller, tmp_path):
    path = tmp_path / "results.csv"
    path.write_text("old")
    controller.set_results_filename(str(path))
    controller.set_overwrite_results(False)
    controller.datetime_str = "20261113_120000"

    out = controller._results_output_path()
    assert out == stamped_results_filename(str(path), "20261113_120000")
    assert out != str(path)
    assert path.read_text() == "old"


def test_overwrite_off_writes_a_missing_path_directly(controller, tmp_path):
    path = tmp_path / "new.csv"
    controller.set_results_filename(str(path))
    controller.set_overwrite_results(False)
    assert controller._results_output_path() == str(path)
