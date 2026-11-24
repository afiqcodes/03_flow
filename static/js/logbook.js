function logbookFileDetails(picture) {
    const format = picture.mime_type?.split("/")[1]?.toUpperCase() || "Image";
    const bytes = picture.size_bytes;
    if (!Number.isFinite(bytes)) return `${format} image`;
    const size = bytes >= 1024 * 1024
        ? `${(bytes / (1024 * 1024)).toFixed(1)} MB`
        : `${Math.max(1, Math.round(bytes / 1024))} KB`;
    return `${format} · ${size}`;
}

function createLogbookFile(picture, templateId) {
    const template = document.querySelector(templateId);
    const item = template.content.firstElementChild.cloneNode(true);
    item.querySelector("[data-filename]").textContent = picture.filename;
    item.querySelector("[data-file-detail]").textContent = logbookFileDetails(picture);
    return item;
}

function createLogbookImage(picture) {
    const figure = createLogbookFile(picture, "#logbook-picture-template");
    const image = figure.querySelector("img");
    image.src = picture.url;
    image.alt = picture.filename;

    const download = figure.querySelector("a");
    download.href = picture.download_url;
    download.download = picture.filename;
    download.setAttribute("aria-label", `Download ${picture.filename}`);
    return figure;
}

function setupLogbookDialog() {
    const dialog = document.querySelector("#logbook-dialog");
    if (!dialog) return;

    const title = dialog.querySelector("#logbook-dialog-title");
    const dateLabel = dialog.querySelector("#logbook-dialog-date");
    const status = dialog.querySelector("#logbook-dialog-status");
    const details = dialog.querySelector("#logbook-dialog-details");
    const gallery = dialog.querySelector("#logbook-dialog-images");
    const edit = dialog.querySelector("#logbook-dialog-edit");
    const editLabel = dialog.querySelector("#logbook-edit-label");
    const meta = dialog.querySelector("#logbook-dialog-meta");
    const sidebarDate = dialog.querySelector("#logbook-sidebar-date");
    const sidebarType = dialog.querySelector("#logbook-sidebar-type");
    const sidebarLocation = dialog.querySelector("#logbook-sidebar-location");
    const categories = dialog.querySelector("#logbook-sidebar-categories");
    const attachments = dialog.querySelector("#logbook-sidebar-attachments");
    const attachmentList = dialog.querySelector("#logbook-attachment-list");
    const pictureCount = dialog.querySelector("#logbook-picture-count");
    const noPictures = dialog.querySelector("#logbook-no-pictures");
    const noAttachments = dialog.querySelector("#logbook-no-attachments");
    const type = dialog.querySelector("#logbook-dialog-type");
    const location = dialog.querySelector("#logbook-dialog-location");
    const description = dialog.querySelector("#logbook-dialog-description");
    let controller;

    const renderEntry = (entry, createUrl) => {
        edit.hidden = false;
        if (!entry) {
            title.textContent = "A fresh page";
            status.textContent = "No log for this day yet. Capture your work, a memory, or a moment for yourself.";
            editLabel.textContent = "Write a log";
            edit.href = createUrl;
            return;
        }

        title.textContent = entry.title;
        type.textContent = entry.day_type;
        type.className = `day-type day-type-${entry.day_type.toLowerCase()}`;
        sidebarType.textContent = entry.day_type;
        sidebarType.className = type.className;
        location.textContent = entry.location;
        sidebarLocation.textContent = entry.location;
        description.textContent = entry.description;
        gallery.replaceChildren(...entry.images.map(createLogbookImage));
        attachmentList.replaceChildren(...entry.images.map((picture) =>
            createLogbookFile(picture, "#logbook-attachment-template")
        ));
        pictureCount.textContent = `(${entry.images.length})`;
        noPictures.hidden = entry.images.length > 0;
        noAttachments.hidden = entry.images.length > 0;
        meta.hidden = false;
        categories.hidden = false;
        attachments.hidden = false;
        editLabel.textContent = "Edit log";
        edit.href = entry.edit_url;
        status.hidden = true;
        details.hidden = false;
    };

    const showDay = async (button) => {
        controller?.abort();
        controller = new AbortController();
        title.textContent = "Daily log";
        dateLabel.textContent = new Date(`${button.dataset.logbookDay}T12:00:00`)
            .toLocaleDateString(undefined, {
                weekday: "long",
                day: "numeric",
                month: "long",
                year: "numeric",
            });
        sidebarDate.textContent = dateLabel.textContent;
        dateLabel.dateTime = button.dataset.logbookDay;
        sidebarDate.dateTime = button.dataset.logbookDay;
        meta.hidden = true;
        categories.hidden = true;
        attachments.hidden = true;
        details.hidden = true;
        edit.hidden = true;
        status.hidden = false;
        status.textContent = "Loading log…";
        gallery.replaceChildren();
        attachmentList.replaceChildren();
        dialog.showModal();
        dialog.querySelector(".logbook-dialog-main").scrollTop = 0;
        dialog.querySelector(".logbook-dialog-sidebar").scrollTop = 0;
        dialog.scrollTop = 0;

        try {
            const response = await fetch(button.dataset.dayUrl, {
                signal: controller.signal,
            });
            if (!response.ok) throw new Error("Unable to load log");
            const { entry } = await response.json();
            renderEntry(entry, button.dataset.createUrl);
        } catch (error) {
            if (error.name !== "AbortError") {
                status.textContent = "Could not load this log. Close this window and try again.";
            }
        }
    };

    dialog.querySelector("#logbook-dialog-close").addEventListener("click", () => {
        dialog.close();
    });
    dialog.addEventListener("click", (event) => {
        if (event.target !== dialog) return;
        const rect = dialog.getBoundingClientRect();
        const outside = event.clientX < rect.left || event.clientX > rect.right ||
            event.clientY < rect.top || event.clientY > rect.bottom;
        if (outside) dialog.close();
    });
    dialog.addEventListener("close", () => controller?.abort());
    document.querySelectorAll("[data-logbook-day]").forEach((button) => {
        button.addEventListener("click", () => showDay(button));
    });
}

