let releaseConversion = () => {};

function setupFileFormats(event) {
    releaseConversion();
    const form = document.querySelector("#file-conversion-form");
    if (!form) return;
    if (event?.type === "app:content-updated" && window.matchMedia("(max-width: 1230px)").matches) {
        form.scrollIntoView({ behavior: "auto", block: "start" });
    }

    const input = form.elements.files;
    const conversion = form.elements.conversion.value;
    const list = form.querySelector("[data-conversion-files]");
    const button = form.querySelector('[type="submit"]');
    const status = form.querySelector("[data-conversion-status]");
    const error = document.querySelector("[data-conversion-error]");
    const download = form.querySelector("[data-conversion-download]");
    const controller = new AbortController();
    let imageFiles = Array.from(input.files);
    let downloadUrl;

    releaseConversion = () => {
        controller.abort();
        if (downloadUrl) URL.revokeObjectURL(downloadUrl);
    };

    const renderOrder = () => {
        if (!list) return;
        list.replaceChildren(...imageFiles.map((file, index) => {
            const row = document.createElement("li");
            const name = document.createElement("span");
            name.textContent = `${index + 1}. ${file.name}`;
            row.append(name);
            for (const [direction, symbol, label] of [[-1, "↑", "up"], [1, "↓", "down"]]) {
                const move = document.createElement("button");
                move.type = "button";
                move.textContent = symbol;
                move.setAttribute("aria-label", `Move ${file.name} ${label}`);
                move.disabled = index + direction < 0 || index + direction >= imageFiles.length;
                move.addEventListener("click", () => {
                    const target = index + direction;
                    [imageFiles[index], imageFiles[target]] = [imageFiles[target], imageFiles[index]];
                    renderOrder();
                    list.children[target].querySelector("button:not(:disabled)")?.focus();
                });
                row.append(move);
            }
            return row;
        }));
    };
    input.addEventListener("change", () => {
        imageFiles = Array.from(input.files);
        renderOrder();
    });
    renderOrder();

    form.addEventListener("submit", async (event) => {
        event.preventDefault();
        event.stopPropagation();
        if (button.disabled) return;
        button.disabled = true;
        button.textContent = "converting…";
        error.hidden = true;
        download.hidden = true;
        status.textContent = "Converting your file. Larger documents may take a moment.";
        try {
            const body = new FormData(form);
            if (conversion === "images-to-pdf") {
                body.delete("files");
                imageFiles.forEach((file) => body.append("files", file));
            }
            const response = await fetch(form.action, {
                method: "POST", body, signal: controller.signal,
            });
            if (!response.ok) {
                const page = new DOMParser().parseFromString(await response.text(), "text/html");
                throw new Error(page.querySelector("[data-conversion-error]")?.textContent.trim()
                    || "Could not convert this file. Please try again.");
            }
            const blob = await response.blob();
            if (downloadUrl) URL.revokeObjectURL(downloadUrl);
            downloadUrl = URL.createObjectURL(blob);
            const disposition = response.headers.get("Content-Disposition") || "";
            const filename = disposition.match(/filename="([^"]+)"|filename=([^;]+)/);
            download.href = downloadUrl;
            download.download = filename?.[1] || filename?.[2]?.trim()
                || (conversion === "pdf-to-images" ? "pages.zip" : "converted.pdf");
            download.hidden = false;
            download.click();
            status.textContent = `Ready: ${download.download}. Your download has started.`;
        } catch (failure) {
            if (failure.name === "AbortError") return;
            error.textContent = failure.message || "Could not convert this file. Please try again.";
            error.hidden = false;
            status.textContent = "";
        } finally {
            button.disabled = false;
            button.textContent = "convert & download";
        }
    });
}

document.addEventListener("DOMContentLoaded", setupFileFormats);
document.addEventListener("app:content-updated", setupFileFormats);
window.addEventListener("beforeunload", () => releaseConversion());
