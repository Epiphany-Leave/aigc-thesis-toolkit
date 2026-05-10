#!/usr/bin/env python3
import re
import shutil
import sys
import tempfile
import zipfile
from copy import deepcopy
from pathlib import Path
from xml.etree import ElementTree as ET


NS = {
    "w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main",
    "m": "http://schemas.openxmlformats.org/officeDocument/2006/math",
}

FORMULA_STYLE = "aff2"
STANDARD_TABLE_STYLE = "aff4"
TABLE_CONTENT_STYLE = "aff0"
CAPTION_STYLE = "aff5"
TITLE_STYLE = "af4"
REFERENCE_TEXT_STYLE = "a"
TOC_STYLE_MAP = {
    "TOC1": "10",
    "TOC2": "21",
    "TOC3": "31",
}

for prefix, uri in NS.items():
    ET.register_namespace(prefix, uri)


def qn(name):
    prefix, tag = name.split(":")
    return f"{{{NS[prefix]}}}{tag}"


def find_child(parent, name):
    return parent.find(qn(name))


def ensure_child(parent, name):
    child = find_child(parent, name)
    if child is None:
        child = ET.SubElement(parent, qn(name))
    return child


def cell_text(cell):
    return "".join(node.text or "" for node in cell.findall(".//w:t", NS))


def has_math(cell):
    return cell.find(".//m:oMath", NS) is not None or cell.find(".//m:oMathPara", NS) is not None


def is_equation_number_table(tbl):
    rows = tbl.findall("w:tr", NS)
    if len(rows) != 1:
        return False

    cells = rows[0].findall("w:tc", NS)
    if len(cells) != 2:
        return False

    return has_math(cells[0]) and re.fullmatch(r"\s*\([0-9]+-[0-9]+\)\s*", cell_text(cells[1]))


def first_math(cell):
    math = cell.find(".//m:oMath", NS)
    if math is not None:
        return math
    math_para = cell.find(".//m:oMathPara", NS)
    if math_para is not None:
        return math_para.find(".//m:oMath", NS)
    return None


def set_attr(element, name, value):
    element.set(qn(name), value)


def tab_run():
    run = ET.Element(qn("w:r"))
    ET.SubElement(run, qn("w:tab"))
    return run


def text_run(text):
    run = ET.Element(qn("w:r"))
    node = ET.SubElement(run, qn("w:t"))
    node.text = text
    return run


def ensure_run_properties(run):
    r_pr = run.find(qn("w:rPr"))
    if r_pr is None:
        r_pr = ET.Element(qn("w:rPr"))
        run.insert(0, r_pr)
    return r_pr


def set_reference_run_font(run):
    r_pr = ensure_run_properties(run)
    fonts = r_pr.find(qn("w:rFonts"))
    if fonts is None:
        fonts = ET.SubElement(r_pr, qn("w:rFonts"))
    set_attr(fonts, "w:ascii", "Times New Roman")
    set_attr(fonts, "w:hAnsi", "Times New Roman")
    set_attr(fonts, "w:eastAsia", "\u5b8b\u4f53")

    size = r_pr.find(qn("w:sz"))
    if size is None:
        size = ET.SubElement(r_pr, qn("w:sz"))
    set_attr(size, "w:val", "21")

    size_cs = r_pr.find(qn("w:szCs"))
    if size_cs is None:
        size_cs = ET.SubElement(r_pr, qn("w:szCs"))
    set_attr(size_cs, "w:val", "21")


def eq_bookmark(number):
    return f"eq_{number.strip('()').replace('-', '_')}"


def caption_bookmark(prefix, number):
    return f"{prefix}_{number.replace('-', '_')}"


def bookmark_start(bookmark_id, name):
    node = ET.Element(qn("w:bookmarkStart"))
    set_attr(node, "w:id", str(bookmark_id))
    set_attr(node, "w:name", name)
    return node