let releaseLogbookPreviews = () => {};

function setupLogbookUploads() {
    const form = document.querySelector("#logbook-form");
    if (!form) return;

    releaseLogbookPreviews();

    const uploads = form.querySelector("#logbook-images");
    const previews = form.querySelector("#logbook-upload-previews");
    const status = form.querySelector("#logbook-upload-status");
    const maxImages = Number(uploads.dataset.maxImages);
    const maxBytes = Number(uploads.dataset.maxBytes);
    let previewUrls = [];

    releaseLogbookPreviews = () => {
        previewUrls.forEach((url) => URL.revokeObjectURL(url));
        previewUrls = [];
    };

    const updateUploads = () => {
        releaseLogbookPreviews();
        previews.replaceChildren();

        const files = Array.from(uploads.files);
        const retained = form.querySelectorAll('input[name="remove_images"]:not(:checked)').length;
        let error = "";
        if (files.length + retained > maxImages) {
            error = `An entry can have up to ${maxImages} images.`;
        } else if (files.some((file) => file.size > maxBytes)) {
            error = `Each image must be ${maxBytes / (1024 * 1024)} MB or smaller.`;
        }
        uploads.setCustomValidity(error);
        status.textContent = error;
        if (error || !files.length) return;

        status.textContent = `${files.length} new image${files.length === 1 ? "" : "s"} selected`;
        files.forEach((file) => {
            const image = document.createElement("img");
            const url = URL.createObjectURL(file);
            previewUrls.push(url);
            image.src = url;
            image.alt = file.name;
            previews.append(image);
        });
    };

    uploads.addEventListener("change", updateUploads);
    form.querySelectorAll('input[name="remove_images"]').forEach((checkbox) => {
        checkbox.addEventListener("change", updateUploads);
    });
}

function setupLogbookYearPicker() {
    document.querySelector("#logbook-year")?.addEventListener("change", (event) => {
        event.target.form.requestSubmit();
    });
}

function setupLogbook() {
    setupLogbookYearPicker();
    setupLogbookDialog();
    setupLogbookUploads();
}

document.addEventListener("DOMContentLoaded", setupLogbook);
document.addEventListener("app:content-updated", setupLogbook);
