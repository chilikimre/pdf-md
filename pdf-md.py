#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
pdf_to_md.py

Простой локальный конвертер PDF -> Markdown.
Работает лучше всего на текстовых PDF, где текст настоящий, а не картинкой.

Что делает:
- читает PDF через PyMuPDF
- группирует текст в блоки
- пытается выделять заголовки по размеру шрифта
- сохраняет списки
- чистит переносы строк
- пишет Markdown-файл

Установка:
    pip install pymupdf

Запуск:
    python pdf_to_md.py input.pdf
    python pdf_to_md.py input.pdf -o output.md
"""

from __future__ import annotations

import argparse
import re
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

import fitz  # PyMuPDF


@dataclass
class TextLine:
    text: str
    font_size: float
    is_bold: bool


def clean_text(text: str) -> str:
    text = text.replace("\u00a0", " ")
    text = text.replace("­", "")  # soft hyphen
    text = re.sub(r"[ \t]+", " ", text)
    return text.strip()


def looks_like_list_item(text: str) -> bool:
    return bool(re.match(r"^(\-|\*|•|—|\d+[\.\)])\s+", text))


def join_wrapped_lines(lines: List[str]) -> List[str]:
    """
    Склеивает строки, которые выглядят как перенос внутри абзаца.
    """
    result: List[str] = []
    buffer = ""

    for line in lines:
        line = line.strip()

        if not line:
            if buffer:
                result.append(buffer.strip())
                buffer = ""
            result.append("")
            continue

        if not buffer:
            buffer = line
            continue

        # Не склеиваем, если это список
        if looks_like_list_item(line):
            result.append(buffer.strip())
            buffer = line
            continue

        # Если предыдущая строка заканчивается на знак завершения мысли — новый абзац
        if re.search(r"[.!?:;…]$", buffer):
            result.append(buffer.strip())
            buffer = line
            continue

        # Если текущая строка похожа на заголовок короткой длины
        if len(line) < 80 and line == line.title():
            result.append(buffer.strip())
            buffer = line
            continue

        # Если был перенос слова с дефисом
        if buffer.endswith("-"):
            buffer = buffer[:-1] + line
        else:
            buffer += " " + line

    if buffer:
        result.append(buffer.strip())

    return result


def extract_lines_from_page(page: fitz.Page) -> List[TextLine]:
    data = page.get_text("dict")
    lines: List[TextLine] = []

    for block in data.get("blocks", []):
        if block.get("type") != 0:
            continue

        for line in block.get("lines", []):
            spans = line.get("spans", [])
            if not spans:
                continue

            text = "".join(span.get("text", "") for span in spans)
            text = clean_text(text)
            if not text:
                continue

            avg_size = sum(span.get("size", 0.0) for span in spans) / max(len(spans), 1)
            is_bold = any(
                "bold" in str(span.get("font", "")).lower() or (span.get("flags", 0) & 16)
                for span in spans
            )

            lines.append(
                TextLine(
                    text=text,
                    font_size=avg_size,
                    is_bold=is_bold,
                )
            )

    return lines


def detect_base_font_size(all_lines: List[TextLine]) -> float:
    if not all_lines:
        return 11.0

    sizes = [round(line.font_size, 1) for line in all_lines if line.text]
    if not sizes:
        return 11.0

    freq = {}
    for size in sizes:
        freq[size] = freq.get(size, 0) + 1

    return max(freq.items(), key=lambda x: x[1])[0]


def md_heading_level(font_size: float, base_size: float) -> Optional[int]:
    """
    Грубая эвристика по размеру шрифта.
    """
    if font_size >= base_size * 1.9:
        return 1
    if font_size >= base_size * 1.6:
        return 2
    if font_size >= base_size * 1.35:
        return 3
    if font_size >= base_size * 1.2:
        return 4
    return None


def convert_pdf_to_markdown(pdf_path: Path) -> str:
    doc = fitz.open(pdf_path)
    all_lines: List[TextLine] = []

    pages_lines: List[List[TextLine]] = []
    for page in doc:
        lines = extract_lines_from_page(page)
        pages_lines.append(lines)
        all_lines.extend(lines)

    base_size = detect_base_font_size(all_lines)

    md_lines: List[str] = []
    last_was_heading = False

    for page_num, lines in enumerate(pages_lines, start=1):
        if not lines:
            continue

        page_out: List[str] = []

        for line in lines:
            text = line.text

            # Пропускаем пустое
            if not text:
                page_out.append("")
                continue

            # Пытаемся понять, это заголовок или нет
            heading_level = md_heading_level(line.font_size, base_size)

            is_short = len(text) <= 120
            looks_like_heading = (
                heading_level is not None
                and is_short
                and not looks_like_list_item(text)
                and not text.endswith(".")
            )

            if looks_like_heading:
                page_out.append(f"{'#' * heading_level} {text}")
                page_out.append("")
                last_was_heading = True
                continue

            # Списки
            if re.match(r"^(•|—|\-)\s+", text):
                text = re.sub(r"^(•|—|\-)\s+", "- ", text)
                page_out.append(text)
                last_was_heading = False
                continue

            if re.match(r"^\d+[\.\)]\s+", text):
                page_out.append(text)
                last_was_heading = False
                continue

            # Болд-строки иногда тоже заголовки
            if line.is_bold and is_short and not text.endswith(".") and len(text.split()) <= 12:
                page_out.append(f"### {text}")
                page_out.append("")
                last_was_heading = True
                continue

            page_out.append(text)
            last_was_heading = False

        # Склеиваем переносы
        page_out = join_wrapped_lines(page_out)

        # Разделитель страниц можно включить, если надо
        if md_lines:
            md_lines.append("\n---\n")

        md_lines.extend(page_out)

    # Финальная чистка
    output = "\n".join(md_lines)
    output = re.sub(r"\n{3,}", "\n\n", output)
    output = output.strip() + "\n"

    return output


def main() -> None:
    parser = argparse.ArgumentParser(description="Конвертер PDF -> Markdown")
    parser.add_argument("input_pdf", type=Path, help="Путь к PDF-файлу")
    parser.add_argument("-o", "--output", type=Path, help="Путь к выходному .md")
    args = parser.parse_args()

    input_pdf: Path = args.input_pdf
    if not input_pdf.exists():
        raise FileNotFoundError(f"Файл не найден: {input_pdf}")

    output_md = args.output or input_pdf.with_suffix(".md")
    markdown = convert_pdf_to_markdown(input_pdf)

    output_md.write_text(markdown, encoding="utf-8")
    print(f"Готово: {output_md}")


if __name__ == "__main__":
    main()