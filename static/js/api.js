function setupApiDialogs() {
    document.querySelectorAll(".api-dialog").forEach((dialog) => {
        const form = dialog.querySelector(".api-request-form");
        const submitButton = form?.querySelector('[type="submit"]');
        const status = dialog.querySelector("[data-api-status]");
        const message = dialog.querySelector("[data-api-message]");
        const latency = dialog.querySelector("[data-api-latency]");
        const output = dialog.querySelector("[data-api-response]");
        if (!form || !submitButton || !status || !message || !latency || !output) return;

        const showResponse = (label, detail, data, state, elapsed) => {
            status.textContent = label;
            status.className = `api-response-status is-${state}`;
            message.textContent = detail;
            latency.textContent = elapsed === null ? "—" : `${elapsed} ms`;
            output.textContent = JSON.stringify(data, null, 2);
        };

        form.addEventListener("submit", async (event) => {
            event.preventDefault();
            event.stopPropagation();
            if (submitButton.disabled) return;

            submitButton.disabled = true;
            showResponse("Sending", "Waiting for a response…", {}, "pending", null);
            const started = performance.now();
            try {
                const response = await fetch(form.action, {
                    method: "POST",
                    body: new FormData(form),
                    headers: { "Accept": "application/json" },
                });
                const text = await response.text();
                let data;
                try {
                    data = JSON.parse(text);
                } catch (_) {
                    data = { error: "The service returned a response that is not JSON." };
                }
                showResponse(
                    String(response.status),
                    response.statusText || (response.ok ? "Success" : "Request failed"),
                    data,
                    response.ok ? "success" : "error",
                    Math.round(performance.now() - started),
                );
            } catch (_) {
                showResponse("Network error", "Could not reach the service.",
                    { error: "Check the connection and try again." }, "error",
                    Math.round(performance.now() - started));
            } finally {
                submitButton.disabled = false;
            }
        });
    });
}

document.addEventListener("DOMContentLoaded", setupApiDialogs);
document.addEventListener("app:content-updated", setupApiDialogs);
