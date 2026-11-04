from timesheet.report import hours, render


def test_hours_format() -> None:
    assert hours(0) == "0:00"
    assert hours(75) == "1:15"
    assert hours(-90) == "-1:30"


def test_render_lists_projects_and_the_week_total() -> None:
    text = render({"2026-W10": {"support": 90, "billing": 180}})
    assert text == (
        "2026-W10\n  billing         3:00\n  support         1:30\n  total           4:30\n"
    )


def test_render_filters_one_project() -> None:
    text = render({"2026-W10": {"support": 90, "billing": 180}}, project="support")
    assert text.splitlines() == ["2026-W10", "  support         1:30", "  total           1:30"]


def test_render_without_entries_prints_nothing() -> None:
    assert render({}) == ""
