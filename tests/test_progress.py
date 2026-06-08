from __future__ import annotations

from io import StringIO

from uk_address_matcher.helpers.progress import _ProgressBar


def test_progress_bar_ensure_line_break_flushes_active_render() -> None:
    stream = StringIO()
    progress = _ProgressBar(label="Stage", total=10, stream=stream)

    progress.update(5, completed_units=1)
    progress.ensure_line_break()

    assert stream.getvalue().endswith("\n")
    assert progress._rendered is False


def test_progress_bar_close_does_not_duplicate_newline_after_line_break() -> None:
    stream = StringIO()
    progress = _ProgressBar(label="Stage", total=10, stream=stream)

    progress.update(5, completed_units=1)
    progress.ensure_line_break()
    progress.close()

    assert stream.getvalue().count("\n") == 1