def bookmark_end(bookmark_id):
    node = ET.Element(qn("w:bookmarkEnd"))
    set_attr(node, "w:id", str(bookmark_id))
    return node


def bookmark_id_for(number):
    parts = re.findall(r"\d+", number)
    if len(parts) >= 2:
        return 50000 + int(parts[0]) * 1000 + int(parts[1])
    return 50000


def caption_bookmark_id(prefix, number):
    base = {"fig": 70000, "tab": 90000}.get(prefix, 110000)
    parts = re.findall(r"\d+", number)
    if len(parts) >= 2:
        return base + int(parts[0]) * 1000 + int(parts[1])
    return base


def equation_paragraph(tbl):
    cells = tbl.findall("w:tr/w:tc", NS)
    math = first_math(cells[0])
    number = cell_text(cells[1]).strip()
    if math is None or not number:
        return None

    paragraph = ET.Element(qn("w:p"))
    p_pr = ET.SubElement(paragraph, qn("w:pPr"))
    p_style = ET.SubElement(p_pr, qn("w:pStyle"))
    set_attr(p_style, "w:val", FORMULA_STYLE)

    paragraph.append(tab_run())
    paragraph.append(deepcopy(math))
    paragraph.append(tab_run())
    bookmark_id = bookmark_id_for(number)
    paragraph.append(bookmark_start(bookmark_id, eq_bookmark(number)))
    paragraph.append(text_run(number))
    paragraph.append(bookmark_end(bookmark_id))
    return paragraph


def paragraph_text(paragraph):
    return "".join(node.text or "" for node in paragraph.findall(".//w:t", NS))


def style_id(paragraph):
    style = paragraph.find("w:pPr/w:pStyle", NS)
    return style.get(qn("w:val")) if style is not None else ""


def set_paragraph_style(paragraph, value):
    p_pr = ensure_child(paragraph, "w:pPr")
    p_style = ensure_child(p_pr, "w:pStyle")
    set_attr(p_style, "w:val", value)


def page_break_paragraph():
    paragraph = ET.Element(qn("w:p"))
    run = ET.SubElement(paragraph, qn("w:r"))
    br = ET.SubElement(run, qn("w:br"))
    set_attr(br, "w:type", "page")
    return paragraph


def section_break_paragraph(page_format, start=1):
    paragraph = ET.Element(qn("w:p"))
    p_pr = ET.SubElement(paragraph, qn("w:pPr"))
    sect_pr = ET.SubElement(p_pr, qn("w:sectPr"))
    sect_type = ET.SubElement(sect_pr, qn("w:type"))
    set_attr(sect_type, "w:val", "nextPage")
    pg_num = ET.SubElement(sect_pr, qn("w:pgNumType"))
    set_attr(pg_num, "w:fmt", page_format)
    set_attr(pg_num, "w:start", str(start))
    return paragraph


def ensure_body_section_numbering(body, page_format, start=1):
    sect_pr = body.find("w:sectPr", NS)
    if sect_pr is None:
        sect_pr = ET.SubElement(body, qn("w:sectPr"))

    pg_num = sect_pr.find("w:pgNumType", NS)
    if pg_num is None:
        pg_num = ET.SubElement(sect_pr, qn("w:pgNumType"))

    set_attr(pg_num, "w:fmt", page_format)
    set_attr(pg_num, "w:start", str(start))


def is_toc_node(node):
    if node.tag != qn("w:sdt"):
        return False

    text = ET.tostring(node, encoding="unicode")
    return "TOC" in text or "Table of Contents" in text


def localize_toc_heading(toc_node):
    for paragraph in toc_node.findall(".//w:p", NS):
        if style_id(paragraph) == "TOCHeading":
            text_node = paragraph.find(".//w:t", NS)
            if text_node is not None:
                text_node.text = "\u76ee\u5f55"
            return


def is_top_heading(paragraph):
    return paragraph.tag == qn("w:p") and style_id(paragraph) == "1"


