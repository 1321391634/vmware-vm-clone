from __future__ import annotations

import sys
from pathlib import Path
from zipfile import ZipFile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.reports.xlsx_writer import write_xlsx  # noqa: E402


def test_xlsx_writer_creates_two_readable_worksheet_parts(tmp_path):
    target = write_xlsx(
        tmp_path / "report.xlsx",
        {
            "批次参数": [["参数", "值"], ["源虚拟机", "模板-01"]],
            "克隆结果": [["序号", "状态"], [1, "成功"]],
        },
    )

    with ZipFile(target) as package:
        names = set(package.namelist())
        assert "xl/worksheets/sheet1.xml" in names
        assert "xl/worksheets/sheet2.xml" in names
        assert "[Content_Types].xml" in names
        assert "模板-01" in package.read("xl/worksheets/sheet1.xml").decode("utf-8")

