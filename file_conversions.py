"""Local file conversions with bounded uploads and temporary Office profiles."""

import math
import os
import shutil
import signal
import subprocess
from contextlib import ExitStack
from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory
from zipfile import ZIP_DEFLATED, BadZipFile, ZipFile

import pymupdf
from PIL import Image, ImageOps
from werkzeug.utils import secure_filename

from uploads import MAX_IMAGE_PIXELS, read_limited_upload, read_validated_image

MAX_CONVERSION_FILE_BYTES = 20 * 1024 * 1024
MAX_CONVERSION_OUTPUT_BYTES = 50 * 1024 * 1024
MAX_CONVERSION_IMAGES = 20
MAX_TOTAL_IMAGE_PIXELS = 40_000_000
MAX_PDF_PAGES = 50
MAX_RENDER_PIXELS = 80_000_000
OFFICE_TIMEOUT_SECONDS = 60
PDF_DPI_VALUES = (72, 150, 200, 300)
OFFICE_FORMATS = {
    ".docx": "word/document.xml",
    ".xlsx": "xl/workbook.xml",
    ".pptx": "ppt/presentation.xml",
    ".odt": "content.xml",
}
CONVERSION_TOOLS = {
    "images-to-pdf": {
        "title": "Images to PDF",
        "input": "JPG / PNG",
        "output": "PDF",
        "description": "Turn a scan into a PDF, or combine several images into one document.",
        "accept": ".jpg,.jpeg,.png,image/jpeg,image/png",
    },
    "pdf-to-images": {
        "title": "PDF to images",
        "input": "PDF",
        "output": "PNG / JPG",
        "description": "Export each page as an image and download the selected pages in a ZIP.",
        "accept": ".pdf,application/pdf",
    },
    "office-to-pdf": {
        "title": "Office to PDF",
        "input": "DOCX / XLSX / PPTX / ODT",
        "output": "PDF",
        "description": "Create a PDF from a document, spreadsheet, or presentation.",
        "accept": ".docx,.xlsx,.pptx,.odt",
    },
}


class ConversionUnavailable(RuntimeError):
    """A required local conversion tool is unavailable."""


def output_stem(filename):
    return Path(secure_filename(filename or "file")).stem[:80] or "file"


def check_output_size(size):
    if size > MAX_CONVERSION_OUTPUT_BYTES:
        raise ValueError("The result exceeds 50 MB. Convert fewer images or pages, or choose a lower resolution.")


def images_to_pdf(uploads):
    """Preserve selection order, correct orientation, and flatten transparency onto white."""
    if not 1 <= len(uploads) <= MAX_CONVERSION_IMAGES:
        raise ValueError("Choose between 1 and 20 JPG or PNG images.")
    with ExitStack() as stack:
        pages = []
        total_pixels = 0
        for upload in uploads:
            if Path(upload.filename).suffix.lower() not in {".jpg", ".jpeg", ".png"}:
                raise ValueError("Choose JPG or PNG images only.")
            _, mime_type, data = read_validated_image(upload, "Each image")
            if mime_type not in {"image/jpeg", "image/png"}:
                raise ValueError("Choose JPG or PNG images only.")
            original = stack.enter_context(Image.open(BytesIO(data)))
            total_pixels += original.width * original.height
            if total_pixels > MAX_TOTAL_IMAGE_PIXELS:
                raise ValueError("Images must total 40 megapixels or fewer. Resize them or convert fewer at once.")
            oriented = stack.enter_context(ImageOps.exif_transpose(original))
            rgba = stack.enter_context(oriented.convert("RGBA"))
            page = stack.enter_context(Image.new("RGB", rgba.size, "white"))
            mask = stack.enter_context(rgba.getchannel("A"))
            page.paste(rgba, mask=mask)
            pages.append(page)
        output = BytesIO()
        pages[0].save(output, format="PDF", save_all=True, append_images=pages[1:], resolution=150)
        check_output_size(output.tell())
        return output.getvalue(), f"{output_stem(uploads[0].filename)}.pdf", "application/pdf"


def open_pdf(data):
    try:
        document = pymupdf.open(stream=data, filetype="pdf")
    except (pymupdf.FileDataError, RuntimeError) as exc:
        raise ValueError("Choose a valid PDF file.") from exc
    if not document.is_pdf or document.needs_pass or document.page_count == 0:
        document.close()
        raise ValueError("Choose a PDF with pages and remove any password protection first.")
    return document