def is_abstract_heading(paragraph):
    text = re.sub(r"\s+", "", paragraph_text(paragraph))
    return is_top_heading(paragraph) and text in {"\u6458\u8981", "Abstract"}


def is_chapter_heading(paragraph):
    text = paragraph_text(paragraph).strip()
    return is_top_heading(paragraph) and re.match(r"^\u7b2c[0-9\u4e00-\u4e5d\u5341]+\u7ae0", text)


def is_body_top_heading(paragraph):
    return is_top_heading(paragraph) and not is_abstract_heading(paragraph)


def body_index(body, target):
    for index, child in enumerate(list(body)):
        if child is target:
            return index
    return None


def apply_front_matter_layout(root):
    body = root.find("w:body", NS)
    if body is None:
        return 0

    changed = 0
    children = list(body)

    for child in children:
        if is_toc_node(child):
            body.remove(child)
            localize_toc_heading(child)
            toc_node = child
            changed += 1
            break
    else:
        toc_node = None

    children = list(body)
    title_done = False
    for child in children:
        if is_top_heading(child):
            text = paragraph_text(child).strip()
            if text and not is_abstract_heading(child) and not is_chapter_heading(child):
                set_paragraph_style(child, TITLE_STYLE)
                changed += 1
            title_done = True
            break
    if not title_done:
        return changed

    abstract_headings = [child for child in list(body) if is_abstract_heading(child)]
    if len(abstract_headings) >= 2:
        abstract_index = body_index(body, abstract_headings[1])
        if abstract_index is not None:
            body.insert(abstract_index, page_break_paragraph())
            changed += 1

    chapter_headings = [child for child in list(body) if is_chapter_heading(child)]
    body_top_candidates = [child for child in list(body) if is_body_top_heading(child)]
    first_chapter = chapter_headings[0] if chapter_headings else (body_top_candidates[0] if body_top_candidates else None)
    first_chapter_index = body_index(body, first_chapter) if first_chapter is not None else None
    if first_chapter_index is not None and toc_node is not None:
        body.insert(first_chapter_index, section_break_paragraph("lowerRoman", 1))
        body.insert(first_chapter_index, toc_node)
        body.insert(first_chapter_index, page_break_paragraph())
        changed += 3

    body_headings = [child for child in list(body) if is_body_top_heading(child)]
    if first_chapter in body_headings:
        body_headings = body_headings[body_headings.index(first_chapter) :]

    for child in body_headings[1:]:
        index = body_index(body, child)
        if index is not None:
            body.insert(index, page_break_paragraph())
            changed += 1

    if toc_node is None and first_chapter is not None:
        first_chapter_index = body_index(body, first_chapter)
        if first_chapter_index is not None:
            body.insert(first_chapter_index, section_break_paragraph("lowerRoman", 1))
            changed += 1

    ensure_body_section_numbering(body, "decimal", 1)
    changed += 1
    return changed


def wrap_first_caption_number(paragraph):
    text = paragraph_text(paragraph)
    match = re.match(r"\s*([\u56fe\u8868])([0-9]+-[0-9]+)", text)
    if not match:
        return False

    kind, number = match.groups()
    prefix = "fig" if kind == "\u56fe" else "tab"
    target = f"{kind}{number}"
    bookmark_name = caption_bookmark(prefix, number)
    bookmark_id = caption_bookmark_id(prefix, number)
    changed = style_id(paragraph) != CAPTION_STYLE

    set_paragraph_style(paragraph, CAPTION_STYLE)

    if bookmark_name in ET.tostring(paragraph, encoding="unicode"):
        return changed

    remaining = len(target)
    inserted_start = False

    for run in list(paragraph.findall("w:r", NS)):
        texts = run.findall(".//w:t", NS)
        if not texts:
            continue

        for text_node in texts:
            value = text_node.text or ""
            if not value or remaining <= 0:
                continue

            if not inserted_start:
                paragraph.insert(list(paragraph).index(run), bookmark_start(bookmark_id, bookmark_name))
                inserted_start = True

            consume = min(remaining, len(value))
            remaining -= consume
            if remaining == 0:
                paragraph.insert(list(paragraph).index(run) + 1, bookmark_end(bookmark_id))
                return True

    return changed


