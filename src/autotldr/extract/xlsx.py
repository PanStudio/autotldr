"""Spreadsheets, read as a formula dependency graph.

A spreadsheet's meaning is not its values. It is what depends on what. Which
cells are free inputs, which are derived, what the derivation is, and where
somebody typed a number directly into a formula instead of referencing an
assumption. Routing an XLSX through a markdown converter throws all of that away
and leaves a grid of numbers, which is why the router never does.

Nothing in this module calls a model.
"""

from __future__ import annotations

import re
from collections import defaultdict
from pathlib import Path

import openpyxl
from openpyxl.formula.tokenizer import Tokenizer, TokenizerError
from openpyxl.utils import get_column_letter, range_boundaries

from ..unit import Extraction, Modality, Origin, Relation, RelationKind, Role, Unit

# A complete A1 operand after the native tokenizer separates formula syntax.
_REF = re.compile(r"\$?[A-Z]{1,3}\$?[1-9]\d{0,6}", re.IGNORECASE)

# Literals that carry no analytical weight and would only add noise.
_BENIGN_LITERALS = frozenset({"0", "1", "2", "-1", "100", "0.0", "1.0"})
_MAX_PACKAGE_MEMBERS = 10_000
_MAX_MEMBER_BYTES = 64 * 1024 * 1024
_MAX_PACKAGE_BYTES = 256 * 1024 * 1024
_MAX_POPULATED_CELLS = 250_000
_MAX_DEPENDENCIES = 250_000
_MAX_RANGE_VISITS = 2_000_000


def extract(path: Path) -> Extraction:
    source = str(path)
    result = Extraction(source=source, kind="xlsx")

    _validate_package(path)
    formulas = openpyxl.load_workbook(
        path, data_only=False, read_only=False, keep_links=False,
    )
    try:
        values = openpyxl.load_workbook(
            path, data_only=True, read_only=False, keep_links=False,
        )
    except Exception:  # pragma: no cover - some writers omit the value cache
        values = None

    try:
        _extract_workbook(result, formulas, values, source)
    finally:
        formulas.close()
        if values is not None:
            values.close()

    return result


def _validate_package(path: Path) -> None:
    """Bound ZIP expansion and XML work before openpyxl allocates its graph."""

    import zipfile
    from pathlib import PurePosixPath
    from xml.etree.ElementTree import XMLParser

    class Limits:
        def __init__(self):
            self.depth = 0
            self.elements = 0
            self.cells = 0
            self.expanded_cells = 0

        def start(self, tag, attributes):
            self.depth += 1
            self.elements += 1
            # Native OOXML descriptors sometimes match children by local name.
            # An alternate namespace must not bypass their allocation limits.
            local_name = tag.rsplit("}", 1)[-1]
            if local_name == "c":
                self.cells += 1
            if self.depth > 128 or self.elements > 2_000_000:
                raise ValueError("XLSX XML structural limit exceeded")
            if self.cells + self.expanded_cells > _MAX_POPULATED_CELLS:
                raise ValueError("XLSX populated-cell limit exceeded")
            if local_name in {"mergeCell", "hyperlink"}:
                left, top, right, bottom = range_boundaries(attributes.get("ref", ""))
                if None in (left, top, right, bottom) or not (
                    1 <= left <= right <= 16_384 and 1 <= top <= bottom <= 1_048_576
                ):
                    raise ValueError("XLSX expanded-cell range must be bounded")
                self.expanded_cells += (right - left + 1) * (bottom - top + 1)
                if self.cells + self.expanded_cells > _MAX_POPULATED_CELLS:
                    raise ValueError("XLSX expanded-cell limit exceeded")

        def end(self, tag):
            self.depth -= 1

        def data(self, text):
            pass

        def doctype(self, name, pubid, system):
            raise ValueError("XLSX XML document types and entities are not supported")

        def close(self):
            return None

    limits = Limits()
    with zipfile.ZipFile(path) as package:
        members = package.infolist()
        if len(members) > _MAX_PACKAGE_MEMBERS:
            raise ValueError("XLSX package member limit exceeded")
        names: set[str] = set()
        total = 0
        for member in members:
            name = member.filename
            if (
                name in names or "\\" in name or name.startswith("/")
                or ".." in PurePosixPath(name).parts or member.flag_bits & 1
            ):
                raise ValueError("XLSX package has duplicate, unsafe, or encrypted members")
            names.add(name)
            total += member.file_size
            if member.file_size > _MAX_MEMBER_BYTES or total > _MAX_PACKAGE_BYTES:
                raise ValueError("XLSX package uncompressed-byte limit exceeded")
            if member.file_size > 65_536 and member.file_size > 200 * max(member.compress_size, 1):
                raise ValueError("XLSX package compression-ratio limit exceeded")
        for member in members:
            with package.open(member) as stream:
                # Relationships can point to XML parts with arbitrary suffixes.
                # Identify XML bytes as well as conventional package filenames.
                # Skip leading XML whitespace when sniffing an unnamed part;
                # the native parser still receives the original, exact bytes.
                head = stream.read(65_536)
                while head and not head.strip(b" \t\r\n"):
                    head = stream.read(65_536)
                prefix = head.lstrip(b" \t\r\n\x00")
                if not member.filename.casefold().endswith((".xml", ".rels")) and not prefix.startswith(
                    (b"<", b"\xef\xbb\xbf", b"\xff\xfe", b"\xfe\xff"),
                ):
                    continue
                parser = XMLParser(target=limits)
                parser.feed(head)
                consumed = len(head)
                while block := stream.read(65_536):
                    consumed += len(block)
                    if consumed > _MAX_MEMBER_BYTES:
                        raise ValueError("XLSX XML member-byte limit exceeded")
                    parser.feed(block)
                parser.close()


