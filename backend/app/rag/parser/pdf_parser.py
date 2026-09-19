import logging
from pathlib import Path
from typing import Optional

from docling.datamodel.base_models import InputFormat
from docling.datamodel.pipeline_options import PdfPipelineOptions, RapidOcrOptions
from docling.document_converter import DocumentConverter, PdfFormatOption

from app.rag.parser.image_pipeline import VisionFilePipeline
from app.rag.parser.parser import Parser

logger = logging.getLogger(__name__)


class PdfParser(VisionFilePipeline, Parser):

    def __init__(
        self,
        repo_root: Optional[Path] = None,
        min_dim: int = 120,
        min_pixels: int = 25000,
        max_aspect_ratio: float = 5.0,
        images_scale: float = 2.0,
    ) -> None:
        super().__init__(
            min_dim=min_dim, min_pixels=min_pixels, max_aspect_ratio=max_aspect_ratio
        )

        # Establish output directories at repo root
        self.repo_root = repo_root or self.find_repo_root()
        self.output_dir = self.repo_root / "output"
        self.images_dir = self.output_dir / "images"

        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.images_dir.mkdir(parents=True, exist_ok=True)

        # Configure Docling pipeline
        pipeline_options = PdfPipelineOptions()
        pipeline_options.do_ocr = False
        pipeline_options.generate_picture_images = True
        pipeline_options.images_scale = images_scale
        pipeline_options.ocr_options = RapidOcrOptions(backend="onnxruntime")

        self.converter = DocumentConverter(
            format_options={
                InputFormat.PDF: PdfFormatOption(pipeline_options=pipeline_options)
            }
        )

    def convert_file(self, file_path: Path) -> Path:
        """Converts a PDF file to Markdown with filtered image extractions."""
        try:
            result = self.converter.convert(file_path)
            if result.document is None:
                raise ValueError(
                    f"Docling returned empty document for {file_path.name}"
                )

            raw_markdown = result.document.export_to_markdown()
            md_chunks = raw_markdown.split("<!-- image -->")
            reconstructed_md = [md_chunks[0]]

            valid_img_count = 0
            pictures = result.document.pictures or []

            for i, picture in enumerate(pictures):
                if i >= len(md_chunks) - 1:
                    break

                pil_img = (
                    picture.image.pil_image
                    if (picture.image and picture.image.pil_image)
                    else None
                )

                if pil_img and self._is_meaningful_image(pil_img):
                    valid_img_count += 1
                    img_name = f"{file_path.stem}_img_{valid_img_count}.png"
                    img_path = self.images_dir / img_name

                    # Save image to disk
                    pil_img.save(img_path)

                    # Append relative link to markdown
                    md_image_tag = f"\n\n![{img_name}]({img_path})\n\n"
                    reconstructed_md.append(md_image_tag + md_chunks[i + 1])
                else:
                    reconstructed_md.append(md_chunks[i + 1])

            # Safety fix: Append any remaining text chunks if image count < placeholder count
            if len(pictures) < len(md_chunks) - 1:
                reconstructed_md.extend(md_chunks[len(pictures) + 1 :])

            final_markdown = "".join(reconstructed_md)
            output_file = self.output_dir / f"{file_path.stem}.md"
            output_file.write_text(final_markdown, encoding="utf-8")

            logger.info(
                "Successfully converted %s | Extracted %d images",
                file_path.name,
                valid_img_count,
            )
            return output_file

        except Exception as exc:
            logger.error(
                "Failed to parse PDF %s: %s", file_path.name, exc, exc_info=True
            )
            raise RuntimeError(f"Unable to parse PDF: {file_path.name}") from exc