def add_caption_bookmarks(root):
    changed = 0
    for paragraph in root.findall(".//w:p", NS):
        if wrap_first_caption_number(paragraph):
            changed += 1
    return changed


def set_table_style(tbl, style_name):
    tbl_pr = ensure_child(tbl, "w:tblPr")
    tbl_style = ensure_child(tbl_pr, "w:tblStyle")
    before = tbl_style.get(qn("w:val"))
    set_attr(tbl_style, "w:val", style_name)
    return before != style_name


def apply_standard_table_style(root):
    changed = 0
    for tbl in root.findall(".//w:tbl", NS):
        if is_equation_number_table(tbl):
            continue
        if set_table_style(tbl, STANDARD_TABLE_STYLE):
            changed += 1
    return changed


def apply_table_content_style(root):
    changed = 0
    for tbl in root.findall(".//w:tbl", NS):
        if is_equation_number_table(tbl):
            continue

        for paragraph in tbl.findall(".//w:p", NS):
            if style_id(paragraph) != TABLE_CONTENT_STYLE:
                set_paragraph_style(paragraph, TABLE_CONTENT_STYLE)
                changed += 1

    return changed


def is_formula_paragraph(paragraph):
    return paragraph.tag == qn("w:p") and style_id(paragraph) == FORMULA_STYLE


def is_empty_paragraph(paragraph):
    if paragraph.tag != qn("w:p"):
        return False
    if paragraph_text(paragraph).strip():
        return False
    if paragraph.find(".//m:oMath", NS) is not None or paragraph.find(".//m:oMathPara", NS) is not None:
        return False
    if paragraph.find(".//w:br", NS) is not None:
        return False
    if paragraph.find("w:pPr/w:sectPr", NS) is not None:
        return False
    return True


def remove_empty_paragraphs_between_equations(parent):
    changed = 0
    children = list(parent)
    index = 1
    while index < len(children) - 1:
        child = children[index]
        if (
            is_empty_paragraph(child)
            and is_formula_paragraph(children[index - 1])
            and is_formula_paragraph(children[index + 1])
        ):
            parent.remove(child)
            children.pop(index)
            changed += 1
            continue
        index += 1

    for child in list(parent):
        changed += remove_empty_paragraphs_between_equations(child)

    return changed


def apply_toc_styles(root):
    changed = 0
    for paragraph in root.findall(".//w:p", NS):
        mapped = TOC_STYLE_MAP.get(style_id(paragraph))
        if mapped is not None:
            set_paragraph_style(paragraph, mapped)
            changed += 1
    return changed


def is_heading_one(paragraph):
    return paragraph.tag == qn("w:p") and style_id(paragraph) == "1"


def apply_reference_styles(root):
    body = root.find("w:body", NS)
    if body is None:
        return 0
    changed = 0
    in_references = False
    for child in body:
        if child.tag != qn("w:p"):
            continue
        text = paragraph_text(child).strip()
        if is_heading_one(child):
            if text == "\u53c2\u8003\u6587\u732e":
                in_references = True
                continue
            if in_references:
                break
        if not in_references or not text:
            continue
        if style_id(child) != REFERENCE_TEXT_STYLE:
            set_paragraph_style(child, REFERENCE_TEXT_STYLE)
            changed += 1
        for run in child.findall("w:r", NS):
            set_reference_run_font(run)
            changed += 1
    return changed


