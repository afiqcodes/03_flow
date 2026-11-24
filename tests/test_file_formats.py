"""Real image, PDF, and Office conversions plus route validation."""

import re
import shutil
import subprocess
import unittest
from io import BytesIO
from pathlib import Path
from unittest.mock import MagicMock, patch
from zipfile import ZipFile

import pymupdf
from PIL import Image
from werkzeug.datastructures import FileStorage

import app as todo
import file_conversions as conversions


def image_bytes(color="red", size=(100, 200), image_format="PNG", orientation=None):
    output = BytesIO()
    with Image.new("RGBA", size, color) as image:
        if image_format == "JPEG":
            image = image.convert("RGB")
        exif = Image.Exif()
        if orientation is not None:
            exif[274] = orientation
        image.save(output, format=image_format, exif=exif)
    return output.getvalue()


def pdf_bytes(pages=3, password=None):
    with pymupdf.open() as document:
        for number in range(pages):
            page = document.new_page(width=144, height=216)
            page.insert_text((15, 30), f"Page {number + 1}")
        if password:
            return document.tobytes(encryption=pymupdf.PDF_ENCRYPT_AES_256, user_pw=password, owner_pw=password)
        return document.tobytes()


def office_bytes(extension):
    """Small valid documents without adding document-generation dependencies."""
    office_ns = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
    package_ns = "http://schemas.openxmlformats.org/package/2006/relationships"
    types_ns = "http://schemas.openxmlformats.org/package/2006/content-types"
    if extension == ".odt":
        files = {
            "mimetype": "application/vnd.oasis.opendocument.text",
            "META-INF/manifest.xml": '<manifest:manifest xmlns:manifest="urn:oasis:names:tc:opendocument:xmlns:manifest:1.0" manifest:version="1.2"><manifest:file-entry manifest:full-path="/" manifest:media-type="application/vnd.oasis.opendocument.text"/><manifest:file-entry manifest:full-path="content.xml" manifest:media-type="text/xml"/></manifest:manifest>',
            "content.xml": '<office:document-content xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0" xmlns:text="urn:oasis:names:tc:opendocument:xmlns:text:1.0" office:version="1.2"><office:body><office:text><text:p>Conversion sample</text:p></office:text></office:body></office:document-content>',
        }
    else:
        primary = {".docx": "word/document.xml", ".xlsx": "xl/workbook.xml", ".pptx": "ppt/presentation.xml"}[extension]
        media = {".docx": "wordprocessingml.document", ".xlsx": "spreadsheetml.sheet", ".pptx": "presentationml.presentation"}[extension]
        overrides = f'<Override PartName="/{primary}" ContentType="application/vnd.openxmlformats-officedocument.{media}.main+xml"/>'
        files = {
            "_rels/.rels": f'<Relationships xmlns="{package_ns}"><Relationship Id="rId1" Type="{office_ns}/officeDocument" Target="{primary}"/></Relationships>',
        }
        if extension == ".docx":
            files[primary] = '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body><w:p><w:r><w:t>Conversion sample</w:t></w:r></w:p></w:body></w:document>'
        elif extension == ".xlsx":
            files[primary] = f'<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="{office_ns}"><sheets><sheet name="Sample" sheetId="1" r:id="rId1"/></sheets></workbook>'
            files["xl/_rels/workbook.xml.rels"] = f'<Relationships xmlns="{package_ns}"><Relationship Id="rId1" Type="{office_ns}/worksheet" Target="worksheets/sheet1.xml"/></Relationships>'
            files["xl/worksheets/sheet1.xml"] = '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData><row r="1"><c r="A1" t="inlineStr"><is><t>Conversion sample</t></is></c></row></sheetData></worksheet>'
            overrides += '<Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
        else:
            files[primary] = f'<p:presentation xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main" xmlns:r="{office_ns}"><p:sldIdLst><p:sldId id="256" r:id="rId1"/></p:sldIdLst><p:sldSz cx="9144000" cy="6858000"/><p:notesSz cx="6858000" cy="9144000"/></p:presentation>'
            files["ppt/_rels/presentation.xml.rels"] = f'<Relationships xmlns="{package_ns}"><Relationship Id="rId1" Type="{office_ns}/slide" Target="slides/slide1.xml"/></Relationships>'
            files["ppt/slides/slide1.xml"] = '<p:sld xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main" xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"><p:cSld><p:spTree><p:nvGrpSpPr><p:cNvPr id="1" name=""/><p:cNvGrpSpPr/><p:nvPr/></p:nvGrpSpPr><p:grpSpPr/><p:sp><p:nvSpPr><p:cNvPr id="2" name="Title"/><p:cNvSpPr/><p:nvPr/></p:nvSpPr><p:spPr><a:xfrm><a:off x="914400" y="914400"/><a:ext cx="7315200" cy="914400"/></a:xfrm><a:prstGeom prst="rect"><a:avLst/></a:prstGeom></p:spPr><p:txBody><a:bodyPr/><a:lstStyle/><a:p><a:r><a:t>Conversion sample</a:t></a:r></a:p></p:txBody></p:sp></p:spTree></p:cSld></p:sld>'
            overrides += '<Override PartName="/ppt/slides/slide1.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.slide+xml"/>'
        files["[Content_Types].xml"] = f'<Types xmlns="{types_ns}"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/>{overrides}</Types>'
    output = BytesIO()
    with ZipFile(output, "w") as archive:
        for name, value in files.items():
            archive.writestr(name, value)
    return output.getvalue()


