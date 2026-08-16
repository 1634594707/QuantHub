"""CSV/XLSX parsing for point-in-time universe batch maintenance."""

from __future__ import annotations

import base64
import csv
import io
import zipfile
from xml.etree import ElementTree

EXPECTED_COLUMNS = (
    "symbol",
    "effective_from",
    "effective_to",
    "status",
    "industry",
    "market_cap",
    "beta",
    "is_st",
    "listed_at",
    "delisted_at",
)


def _xlsx_rows(content: bytes) -> list[dict[str, str]]:
    namespace = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
    with zipfile.ZipFile(io.BytesIO(content)) as archive:
        shared: list[str] = []
        if "xl/sharedStrings.xml" in archive.namelist():
            root = ElementTree.fromstring(archive.read("xl/sharedStrings.xml"))
            for item in root.findall("m:si", namespace):
                shared.append(
                    "".join(node.text or "" for node in item.findall(".//m:t", namespace))
                )
        sheets = sorted(
            name
            for name in archive.namelist()
            if name.startswith("xl/worksheets/sheet") and name.endswith(".xml")
        )
        if not sheets:
            raise ValueError("XLSX 不包含工作表")
        root = ElementTree.fromstring(archive.read(sheets[0]))
        matrix: list[list[str]] = []
        for row in root.findall(".//m:sheetData/m:row", namespace):
            values: list[str] = []
            for cell in row.findall("m:c", namespace):
                reference = cell.attrib.get("r", "A1")
                letters = "".join(char for char in reference if char.isalpha())
                index = 0
                for char in letters:
                    index = index * 26 + ord(char.upper()) - 64
                while len(values) < max(0, index - 1):
                    values.append("")
                value_node = cell.find("m:v", namespace)
                value = value_node.text if value_node is not None and value_node.text else ""
                if cell.attrib.get("t") == "s" and value:
                    value = shared[int(value)]
                elif cell.attrib.get("t") == "inlineStr":
                    value = "".join(node.text or "" for node in cell.findall(".//m:t", namespace))
                values.append(value)
            matrix.append(values)
    if not matrix:
        return []
    headers = [item.strip() for item in matrix[0]]
    return [
        {headers[index]: value.strip() for index, value in enumerate(row) if index < len(headers)}
        for row in matrix[1:]
        if any(value.strip() for value in row)
    ]


def parse_universe_file(filename: str, content_base64: str) -> list[dict[str, str]]:
    try:
        content = base64.b64decode(content_base64, validate=True)
    except ValueError as exc:
        raise ValueError("content_base64 不是有效 Base64") from exc
    lowered = filename.lower()
    if lowered.endswith(".csv"):
        text = content.decode("utf-8-sig")
        rows = [dict(row) for row in csv.DictReader(io.StringIO(text))]
    elif lowered.endswith(".xlsx"):
        rows = _xlsx_rows(content)
    else:
        raise ValueError("仅支持 CSV 或 XLSX")
    if not rows:
        raise ValueError("导入文件没有数据行")
    missing = [column for column in ("symbol", "effective_from") if column not in rows[0]]
    if missing:
        raise ValueError(f"导入文件缺少字段: {', '.join(missing)}")
    return rows


def template_columns() -> list[str]:
    return list(EXPECTED_COLUMNS)