def _extract_workbook(result: Extraction, wb, values_wb, source: str) -> None:
    unit_by_cell: dict[str, Unit] = {}
    deps: dict[str, set[str]] = {}
    referenced: set[str] = set()
    formula_cells: dict[str, str] = {}
    labels: dict[str, str] = {}
    grids: dict[str, dict[str, object]] = {}

    # Pass 1: read every cell, record formulas and their dependencies.
    for ws in wb.worksheets:
        grid, texts = _read_sheet(ws)
        grids[ws.title] = grid
        result.units.append(_sheet_unit(source, ws, grid))

        for addr, raw in grid.items():
            if isinstance(raw, str) and raw.startswith("="):
                key = f"{ws.title}!{addr}"
                formula_cells[key] = raw

        labels.update(_infer_labels(ws.title, grid, texts))

    # Resolve against the complete sparse workbook, including later sheets.
    references = _ReferenceIndex(grids)
    dependency_count = 0
    for key, formula in formula_cells.items():
        sheet, _addr = key.rsplit("!", 1)
        unresolved: list[str] = []
        targets = _dependencies(
            formula, sheet, references=references, unresolved=unresolved,
        )
        deps[key] = targets
        referenced |= targets
        dependency_count += len(targets)
        if dependency_count > _MAX_DEPENDENCIES:
            raise ValueError("XLSX formula-dependency limit exceeded")
        for reference in sorted(set(unresolved)):
            result.add_gap(
                f"{key} contains an unresolved formula reference: {reference}", ref=key,
            )

    # Pass 2: emit a unit per formula cell, and per constant that a formula uses.
    for key, formula in formula_cells.items():
        sheet, addr = key.rsplit("!", 1)
        value = _cached_value(values_wb, sheet, addr)
        label = labels.get(key, "")
        literals = _suspect_literals(formula)

        unit = Unit(
            source=source,
            modality=Modality.RECORD,
            content=_describe(label, addr, formula, value),
            origin=Origin(source, key),
            # A formula's derivation is explicit in metadata and relations;
            # RESULT did not survive the Stage 2 role-recoverability gate.
            role=Role.UNKNOWN,
            structure=(sheet,),
            salience=0.75 if key not in referenced else 0.6,
            meta={
                "cell": key,
                "formula": formula,
                "derived": True,
                "value": value,
                "label": label or None,
                "functions": sorted({
                    token.value[:-1].upper() for token in _formula_tokens(formula)
                    if token.type == "FUNC" and token.subtype == "OPEN"
                }),
                "hardcoded": literals or None,
                "terminal": key not in referenced,
            },
        )
        result.units.append(unit)
        unit_by_cell[key] = unit

        if literals:
            result.add_gap(
                f"{key} hardcodes {', '.join(literals)} inside its formula "
                f"instead of referencing a named input",
                ref=key,
            )

    for key in sorted(referenced - set(formula_cells)):
        sheet, addr = key.rsplit("!", 1)
        value = _cached_value(values_wb, sheet, addr)
        if value is None:
            continue
        label = labels.get(key, "")
        unit = Unit(
            source=source,
            modality=Modality.RECORD,
            content=_describe(label, addr, None, value),
            origin=Origin(source, key),
            role=Role.ASSUMPTION,
            structure=(sheet,),
            salience=0.85,
            meta={
                "cell": key,
                "value": value,
                "label": label or None,
                "input": True,
                "documented": bool(label),
            },
        )
        result.units.append(unit)
        unit_by_cell[key] = unit

    # Pass 3: turn the dependency map into relations.
    for key, targets in deps.items():
        src_unit = unit_by_cell.get(key)
        if src_unit is None:
            continue
        for target in sorted(targets):
            if dst_unit := unit_by_cell.get(target):
                result.relations.append(
                    Relation(
                        src=src_unit.id,
                        dst=dst_unit.id,
                        kind=RelationKind.DERIVES_FROM,
                        evidence=f"{key} formula references {target}",
                    )
                )

    _report_findings(result, deps, referenced, formula_cells, labels, unit_by_cell)

    result.meta.update(
        {
            "sheets": [ws.title for ws in wb.worksheets],
            "formula_cells": len(formula_cells),
            "input_cells": sum(1 for u in result.units if u.meta.get("input")),
        }
    )


