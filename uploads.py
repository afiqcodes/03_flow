"""Shared validation and responses for database-backed file uploads."""

import warnings
from io import BytesIO

from flask import send_file
from PIL import Image, UnidentifiedImageError
from werkzeug.utils import secure_filename

MAX_IMAGE_BYTES = 5 * 1024 * 1024
MAX_IMAGE_PIXELS = 20_000_000
IMAGE_MIME_TYPES = {
    "JPEG": "image/jpeg",
    "PNG": "image/png",
    "GIF": "image/gif",
    "WEBP": "image/webp",
}


def read_limited_upload(upload, max_bytes, error_message):
    """Read only enough bytes to reject an oversized upload."""
    data = upload.read(max_bytes + 1)
    if len(data) > max_bytes:
        raise ValueError(error_message)
    return data


def read_validated_image(upload, label):
    """Read and validate a JPEG, PNG, GIF, or WebP upload."""
    data = read_limited_upload(upload, MAX_IMAGE_BYTES, f"{label} must be 5 MB or smaller.")

    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(BytesIO(data)) as picture:
                image_format = picture.format
                if image_format not in IMAGE_MIME_TYPES:
                    raise ValueError(f"{label} must be JPEG, PNG, GIF, or WebP.")
                if picture.width * picture.height > MAX_IMAGE_PIXELS:
                    raise ValueError(f"{label} must be 20 megapixels or smaller.")
                picture.verify()
            # Verify checks the file structure; decoding catches truncated pixels.
            with Image.open(BytesIO(data)) as picture:
                picture.load()
    except (
        UnidentifiedImageError,
        OSError,
        SyntaxError,
        Image.DecompressionBombError,
        Image.DecompressionBombWarning,
    ) as exc:
        raise ValueError(f"{label} is not a valid JPEG, PNG, GIF, or WebP image.") from exc

    filename = secure_filename(upload.filename)[:200] or f"image.{image_format.lower()}"
    return filename, IMAGE_MIME_TYPES[image_format], data


def send_stored_file(data, filename, mimetype, *, as_attachment=False):
    """Serve database bytes without letting browsers sniff executable content."""
    response = send_file(
        BytesIO(bytes(data)),
        mimetype=mimetype,
        download_name=filename,
        as_attachment=as_attachment,
        max_age=0,
    )
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Cache-Control"] = "private, no-store"
    return response