def replace_equation_tables(parent):
    changed = 0
    for index, child in enumerate(list(parent)):
        if child.tag == qn("w:tbl") and is_equation_number_table(child):
            paragraph = equation_paragraph(child)
            if paragraph is not None:
                parent[index] = paragraph
                changed += 1
            continue

        changed += replace_equation_tables(child)

    return changed


def postprocess_document_xml(xml_text):
    root = ET.fromstring(xml_text)
    changed = apply_front_matter_layout(root)
    changed += replace_equation_tables(root)
    changed += remove_empty_paragraphs_between_equations(root)
    changed += apply_standard_table_style(root)
    changed += apply_table_content_style(root)
    changed += add_caption_bookmarks(root)
    changed += apply_toc_styles(root)
    changed += apply_reference_styles(root)
    return ET.tostring(root, encoding="utf-8", xml_declaration=True), changed


def enable_field_updates(settings_xml):
    root = ET.fromstring(settings_xml)
    update_fields = root.find("w:updateFields", NS)
    changed = False
    if update_fields is None:
        update_fields = ET.SubElement(root, qn("w:updateFields"))
        changed = True

    if update_fields.get(qn("w:val")) != "true":
        set_attr(update_fields, "w:val", "true")
        changed = True

    return ET.tostring(root, encoding="utf-8", xml_declaration=True), changed


def style_by_id(root, style_id_value):
    for style in root.findall("w:style", NS):
        if style.get(qn("w:styleId")) == style_id_value:
            return style
    return None


def copy_style_definition(root, source_id, target_id):
    source = style_by_id(root, source_id)
    target = style_by_id(root, target_id)
    if source is None:
        return False

    if target is None:
        target = deepcopy(source)
        set_attr(target, "w:styleId", target_id)
        root.append(target)
        return True

    target.attrib.clear()
    target.attrib.update(source.attrib)
    set_attr(target, "w:styleId", target_id)
    target[:] = [deepcopy(child) for child in list(source)]
    return True


def apply_reference_toc_style_definitions(styles_xml):
    root = ET.fromstring(styles_xml)
    changed = False
    for target_id, source_id in TOC_STYLE_MAP.items():
        if copy_style_definition(root, source_id, target_id):
            changed = True
    return ET.tostring(root, encoding="utf-8", xml_declaration=True), changed


def postprocess_docx(path):
    src = Path(path)
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp = Path(tmp_dir)
        unpacked = tmp / "docx"
        unpacked.mkdir()

        with zipfile.ZipFile(src, "r") as docx:
            docx.extractall(unpacked)

        document_xml = unpacked / "word" / "document.xml"
        updated, changed = postprocess_document_xml(document_xml.read_text(encoding="utf-8"))
        document_xml.write_bytes(updated)

        settings_xml = unpacked / "word" / "settings.xml"
        if settings_xml.exists():
            updated_settings, settings_changed = enable_field_updates(settings_xml.read_text(encoding="utf-8"))
            settings_xml.write_bytes(updated_settings)
            changed += int(settings_changed)

        styles_xml = unpacked / "word" / "styles.xml"
        if styles_xml.exists():
            updated_styles, styles_changed = apply_reference_toc_style_definitions(styles_xml.read_text(encoding="utf-8"))
            styles_xml.write_bytes(updated_styles)
            changed += int(styles_changed)

        new_docx = tmp / "updated.docx"
        with zipfile.ZipFile(new_docx, "w", compression=zipfile.ZIP_DEFLATED) as docx:
            for file in unpacked.rglob("*"):
                if file.is_file():
                    docx.write(file, file.relative_to(unpacked).as_posix())

        shutil.copyfile(new_docx, src)

    print(f"OK: docx cross references postprocessed: {changed}")
    return 0


def main():
    if len(sys.argv) != 2:
        print("Usage: postprocess_docx.py <docx>", file=sys.stderr)
        return 1

    return postprocess_docx(sys.argv[1])


if __name__ == "__main__":
    raise SystemExit(main())