# --------------------------------------------------------------------------- #
# Sheet reading
# --------------------------------------------------------------------------- #


def _read_sheet(ws) -> tuple[dict[str, object], dict[str, str]]:
    """Return every non-empty cell, plus the subset holding text."""
    grid: dict[str, object] = {}
    texts: dict[str, str] = {}
    # openpyxl's public rectangular iterator materializes every empty cell
    # between A1 and the last address. A sparse worksheet can span billions of
    # coordinates. Its native sparse cell map preserves actual cells only.
    for _position, cell in sorted(ws._cells.items()):
        if cell.value is None:
            continue
        addr = f"{get_column_letter(cell.column)}{cell.row}"
        grid[addr] = cell.value
        if isinstance(cell.value, str) and not cell.value.startswith("="):
            texts[addr] = cell.value.strip()
    return grid, texts


def _sheet_unit(source: str, ws, grid: dict[str, object]) -> Unit:
    formulas = sum(1 for v in grid.values() if isinstance(v, str) and v.startswith("="))
    summary = (
        f"Sheet {ws.title!r}: {ws.max_row} rows x {ws.max_column} columns, "
        f"{len(grid)} populated cells, {formulas} formulas."
    )
    return Unit(
        source=source,
        modality=Modality.SCHEMA,
        content=summary,
        origin=Origin(source, f"{ws.title}!A1:{get_column_letter(max(ws.max_column, 1))}{ws.max_row}"),
        role=Role.UNKNOWN,
        structure=(ws.title,),
        salience=0.9,
        meta={
            "sheet": ws.title,
            "sheet_summary": True,
            "definition_cue": True,
            "rows": ws.max_row,
            "columns": ws.max_column,
            "populated": len(grid),
            "formulas": formulas,
        },
    )


# --------------------------------------------------------------------------- #
# Formula analysis
# --------------------------------------------------------------------------- #


def _formula_tokens(formula: str):
    if len(formula) > 16_384:
        raise ValueError("XLSX formula-length limit exceeded")
    try:
        return Tokenizer(formula).items
    except TokenizerError:
        return []


