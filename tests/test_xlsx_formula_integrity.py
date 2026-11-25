"""Independent native-workbook regressions for the public-release audit."""

from __future__ import annotations

from pathlib import Path
import zipfile

import pytest

from autotldr.router import extract


def _workbook(tmp_path: Path, cells: dict, *, sheet: str = "Model"):
    openpyxl = pytest.importorskip("openpyxl")
    workbook = openpyxl.Workbook()
    workbook.active.title = sheet
    for address, value in cells.items():
        workbook.active[address] = value
    path = tmp_path / "model.xlsx"
    workbook.save(path)
    workbook.close()
    return path


def _edges(result):
    cells = {unit.id: unit.meta.get("cell") for unit in result.units}
    return {(cells[edge.src], cells[edge.dst]) for edge in result.relations}


def test_formula_strings_and_function_names_do_not_invent_dependencies(tmp_path):
    path = _workbook(tmp_path, {
        "A1": '="B7 and 12345"', "A2": "=LOG10(B1)",
        "B1": 1000, "B7": 77, "LOG10": 99,
    })
    result = extract(path)
    assert _edges(result) == {("Model!A2", "Model!B1")}
    by_cell = {unit.meta.get("cell"): unit for unit in result.units}
    assert by_cell["Model!A1"].meta["hardcoded"] is None
    assert by_cell["Model!A1"].meta["functions"] == []
    assert by_cell["Model!A2"].meta["functions"] == ["LOG10"]
    assert "Model!B7" not in by_cell
    assert "Model!LOG10" not in by_cell


def test_quoted_sheet_escapes_and_case_insensitive_addresses(tmp_path):
    path = _workbook(tmp_path, {
        "A1": 7, "B1": "='bob''s ! DATA'!$a$1*0.87",
    }, sheet="Bob's ! data")
    result = extract(path)
    assert _edges(result) == {("Bob's ! data!B1", "Bob's ! data!A1")}
    assert any("0.87" in gap for gap in result.gaps)


@pytest.mark.parametrize("reference", ["A1:A5", "A:A", "1:5"])
def test_formula_ranges_include_interior_populated_cells(tmp_path, reference):
    path = _workbook(tmp_path, {
        "A1": 4, "A3": 6, "A5": 8, "B6": f"=SUM({reference})",
    })
    result = extract(path)
    assert _edges(result) == {
        ("Model!B6", "Model!A1"),
        ("Model!B6", "Model!A3"),
        ("Model!B6", "Model!A5"),
    }


def test_range_interior_cycle_is_reported(tmp_path):
    path = _workbook(tmp_path, {"A1": 1, "A2": "=SUM(A1:A3)", "A3": 3})
    result = extract(path)
    assert ("Model!A2", "Model!A2") in _edges(result)
    assert any("circular reference" in gap for gap in result.gaps)


@pytest.mark.parametrize("formula", [
    "=price2026*A1", "=INDIRECT(\"A1\")", "='[outside.xlsx]Sheet'!A1",
    "=SUM(Sheet1:Sheet3!A1)", "=#REF!", "=SUM(Table1[Cost])",
])
def test_unresolved_formula_targets_are_addressed_findings(tmp_path, formula):
    path = _workbook(tmp_path, {"A1": 5, "B1": formula})
    result = extract(path)
    findings = [gap for gap in result.gaps if "unresolved formula reference" in gap]
    assert findings
    assert all(gap.origin.ref == "Model!B1" for gap in findings)
    assert all(gap.origin.source == str(path) for gap in findings)


def test_sparse_sheet_does_not_materialize_the_excel_grid(tmp_path):
    path = _workbook(tmp_path, {"A1": 9, "XFD1048576": "=A1"})
    result = extract(path)
    assert len(result.units) == 3
    assert _edges(result) == {("Model!XFD1048576", "Model!A1")}


def _replace_xml(path, member, transform):
    with zipfile.ZipFile(path) as archive:
        contents = {item.filename: archive.read(item) for item in archive.infolist()}
    contents[member] = transform(contents[member])
    with zipfile.ZipFile(path, "w") as archive:
        for name, data in contents.items():
            archive.writestr(name, data)


def test_merged_grid_expansion_is_refused_before_openpyxl(tmp_path):
    path = _workbook(tmp_path, {"A1": 1})
    _replace_xml(path, "xl/worksheets/sheet1.xml", lambda data: data.replace(
        b"</worksheet>",
        b'<mergeCells count="1"><mergeCell ref="A1:XFD1048576"/></mergeCells></worksheet>',
    ))
    with pytest.raises(ValueError, match="XLSX expanded-cell limit"):
        extract(path)