def pdf_to_images(upload, image_format="png", dpi=150, first_page=1, last_page=None):
    """Render a bounded page range into an archive, one image per page."""
    if Path(upload.filename).suffix.lower() != ".pdf":
        raise ValueError("Choose a PDF file.")
    if image_format not in {"png", "jpg"} or dpi not in PDF_DPI_VALUES:
        raise ValueError("Choose PNG or JPG and a supported resolution.")
    data = read_limited_upload(upload, MAX_CONVERSION_FILE_BYTES, "The PDF must be 20 MB or smaller.")
    with open_pdf(data) as document:
        end = document.page_count if last_page is None else last_page
        if not 1 <= first_page <= end <= document.page_count:
            raise ValueError(f"Choose a page range between 1 and {document.page_count}.")
        if end - first_page + 1 > MAX_PDF_PAGES:
            raise ValueError("Convert up to 50 pages at a time. Choose a first and last page.")
        total_pixels = 0
        for number in range(first_page - 1, end):
            rect = document[number].rect
            pixels = math.ceil(rect.width * dpi / 72) * math.ceil(rect.height * dpi / 72)
            total_pixels += pixels
            if pixels > MAX_IMAGE_PIXELS or total_pixels > MAX_RENDER_PIXELS:
                raise ValueError("These pages are too large at this resolution. Choose fewer pages or a lower DPI.")
        output = BytesIO()
        stem = output_stem(upload.filename)
        with ZipFile(output, "w", compression=ZIP_DEFLATED) as archive:
            for number in range(first_page - 1, end):
                page = document[number]
                try:
                    image = page.get_pixmap(dpi=dpi, colorspace=pymupdf.csRGB, alpha=False)
                    image_data = image.tobytes(image_format)
                except RuntimeError as exc:
                    raise ValueError("A PDF page could not be rendered. Try exporting a fresh copy of the PDF.") from exc
                archive.writestr(f"{stem}-page-{number + 1:03d}.{image_format}", image_data)
                check_output_size(output.tell())
        check_output_size(output.tell())
        return output.getvalue(), f"{stem}-pages.zip", "application/zip"


def validate_office_file(upload):
    extension = Path(upload.filename).suffix.lower()
    if extension not in OFFICE_FORMATS:
        raise ValueError("Choose a DOCX, XLSX, PPTX, or ODT file.")
    data = read_limited_upload(upload, MAX_CONVERSION_FILE_BYTES, "The document must be 20 MB or smaller.")
    try:
        with ZipFile(BytesIO(data)) as archive:
            entries = archive.infolist()
            if len(entries) > 5000 or sum(entry.file_size for entry in entries) > 100 * 1024 * 1024:
                raise ValueError("This document is too large when expanded. Choose a smaller document.")
            names = set(archive.namelist())
            if OFFICE_FORMATS[extension] not in names:
                raise ValueError("The document contents do not match its file format.")
            if any(entry.flag_bits & 1 for entry in entries):
                raise ValueError("Remove password protection before converting this document.")
            if extension == ".odt":
                if archive.read("mimetype") != b"application/vnd.oasis.opendocument.text":
                    raise ValueError("Choose a valid ODT document.")
            elif "[Content_Types].xml" not in names:
                raise ValueError("Choose a valid Office document.")
    except (BadZipFile, KeyError, RuntimeError, NotImplementedError) as exc:
        raise ValueError("Choose a valid, unencrypted Office document.") from exc
    return data, extension


def office_to_pdf(upload):
    """Use an isolated LibreOffice process and remove all intermediate files afterward."""
    data, extension = validate_office_file(upload)
    executable = shutil.which("libreoffice") or shutil.which("soffice")
    if executable is None:
        raise ConversionUnavailable("Office conversion is currently unavailable. Please try again later.")
    with TemporaryDirectory(prefix="flow-convert-") as directory:
        root = Path(directory)
        source = root / f"input{extension}"
        source.write_bytes(data)
        destination = root / "output"
        destination.mkdir()
        profile = root / "profile"
        (profile / "user").mkdir(parents=True)
        (profile / "user" / "registrymodifications.xcu").write_text(
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<oor:items xmlns:oor="http://openoffice.org/2001/registry">'
            '<item oor:path="/org.openoffice.Office.Common/Security/Scripting">'
            '<prop oor:name="MacroSecurityLevel" oor:op="fuse"><value>3</value></prop>'
            '</item></oor:items>', encoding="utf-8",
        )
        try:
            with subprocess.Popen(
                [executable, f"-env:UserInstallation={profile.as_uri()}", "--headless",
                 "--convert-to", "pdf", "--outdir", str(destination), str(source)],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True,
            ) as process:
                try:
                    return_code = process.wait(timeout=OFFICE_TIMEOUT_SECONDS)
                except subprocess.TimeoutExpired as exc:
                    os.killpg(process.pid, signal.SIGKILL)
                    process.wait()
                    raise ValueError("This document took too long to convert. Try a smaller or simpler document.") from exc
        except OSError as exc:
            raise ConversionUnavailable("Office conversion is currently unavailable. Please try again later.") from exc
        result = destination / "input.pdf"
        if return_code != 0 or not result.is_file():
            raise ValueError("This document could not be converted. Check that it opens correctly and is not password protected.")
        check_output_size(result.stat().st_size)
        converted = result.read_bytes()
        with open_pdf(converted):
            pass
        return converted, f"{output_stem(upload.filename)}.pdf", "application/pdf"