class _ReferenceIndex:
    """A workbook's sparse native cells and a bounded range-query cache."""

    def __init__(self, grids: dict[str, dict[str, object]]) -> None:
        self.sheets = {name.casefold(): name for name in grids}
        self.positions = {}
        for sheet, grid in grids.items():
            self.positions[sheet] = sorted(
                (_split(cell)[1], _col_index(_split(cell)[0]), cell) for cell in grid
            )
        self.visits = 0
        self.ranges: dict[tuple[str, int, int, int, int], set[str]] = {}

    def cells_in_range(self, sheet, left, top, right, bottom) -> set[str]:
        from bisect import bisect_left, bisect_right

        key = (sheet, left, top, right, bottom)
        if key not in self.ranges:
            positions = self.positions[sheet]
            start = bisect_left(positions, (top, 0, ""))
            end = bisect_right(positions, (bottom, 16_385, ""))
            self.visits += end - start
            if self.visits > _MAX_RANGE_VISITS:
                raise ValueError("XLSX formula range-inspection limit exceeded")
            self.ranges[key] = {
                f"{sheet}!{cell}" for _row, col, cell in positions[start:end]
                if left <= col <= right
            }
        return self.ranges[key]


def _dependencies(
    formula: str,
    current_sheet: str,
    *,
    references: _ReferenceIndex,
    unresolved: list[str],
) -> set[str]:
    """Resolve native reference operands, never strings or function names.

    Ranges include every populated cell. Unresolved names, external/3-D
    references, and dynamic references become findings at the formula cell;
    they must not be silently presented as a complete dependency graph.
    """
    found: set[str] = set()
    tokens = _formula_tokens(formula)
    if not tokens:
        unresolved.append("formula syntax could not be tokenized")
    for index, token in enumerate(tokens[1:-1], start=1):
        before, after = tokens[index - 1], tokens[index + 1]
        if token.type == "WHITE-SPACE" and (
            before.subtype == "RANGE" or before.subtype == "CLOSE"
        ) and (
            after.subtype == "RANGE"
            or after.type in {"PAREN", "FUNC"} and after.subtype == "OPEN"
        ):
            unresolved.append("reference intersection is not resolved")
            return found
    for token in tokens:
        if token.type == "FUNC" and token.subtype == "OPEN":
            if token.value[:-1].upper() in {"INDIRECT", "OFFSET"}:
                unresolved.append(f"dynamic {token.value[:-1].upper()} target")
            continue
        if token.type != "OPERAND" or token.subtype != "RANGE":
            if token.subtype == "ERROR" and token.value == "#REF!":
                unresolved.append(token.value)
            continue
        reference = token.value
        if "!" in reference:
            qualifier, address = reference.rsplit("!", 1)
            sheet = qualifier[1:-1].replace("''", "'") if qualifier.startswith("'") and qualifier.endswith("'") else qualifier
        else:
            sheet, address = current_sheet, reference
        sheet = references.sheets.get(sheet.casefold(), sheet)
        if sheet not in references.positions or any(character in sheet for character in "[]:"):
            unresolved.append(reference)
            continue
        address = address.replace("$", "").upper()
        if _REF.fullmatch(address):
            column, row = _split(address)
            if _col_index(column) <= 16_384 and row <= 1_048_576:
                found.add(f"{sheet}!{address}")
            else:
                unresolved.append(reference)
            continue
        if ":" not in address:
            unresolved.append(reference)
            continue
        try:
            left, top, right, bottom = range_boundaries(address)
        except ValueError:
            unresolved.append(reference)
            continue
        left, top = left or 1, top or 1
        right, bottom = right or 16_384, bottom or 1_048_576
        if not (1 <= left <= right <= 16_384 and 1 <= top <= bottom <= 1_048_576):
            unresolved.append(reference)
            continue
        found.update(references.cells_in_range(sheet, left, top, right, bottom))
    return found


def _suspect_literals(formula: str) -> list[str]:
    """Numbers typed directly into a formula that probably should be inputs."""
    out: list[str] = []
    for token in _formula_tokens(formula):
        if token.type != "OPERAND" or token.subtype != "NUMBER":
            continue
        raw = token.value
        if raw in _BENIGN_LITERALS:
            continue
        out.append(raw)
    return sorted(set(out))