def upload(data, filename):
    return FileStorage(stream=BytesIO(data), filename=filename)


class FileFormatTests(unittest.TestCase):
    def setUp(self):
        todo.app.config["TESTING"] = True
        self.client = todo.app.test_client()

    def convert(self, kind, files, **options):
        return self.client.post("/file-formats/convert", data={
            "conversion": kind, "files": files, **options,
        })

    def test_page_and_navigation_render_without_database(self):
        with patch.object(todo, "get_connection") as connect:
            for tool in conversions.CONVERSION_TOOLS:
                response = self.client.get("/file-formats?tool=" + tool)
                self.assertEqual(response.status_code, 200)
                self.assertIn(b"FILE FORMATs", response.data)
                self.assertIn(b'aria-current="page"', response.data)
                self.assertIn(b'data-download-form', response.data)
            connect.assert_not_called()
        self.assertEqual(self.client.get("/file-formats?tool=unknown").status_code, 404)

    def test_combined_pdf_has_ordered_pages_and_safe_download_headers(self):
        response = self.convert("images-to-pdf", [
            (BytesIO(image_bytes("red")), "../red.png"),
            (BytesIO(image_bytes("blue")), "blue.png"),
        ])
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.mimetype, "application/pdf")
        self.assertIn("red.pdf", response.headers["Content-Disposition"])
        self.assertEqual(response.headers["Cache-Control"], "private, no-store")
        self.assertEqual(response.headers["X-Content-Type-Options"], "nosniff")
        with pymupdf.open(stream=response.data, filetype="pdf") as document:
            self.assertEqual(len(document), 2)
            red = document[0].get_pixmap().pixel(10, 10)
            blue = document[1].get_pixmap().pixel(10, 10)
            self.assertGreater(red[0], 200)
            self.assertLess(red[2], 50)
            self.assertGreater(blue[2], 200)
            self.assertLess(blue[0], 50)
        response.close()

    def test_transparency_is_white_and_exif_orientation_is_applied(self):
        data, _, _ = conversions.images_to_pdf([upload(image_bytes((0, 0, 0, 0)), "clear.png")])
        with pymupdf.open(stream=data, filetype="pdf") as document:
            self.assertEqual(document[0].get_pixmap().pixel(10, 10), (255, 255, 255))
        data, _, _ = conversions.images_to_pdf([
            upload(image_bytes(size=(100, 60), image_format="JPEG", orientation=6), "rotated.jpg"),
        ])
        with pymupdf.open(stream=data, filetype="pdf") as document:
            self.assertAlmostEqual(document[0].rect.width, 28.8, places=2)
            self.assertAlmostEqual(document[0].rect.height, 48, places=2)

    def test_bad_images_limits_and_disguised_file_types_are_rejected(self):
        cases = [(b"not an image", "bad.png"), (image_bytes(), "image.gif"),
                 (image_bytes(image_format="WEBP"), "disguised.png")]
        for data, filename in cases:
            with self.subTest(filename=filename):
                response = self.convert("images-to-pdf", (BytesIO(data), filename))
                self.assertEqual(response.status_code, 400)
        with self.assertRaises(ValueError):
            conversions.images_to_pdf([])
        with self.assertRaises(ValueError):
            conversions.images_to_pdf([upload(image_bytes(), "x.png")] * 21)
        with patch.object(conversions, "MAX_TOTAL_IMAGE_PIXELS", 10):
            with self.assertRaises(ValueError):
                conversions.images_to_pdf([upload(image_bytes(), "large.png")])

    def test_pdf_page_range_and_both_image_formats(self):
        for image_format, expected_format in (("png", "PNG"), ("jpg", "JPEG")):
            with self.subTest(image_format=image_format):
                response = self.convert("pdf-to-images", (BytesIO(pdf_bytes()), "sample.pdf"),
                                        image_format=image_format, dpi="72", first_page="2", last_page="3")
                self.assertEqual(response.status_code, 200)
                with ZipFile(BytesIO(response.data)) as archive:
                    self.assertEqual(archive.namelist(), [f"sample-page-002.{image_format}", f"sample-page-003.{image_format}"])
                    with Image.open(BytesIO(archive.read(archive.namelist()[0]))) as image:
                        self.assertEqual(image.format, expected_format)
                        self.assertEqual(image.size, (144, 216))
                response.close()

    def test_invalid_encrypted_and_oversized_pdf_requests(self):
        for data in (b"", b"not a pdf", pdf_bytes(password="secret")):
            response = self.convert("pdf-to-images", (BytesIO(data), "sample.pdf"))
            self.assertEqual(response.status_code, 400)
        for options in ({"dpi": "999"}, {"dpi": "bad"}, {"image_format": "svg"},
                        {"first_page": "0"}, {"first_page": "2", "last_page": "1"},
                        {"last_page": "9"}, {"first_page": "bad"}):
            with self.subTest(options=options):
                response = self.convert("pdf-to-images", (BytesIO(pdf_bytes()), "sample.pdf"), **options)
                self.assertEqual(response.status_code, 400)
        with patch.object(conversions, "MAX_CONVERSION_FILE_BYTES", 10):
            response = self.convert("pdf-to-images", (BytesIO(pdf_bytes()), "big.pdf"))
            self.assertEqual(response.status_code, 400)
        with patch.object(conversions, "MAX_PDF_PAGES", 2):
            response = self.convert("pdf-to-images", (BytesIO(pdf_bytes()), "pages.pdf"))
            self.assertEqual(response.status_code, 400)
        with patch.object(conversions, "MAX_RENDER_PIXELS", 10):
            response = self.convert("pdf-to-images", (BytesIO(pdf_bytes()), "large.pdf"))
            self.assertEqual(response.status_code, 400)

    def test_missing_files_unknown_conversion_and_request_size_errors(self):
        for tool in (*conversions.CONVERSION_TOOLS, "unknown"):
            response = self.client.post("/file-formats/convert", data={"conversion": tool})
            self.assertEqual(response.status_code, 400)
            self.assertIn(b'data-conversion-error', response.data)
        with patch.dict(todo.app.config, MAX_CONTENT_LENGTH=100):
            response = self.convert("images-to-pdf", (BytesIO(b"x" * 1000), "large.png"))
            self.assertEqual(response.status_code, 413)
            self.assertIn(b"55 MB", response.data)
            self.assertNotIn(b"Your log was not saved", response.data)

    def test_office_validation_and_unavailable_converter(self):
        for data, filename in ((b"not office", "file.docx"), (office_bytes(".docx"), "file.xlsx"),
                               (b"text", "file.txt")):
            response = self.convert("office-to-pdf", (BytesIO(data), filename))
            self.assertEqual(response.status_code, 400)
        with patch.object(conversions.shutil, "which", return_value=None):
            response = self.convert("office-to-pdf", (BytesIO(office_bytes(".docx")), "sample.docx"))
            self.assertEqual(response.status_code, 503)
            self.assertIn(b"currently unavailable", response.data)

    def test_office_timeout_stops_process_and_cleans_temporary_files(self):
        process = MagicMock()
        process.pid = 12345
        process.wait.side_effect = [subprocess.TimeoutExpired("libreoffice", 60), None]
        with patch.object(conversions.shutil, "which", return_value="/usr/bin/libreoffice"), \
                patch.object(conversions.subprocess, "Popen") as launch, \
                patch.object(conversions.os, "killpg") as kill:
            launch.return_value.__enter__.return_value = process
            response = self.convert("office-to-pdf", (BytesIO(office_bytes(".docx")), "sample.docx"))
            self.assertEqual(response.status_code, 400)
            self.assertIn(b"too long", response.data)
            kill.assert_called_once()
            source = Path(launch.call_args.args[0][-1])
            self.assertFalse(source.parent.exists())

    def test_output_size_is_bounded(self):
        with patch.object(conversions, "MAX_CONVERSION_OUTPUT_BYTES", 1):
            response = self.convert("images-to-pdf", (BytesIO(image_bytes()), "image.png"))
            self.assertEqual(response.status_code, 400)
            response = self.convert("pdf-to-images", (BytesIO(pdf_bytes()), "sample.pdf"))
            self.assertEqual(response.status_code, 400)

    @unittest.skipUnless(shutil.which("libreoffice") or shutil.which("soffice"), "Requires LibreOffice (included in Docker)")
    def test_real_office_conversions_produce_readable_pdfs(self):
        for extension in (".docx", ".xlsx", ".pptx", ".odt"):
            with self.subTest(extension=extension):
                response = self.convert("office-to-pdf", (BytesIO(office_bytes(extension)), f"sample{extension}"))
                error = re.search(r'data-conversion-error[^>]*>(.*?)</p>', response.get_data(as_text=True)) if response.status_code != 200 else None
                self.assertEqual(response.status_code, 200, error.group(1) if error else "")
                with pymupdf.open(stream=response.data, filetype="pdf") as document:
                    self.assertGreater(len(document), 0)
                    text = "".join(page.get_text() for page in document)
                    self.assertIn("Conversion sample", text)
                response.close()


if __name__ == "__main__":
    unittest.main()
