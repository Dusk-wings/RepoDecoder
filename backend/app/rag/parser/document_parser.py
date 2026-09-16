from rag.parser.image_pipeline import VisionFilePipeline
import zipfile
import os
from pptx import Presentation
import xml.etree.ElementTree as ET
import re
import pypandoc
import urllib.parse
from pathlib import Path
import shutil


class DocumentParser(VisionFilePipeline):
    def __init__(self, media_temp_dir: str = "temp_media") -> None:
        super().__init__()
        self.supported_extensions = {".docx", ".pptx", ".odt", ".rtf"}
        self.media_temp_dir = media_temp_dir

    def _extract_office_images(self, filepath: str, output_dir: str) -> dict:
        """
        Extracts images directly from .docx, .pptx, and .odt zip structures,
        as well as .rtf files via Pandoc conversion.
        Returns a mapping of { image_filename: full_extracted_path }.
        """
        extracted_map = {}
        os.makedirs(output_dir, exist_ok=True)

        # Handle RTF files via Pandoc media extraction
        if filepath.lower().endswith(".rtf"):
            media_dir = os.path.join(output_dir, "rtf_media")

            # Convert RTF -> Markdown and tell Pandoc to extract media
            pypandoc.convert_file(
                filepath,
                "markdown",
                extra_args=[f"--extract-media={media_dir}", "--quiet"],
            )

            # Walk through the extracted media folder to populate extracted_map
            if os.path.exists(media_dir):
                for root, _, files in os.walk(media_dir):
                    for file in files:
                        full_path = os.path.join(root, file)
                        extracted_map[file] = full_path

            return extracted_map

        # Handle ZIP-based formats (.docx, .pptx, .odt)
        if not zipfile.is_zipfile(filepath):
            return extracted_map

        with zipfile.ZipFile(filepath, "r") as z:
            for member in z.namelist():
                # 'Pictures/' catches .odt images, 'word/media/' for docx, 'ppt/media/' for pptx
                if member.startswith(
                    ("word/media/", "ppt/media/", "Pictures/")
                ) and not member.endswith("/"):
                    z.extract(member, path=output_dir)
                    full_path = os.path.join(output_dir, member)
                    filename = os.path.basename(member)
                    extracted_map[filename] = full_path

        return extracted_map

    def _extract_pptx_charts_as_markdown(self, pptx_path: str) -> list:
        """Reads PowerPoint charts via python-pptx."""
        chart_tables = []
        try:
            prs = Presentation(pptx_path)
            for slide_num, slide in enumerate(prs.slides, start=1):
                for shape in slide.shapes:
                    if shape.has_chart:
                        chart = getattr(shape, "chart", None)
                        if chart is None:
                            continue
                        title = (
                            chart.chart_title.text_frame.text
                            if chart.has_title
                            else f"Slide {slide_num} Chart"
                        )
                        categories = [str(c.label) for c in chart.plots[0].categories]
                        series_list = chart.series

                        series_names = [
                            s.name if s.name else f"Series {i+1}"
                            for i, s in enumerate(series_list)
                        ]
                        md_table = (
                            f"\n\n### [Chart Data: {title} (Slide {slide_num})]\n"
                        )
                        md_table += "| Category | " + " | ".join(series_names) + " |\n"
                        md_table += (
                            "|---| " + " | ".join(["---"] * len(series_names)) + " |\n"
                        )

                        for cat_idx, cat in enumerate(categories):
                            row_vals = []
                            for series in series_list:
                                try:
                                    row_vals.append(str(series.values[cat_idx]))
                                except IndexError:
                                    row_vals.append("-")
                            md_table += f"| {cat} | " + " | ".join(row_vals) + " |\n"

                        chart_tables.append(md_table)
        except Exception as e:
            print(f"[Warning] Could not extract PPTX chart data: {e}")

        return chart_tables

    def _extract_docx_charts_as_markdown(self, docx_path: str) -> list:
        """Reads Word charts natively from the DOCX XML zip structure."""
        chart_tables = []
        if not zipfile.is_zipfile(docx_path):
            return chart_tables

        try:
            with zipfile.ZipFile(docx_path, "r") as z:
                chart_files = [
                    f
                    for f in z.namelist()
                    if f.startswith("word/charts/chart") and f.endswith(".xml")
                ]
                for chart_num, chart_file in enumerate(chart_files, start=1):
                    root = ET.fromstring(z.read(chart_file))
                    ns = {"c": "http://schemas.openxmlformats.org/drawingml/2006/chart"}

                    title_node = root.find(".//c:title//c:tx//c:v", ns)
                    title = (
                        title_node.text
                        if title_node is not None
                        else f"Chart {chart_num}"
                    )

                    series_nodes = root.findall(".//c:ser", ns)
                    if not series_nodes:
                        continue

                    categories = [
                        cat.text or ""
                        for cat in series_nodes[0].findall(".//c:cat//c:pt/c:v", ns)
                    ]
                    series_names, series_data = [], []

                    for ser in series_nodes:
                        tx_node = ser.find(".//c:tx//c:v", ns)
                        series_names.append(
                            tx_node.text
                            if tx_node is not None
                            else f"Series {len(series_names)+1}"
                        )
                        series_data.append(
                            [
                                v.text or "-"
                                for v in ser.findall(".//c:val//c:pt/c:v", ns)
                            ]
                        )

                    md_table = (
                        f"\n\n### [Chart Data: {title}]\n| Category | "
                        + " | ".join(series_names)
                        + " |\n"
                    )
                    md_table += (
                        "|---| " + " | ".join(["---"] * len(series_names)) + " |\n"
                    )

                    for i, cat in enumerate(categories):
                        row = [cat] + [
                            s_data[i] if i < len(s_data) else "-"
                            for s_data in series_data
                        ]
                        md_table += "| " + " | ".join(row) + " |\n"

                    chart_tables.append(md_table)
        except Exception as e:
            print(f"[Warning] Could not extract DOCX chart data: {e}")

        return chart_tables

    def _extract_odt_charts_as_markdown(self, odt_path: str) -> dict:
        """
        Reads charts directly from embedded objects in ODT files.
        Returns a mapping of { 'ObjectReplacements/Object X': markdown_table }
        """
        chart_map = {}
        if not zipfile.is_zipfile(odt_path):
            return chart_map

        try:
            with zipfile.ZipFile(odt_path, "r") as z:
                object_contents = [
                    f
                    for f in z.namelist()
                    if f.startswith("Object ") and f.endswith("/content.xml")
                ]

                for obj_file in object_contents:
                    root = ET.fromstring(z.read(obj_file))
                    ns = {
                        "table": "urn:oasis:names:tc:opendocument:xmlns:table:1.0",
                        "text": "urn:oasis:names:tc:opendocument:xmlns:text:1.0",
                    }

                    tables = root.findall(".//table:table", ns)
                    if not tables:
                        continue

                    parsed_rows = []
                    for row in tables[0].findall(".//table:table-row", ns):
                        row_data = []
                        for cell in row.findall(".//table:table-cell", ns):
                            text_p = cell.find(".//text:p", ns)
                            # Safely extract text and ensure it is a string
                            val = text_p.text if text_p is not None else None
                            row_data.append(str(val).strip() if val else "-")

                        if any(r != "-" for r in row_data):
                            parsed_rows.append(row_data)

                    if len(parsed_rows) < 2:
                        continue

                    obj_name = obj_file.split("/")[0]  # E.g., 'Object 1'
                    header = parsed_rows[0]

                    md_table = f"\n\n### [Chart Data: {obj_name}]\n"
                    md_table += "| " + " | ".join(header) + " |\n"
                    md_table += "|---" * len(header) + "|\n"

                    for row in parsed_rows[1:]:
                        # Pad row if it's missing trailing columns
                        padded_row = row + ["-"] * (len(header) - len(row))
                        md_table += "| " + " | ".join(padded_row) + " |\n"

                    # Map to the exact path Pandoc uses in its placeholder
                    chart_map[f"ObjectReplacements/{obj_name}"] = md_table

        except Exception as e:
            print(f"[Warning] Could not extract ODT chart data: {e}")

        return chart_map

    def parse(self, filepath: Path) -> str:
        """Main execution flow: Extract -> Analyze -> Format -> Clean."""
        if not os.path.exists(filepath):
            raise FileNotFoundError(f"File not found: {filepath}")

        ext = os.path.splitext(filepath)[1].lower()
        if ext not in self.supported_extensions:
            raise ValueError(
                f"Unsupported extension: {ext}. Only .docx, .pptx, and .odt are supported."
            )

        # 1. Extract embedded images directly from the zip structure
        extracted_images = self._extract_office_images(
            str(filepath), self.media_temp_dir
        )

        # 2. Process images: Call Save_Image() and Vision_LLM() once per image
        descriptions_by_filename = {}
        for img_filename, local_path in extracted_images.items():
            if os.path.exists(local_path):
                self._save_image(local_path)
                descriptions_by_filename[img_filename] = self._vission_LLM(local_path)

        # 3. Extract charts natively based on file type
        extracted_chart_tables_list = []
        extracted_odt_charts_map = {}

        if ext == ".pptx":
            extracted_chart_tables_list = self._extract_pptx_charts_as_markdown(
                str(filepath)
            )
        elif ext == ".docx":
            extracted_chart_tables_list = self._extract_docx_charts_as_markdown(
                str(filepath)
            )
        elif ext == ".odt":
            extracted_odt_charts_map = self._extract_odt_charts_as_markdown(
                str(filepath)
            )

        # 4. Parse main text layout and tables using Pandoc
        print(f"[System] Converting {ext} to Markdown via Pandoc...")
        markdown_content = pypandoc.convert_file(
            filepath,
            "markdown",
            extra_args=(
                [f"--extract-media={self.media_temp_dir}", "--quiet"]
                if filepath.suffix == ".rtf"
                else []
            ),
        )

        # 5. Replace Standard Images with LLM Descriptions
        def replace_image_with_llm(match) -> str:
            img_src = match.group(2)
            img_filename = os.path.basename(urllib.parse.unquote(img_src))
            if img_filename in descriptions_by_filename:
                llm_desc = descriptions_by_filename[img_filename]
                return f"\n\n![Image](*[AI Image Description: {llm_desc}]*)\n\n"
            return match.group(0)

        markdown_image_pattern = re.compile(r"!\[([^\]]*)\]\(([^)]+)\)(?:\{[^}]*\})?")
        final_content = re.sub(
            markdown_image_pattern, replace_image_with_llm, markdown_content
        )

        # 6. Replace OpenXML Chart Placeholders (.docx / .pptx)
        chart_placeholder_pattern = re.compile(
            r"\\\[Graphic:\s*other:\s*http://schemas.openxmlformats.org/drawingml/2006/chart\\\]"
        )
        for chart_md in extracted_chart_tables_list:
            if chart_placeholder_pattern.search(final_content):
                final_content = chart_placeholder_pattern.sub(
                    chart_md, final_content, count=1
                )
            else:
                final_content += f"\n{chart_md}"

        # 7. Replace Pandoc's ODT Object Placeholders (.odt)
        # Matches: []{.image .placeholderoriginal-image-src="./ObjectReplacements/Object 2" ... }
        def replace_odt_object(match):
            obj_src = match.group(1)  # e.g., 'ObjectReplacements/Object 1'
            if obj_src in extracted_odt_charts_map:
                return extracted_odt_charts_map[obj_src]
            return ""  # Clear the placeholder if we failed to parse it

        odt_placeholder_pattern = re.compile(
            r"\[\]\{[^}]*original-image-src=\"\.\/([^\"]+)\"[^}]*\}"
        )
        final_content = re.sub(
            odt_placeholder_pattern, replace_odt_object, final_content
        )

        media_dir = Path(self.media_temp_dir)
        if media_dir.exists():
            shutil.rmtree(media_dir)

        return final_content