def test_xlsx_entity_declarations_are_refused_before_openpyxl(tmp_path):
    path = _workbook(tmp_path, {"A1": 1})
    _replace_xml(path, "xl/worksheets/sheet1.xml", lambda data:
        b'<!DOCTYPE worksheet [<!ENTITY value "999">]>' + data)
    with pytest.raises(ValueError, match="document types and entities"):
        extract(path)


def test_xlsx_package_size_limit_precedes_native_parser(tmp_path, monkeypatch):
    path = _workbook(tmp_path, {"A1": 1})
    from autotldr.extract import xlsx

    monkeypatch.setattr(xlsx, "_MAX_PACKAGE_BYTES", 100)
    monkeypatch.setattr(xlsx.openpyxl, "load_workbook", lambda *a, **kw: pytest.fail(
        "oversized package reached openpyxl"))
    with pytest.raises(ValueError, match="uncompressed-byte limit"):
        extract(path)


def test_thousand_small_ranges_use_the_sparse_row_index(tmp_path):
    cells = {}
    for row in range(1, 1001):
        cells.update({f"A{row}": row, f"B{row}": row, f"C{row}": f"=SUM(A{row}:B{row})"})
    result = extract(_workbook(tmp_path, cells))
    assert len(result.relations) == 2000


@pytest.mark.parametrize("formula", ["=SUM(A:A 2:2)", "=SUM(A:A INDEX(A:B,2,1))"])
def test_reference_intersection_does_not_invent_a_union_or_a_cycle(tmp_path, formula):
    result = extract(_workbook(tmp_path, {"A1": 7, "A2": 8, "B2": formula}))
    assert not result.relations
    assert any("intersection is not resolved" in gap for gap in result.gaps)
    assert not any("circular reference" in gap for gap in result.gaps)


def test_parenthesis_whitespace_is_not_an_intersection(tmp_path):
    result = extract(_workbook(tmp_path, {"A1": 7, "B1": "=(A1 )"}))
    assert _edges(result) == {("Model!B1", "Model!A1")}
    assert not any("intersection" in gap for gap in result.gaps)


def test_hyperlink_grid_expansion_is_bounded(tmp_path):
    path = _workbook(tmp_path, {"A1": 1})
    _replace_xml(path, "xl/worksheets/sheet1.xml", lambda data: data.replace(
        b"</worksheet>",
        b'<hyperlinks><hyperlink ref="A1:XFD1048576" location="Model!A1"/></hyperlinks></worksheet>',
    ))
    with pytest.raises(ValueError, match="XLSX expanded-cell limit"):
        extract(path)


@pytest.mark.parametrize("namespace", ["", ' xmlns="urn:foreign"'])
def test_native_localname_matching_cannot_bypass_expansion_limit(tmp_path, monkeypatch, namespace):
    path = _workbook(tmp_path, {"A1": 1})
    from autotldr.extract import xlsx

    monkeypatch.setattr(xlsx, "_MAX_POPULATED_CELLS", 10)
    _replace_xml(path, "xl/worksheets/sheet1.xml", lambda data: data.replace(
        b"</worksheet>",
        f'<mergeCells count="1"><mergeCell{namespace} ref="A1:D5"/></mergeCells></worksheet>'.encode(),
    ))
    with pytest.raises(ValueError, match="XLSX expanded-cell limit"):
        extract(path)


def test_renamed_xml_relationship_target_cannot_bypass_structural_limits(tmp_path):
    path = _workbook(tmp_path, {"A1": 1})
    with zipfile.ZipFile(path) as archive:
        contents = {item.filename: archive.read(item) for item in archive.infolist()}
    sheet = contents.pop("xl/worksheets/sheet1.xml")
    contents["xl/worksheets/sheet1.bin"] = sheet.replace(
        b"</worksheet>",
        b'<mergeCells count="1"><mergeCell ref="A1:XFD1048576"/></mergeCells></worksheet>',
    )
    for name in ("xl/_rels/workbook.xml.rels", "[Content_Types].xml"):
        contents[name] = contents[name].replace(b"sheet1.xml", b"sheet1.bin")
    with zipfile.ZipFile(path, "w") as archive:
        for name, data in contents.items():
            archive.writestr(name, data)
    with pytest.raises(ValueError, match="XLSX expanded-cell limit"):
        extract(path)