def _infer_labels(sheet: str, grid: dict[str, object], texts: dict[str, str]) -> dict[str, str]:
    """Best-effort human label for each cell.

    Spreadsheets label by convention rather than by structure: the text
    immediately to the left of a value, or failing that the column header above
    it. Both conventions are common and neither is guaranteed, so an unlabeled
    cell is reported as undocumented rather than given a made-up name.
    """
    labels: dict[str, str] = {}
    by_col: dict[str, list[int]] = defaultdict(list)
    for addr in texts:
        col, row = _split(addr)
        by_col[col].append(row)

    for addr in grid:
        col, row = _split(addr)
        if left := _nearest_left(texts, col, row):
            labels[f"{sheet}!{addr}"] = left
            continue
        if header := _column_header(texts, by_col, col, row):
            labels[f"{sheet}!{addr}"] = header
    return labels


def _split(addr: str) -> tuple[str, int]:
    i = 0
    while i < len(addr) and addr[i].isalpha():
        i += 1
    return addr[:i], int(addr[i:] or 0)


def _col_index(col: str) -> int:
    n = 0
    for ch in col:
        n = n * 26 + (ord(ch) - 64)
    return n


def _nearest_left(texts: dict[str, str], col: str, row: int) -> str:
    """Scan up to three columns left for a text label in the same row."""
    idx = _col_index(col)
    for back in range(1, 4):
        if idx - back < 1:
            break
        candidate = f"{get_column_letter(idx - back)}{row}"
        if label := texts.get(candidate):
            return label
    return ""


def _column_header(texts: dict[str, str], by_col: dict[str, list[int]], col: str, row: int) -> str:
    """The nearest text cell above, in the same column."""
    rows = [r for r in by_col.get(col, ()) if r < row]
    if not rows:
        return ""
    return texts.get(f"{col}{max(rows)}", "")


def _cached_value(values_wb, sheet: str, addr: str):
    if values_wb is None or sheet not in values_wb.sheetnames:
        return None
    try:
        value = values_wb[sheet][addr].value
    except (KeyError, ValueError, IndexError):  # pragma: no cover
        return None
    return value if not isinstance(value, str) or not value.startswith("=") else None


def _describe(label: str, addr: str, formula: str | None, value) -> str:
    name = label or addr
    if formula:
        # The formula carries its own leading '=', so do not add a second one.
        shown = f"{name} {formula}" if formula.startswith("=") else f"{name} = {formula}"
        return f"{shown} -> {value}" if value is not None else shown
    return f"{name} = {value}"


# --------------------------------------------------------------------------- #
# Findings
# --------------------------------------------------------------------------- #


def _report_findings(
    result: Extraction,
    deps: dict[str, set[str]],
    referenced: set[str],
    formula_cells: dict[str, str],
    labels: dict[str, str],
    unit_by_cell: dict[str, Unit],
) -> None:
    undocumented = [
        u.meta["cell"]
        for u in result.units
        if u.meta.get("input") and not u.meta.get("documented")
    ]
    if undocumented:
        shown = ", ".join(sorted(undocumented)[:5])
        more = f" and {len(undocumented) - 5} more" if len(undocumented) > 5 else ""
        result.gaps.append(f"input cells with no adjacent label: {shown}{more}")

    if cycles := _cycles(deps):
        for cycle in cycles[:5]:
            result.gaps.append("circular reference: " + " -> ".join(cycle))

    outputs = [key for key in formula_cells if key not in referenced]
    if not outputs and formula_cells:
        result.gaps.append("every formula feeds another; the workbook has no terminal output")


def _cycles(deps: dict[str, set[str]]) -> list[list[str]]:
    """Find dependency cycles by iterative depth-first search.

    Iterative rather than recursive because a deep chain in a large workbook
    would otherwise blow the stack on exactly the sheets most worth analyzing.
    """
    found: list[list[str]] = []
    state: dict[str, int] = {}  # 0 = visiting, 1 = done

    for root in deps:
        if state.get(root) == 1:
            continue
        stack: list[tuple[str, list[str]]] = [(root, [root])]
        while stack:
            node, path = stack.pop()
            if state.get(node) == 1:
                continue
            state[node] = 0
            for nxt in sorted(deps.get(node, ())):
                if nxt in path:
                    found.append(path[path.index(nxt):] + [nxt])
                    continue
                if state.get(nxt) != 1 and nxt in deps:
                    stack.append((nxt, path + [nxt]))
            state[node] = 1
    return found
