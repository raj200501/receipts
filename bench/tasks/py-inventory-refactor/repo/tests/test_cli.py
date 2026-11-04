import json
import shutil
from pathlib import Path

import pytest
from stockroom.cli import main

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def data(tmp_path: Path) -> tuple[str, str]:
    catalog = shutil.copy(ROOT / "data" / "catalog.json", tmp_path / "catalog.json")
    stock = shutil.copy(ROOT / "data" / "stock.json", tmp_path / "stock.json")
    return str(catalog), str(stock)


def run(order: str, data: tuple[str, str], *extra: str) -> int:
    return main(
        [
            "process",
            order,
            "--catalog",
            data[0],
            "--stock",
            data[1],
            "--today",
            "2026-10-14",
            *extra,
        ]
    )


def test_process_prints_the_receipt(
    data: tuple[str, str], capsys: pytest.CaptureFixture[str]
) -> None:
    assert run(str(ROOT / "examples" / "order-1001.json"), data) == 0
    out = capsys.readouterr().out
    assert out.startswith("Order SO-1001 for C-204 (DE)\n")
    assert "discount (volume)" in out
    assert "\ntotal" in out


def test_commit_writes_the_stock_back(data: tuple[str, str]) -> None:
    assert run(str(ROOT / "examples" / "order-1002.json"), data, "--commit") == 0
    saved = json.loads(Path(data[1]).read_text(encoding="utf-8"))
    assert saved["LMP-3"] == 7
    assert saved["SPR-5"] == 0


def test_without_commit_the_stock_file_is_unchanged(data: tuple[str, str]) -> None:
    before = Path(data[1]).read_text(encoding="utf-8")
    assert run(str(ROOT / "examples" / "order-1002.json"), data) == 0
    assert Path(data[1]).read_text(encoding="utf-8") == before


def test_a_rejected_order_exits_with_status_1(
    tmp_path: Path, data: tuple[str, str], capsys: pytest.CaptureFixture[str]
) -> None:
    path = tmp_path / "bad.json"
    path.write_text(json.dumps({"id": "SO-9", "customer": "C-1", "lines": []}), encoding="utf-8")
    assert run(str(path), data) == 1
    err = capsys.readouterr().err
    assert "stockroom: SO-9: bad customer id 'C-1'" in err
    assert "stockroom: SO-9: order has no lines" in err


def test_a_missing_order_file_exits_with_status_2(
    tmp_path: Path, data: tuple[str, str], capsys: pytest.CaptureFixture[str]
) -> None:
    assert run(str(tmp_path / "none.json"), data) == 2
    assert "cannot read" in capsys.readouterr().err


def test_a_bad_date_exits_with_status_2(data: tuple[str, str]) -> None:
    order = str(ROOT / "examples" / "order-1002.json")
    assert (
        main(["process", order, "--catalog", data[0], "--stock", data[1], "--today", "soon"]) == 2
    )
