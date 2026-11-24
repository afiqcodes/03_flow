// Restore before the body is painted so page loads do not collapse the sidebar.
const navigationStorageKey = "flow-navigation-open";
try {
    document.documentElement.toggleAttribute(
        "data-nav-open", window.sessionStorage.getItem(navigationStorageKey) === "true"
    );
} catch (_) {
    // Navigation still works when browser storage is unavailable.
}

function setupNavigation() {
    const root = document.documentElement;
    const toggle = document.querySelector("#nav-toggle");
    const navigation = document.querySelector("#side-nav");
    const scrim = document.querySelector("#nav-scrim");

    if (!toggle || !navigation) return;

    const setOpen = (isOpen) => {
        root.toggleAttribute("data-nav-open", isOpen);
        toggle.setAttribute("aria-expanded", String(isOpen));
        toggle.setAttribute(
            "aria-label",
            isOpen ? "Close navigation" : "Open navigation"
        );
        navigation.setAttribute("aria-hidden", String(!isOpen));
        navigation.inert = !isOpen;
        scrim?.setAttribute("aria-hidden", String(!isOpen));
        if (!isOpen && navigation.contains(document.activeElement)) {
            toggle.focus({ preventScroll: true });
        }
        try {
            window.sessionStorage.setItem(navigationStorageKey, String(isOpen));
        } catch (_) {
            // Keep the current page usable without storage access.
        }
    };

    setOpen(root.hasAttribute("data-nav-open"));
    toggle.addEventListener("click", () => {
        setOpen(!root.hasAttribute("data-nav-open"));
    });
    const dismissOnPageInteraction = (event) => {
        if (root.hasAttribute("data-nav-open") &&
            !navigation.contains(event.target) && !toggle.contains(event.target)) {
            setOpen(false);
        }
    };
    document.addEventListener("click", dismissOnPageInteraction);
    document.addEventListener("focusin", dismissOnPageInteraction);
    document.addEventListener("wheel", dismissOnPageInteraction, { passive: true });
    document.addEventListener("touchmove", dismissOnPageInteraction, { passive: true });
    document.addEventListener("keydown", (event) => {
        if (event.key === "Escape") setOpen(false);
    });
    window.addEventListener("pageshow", (event) => {
        if (!event.persisted) return;
        try {
            setOpen(window.sessionStorage.getItem(navigationStorageKey) === "true");
        } catch (_) {
            setOpen(root.hasAttribute("data-nav-open"));
        }
    });
}

function setupDialogs() {
    // Delegation also handles dialogs replaced by an in-place page update.
    document.addEventListener("click", (event) => {
        const opener = event.target.closest("[data-dialog-open]");
        if (opener) {
            document.getElementById(opener.dataset.dialogOpen)?.showModal();
            return;
        }

        const closeButton = event.target.closest("[data-dialog-close]");
        if (closeButton) {
            closeButton.closest("dialog")?.close();
        } else if (event.target.matches("dialog[data-dialog]")) {
            event.target.close();
        }
    });
}

function setupDeleteDialog() {
    const dialog = document.querySelector("#delete-dialog");
    const cancelButton = document.querySelector("#cancel-delete");
    const confirmButton = document.querySelector("#confirm-delete");
    const itemType = document.querySelector("#delete-item-type");
    if (!dialog || !cancelButton || !confirmButton) return;

    let pendingForm = null;
    const cancelDelete = () => {
        pendingForm = null;
        dialog.close();
    };

    document.addEventListener("submit", (event) => {
        const form = event.target.closest(".delete-form");
        if (!form) return;
        event.preventDefault();
        pendingForm = form;
        if (itemType) itemType.textContent = form.dataset.itemType || "task";
        dialog.showModal();
    });

    cancelButton.addEventListener("click", cancelDelete);
    confirmButton.addEventListener("click", () => {
        if (!pendingForm) return;

        const form = pendingForm;
        pendingForm = null;
        dialog.close();
        const confirmed = new Event("confirmed-delete", {
            bubbles: true,
            cancelable: true,
        });
        if (form.dispatchEvent(confirmed)) form.submit();
    });
    dialog.addEventListener("click", (event) => {
        if (event.target === dialog) cancelDelete();
    });
    dialog.addEventListener("cancel", () => {
        pendingForm = null;
    });
}

function setupSaveNotices() {
    const notices = document.querySelectorAll("[data-auto-dismiss]");
    if (!notices.length) return;

    const url = new URL(window.location.href);
    if (url.searchParams.get("saved") === "1") {
        url.searchParams.delete("saved");
        window.history.replaceState(window.history.state, "", url);
    }

    notices.forEach((notice) => {
        const delay = Number(notice.dataset.autoDismiss);
        if (Number.isFinite(delay) && delay > 0) {
            window.setTimeout(() => notice.remove(), delay);
        }
    });
}

function showRequestError(message) {
    document.querySelector("[data-app-request-error]")?.remove();
    const error = document.createElement("p");
    error.className = "upload-error-message";
    error.dataset.appRequestError = "";
    error.setAttribute("role", "alert");
    error.textContent = message;
    document.querySelector(".form-window-content")?.prepend(error);
}

function setupSmoothUpdates() {
    // Tasks already has its own in-place editor and animations.
    if (document.querySelector("#task-form")) return;

    const pagePath = window.location.pathname;
    const reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)");
    let updating = false;

    const swapPage = (page, url, pushHistory = false) => {
        const content = document.querySelector(".content-window > .content");
        const formPanel = document.querySelector(".form-window-content");
        const nextContent = page.querySelector(".content-window > .content");
        const nextFormPanel = page.querySelector(".form-window-content");
        if (!content || !formPanel || !nextContent || !nextFormPanel) {
            throw new Error("Could not refresh this page.");
        }

        const scrollPositions = [".content", ".calendar-list", ".bookmark-list", ".subscription-list", ".workspace-scroll"]
            .map((selector) => [selector, document.querySelector(selector)?.scrollTop || 0]);
        const formScrollTop = formPanel.scrollTop;
        const statsYear = document.querySelector("#budget-stats-year")?.value;
        const openBudgetYears = content.classList.contains("budget-content")
            ? new Set(Array.from(content.querySelectorAll("details.calendar-section[open]"),
                (section) => section.querySelector("summary strong")?.textContent))
            : null;

        document.querySelectorAll(".content-window > dialog[open]").forEach((dialog) => dialog.close());
        document.querySelectorAll(".content-window > dialog, .content-window > template")
            .forEach((element) => element.remove());
        const footer = document.querySelector(".content-window > .statusbar");
        page.querySelectorAll(".content-window > dialog, .content-window > template")
            .forEach((element) => footer.before(document.importNode(element, true)));

        content.replaceWith(document.importNode(nextContent, true));
        formPanel.replaceWith(document.importNode(nextFormPanel, true));
        document.title = page.title;

        for (const [selector, position] of scrollPositions) {
            const element = document.querySelector(selector);
            if (element) element.scrollTop = position;
        }
        document.querySelector(".form-window-content").scrollTop = formScrollTop;
        if (statsYear) {
            const yearSelect = document.querySelector("#budget-stats-year");
            if (yearSelect?.querySelector(`option[value="${statsYear}"]`)) yearSelect.value = statsYear;
        }
        if (openBudgetYears) {
            document.querySelectorAll(".budget-content details.calendar-section").forEach((section) => {
                if (openBudgetYears.has(section.querySelector("summary strong")?.textContent)) {
                    section.open = true;
                }
            });
        }

        // Reinitializers read the current filters and record IDs from the URL.
        if (url) {
            if (pushHistory) window.history.pushState({}, "", url);
            else window.history.replaceState(window.history.state, "", url);
        }
        document.dispatchEvent(new Event("app:content-updated"));
        document.querySelector("#budget-stats-year")?.dispatchEvent(new Event("change"));
        setupSaveNotices();
        if (!reduceMotion.matches) {
            document.querySelector(".content-window > .content").classList.add("app-content-entering");
            document.querySelector(".form-window-content").classList.add("app-content-entering");
        }
    };

    const fetchPage = async (url, options) => {
        const response = await fetch(url, options);
        const page = new DOMParser().parseFromString(await response.text(), "text/html");
        return { response, page };
    };

    const runUpdate = async (operation) => {
        if (updating) return;
        updating = true;
        try {
            await operation();
        } catch (error) {
            showRequestError(error.message || "Could not update this page. Please try again.");
        } finally {
            updating = false;
        }
    };

    const submitForm = async (form, isDelete = false) => {
        const { response, page } = await fetchPage(form.action, {
            method: "POST",
            body: new FormData(form),
            headers: { "X-Requested-With": "XMLHttpRequest" },
        });
        if (response.status === 413) {
            showRequestError(page.querySelector("[role=alert]")?.textContent.trim() || "Upload too large.");
            return;
        }
        if (!response.ok && ![400, 409].includes(response.status)) {
            throw new Error("Could not save your changes. Please try again.");
        }
        if (form.matches(".panel-form") && response.ok &&
            new URL(response.url).searchParams.get("saved") !== "1") {
            throw new Error("Could not save those details. Please check the form.");
        }
        if (isDelete && response.ok && !reduceMotion.matches) {
            const row = form.closest(".bookmark-row, .subscription-row, .month-card, .note-card, .transaction-row");
            if (row) {
                await row.animate([
                    { opacity: 1, transform: "translateY(0)" },
                    { opacity: 0, transform: "translateY(-8px)" },
                ], { duration: 180, easing: "ease-in", fill: "forwards" }).finished;
            }
        }
        let cleanUrl;
        if (response.ok) {
            cleanUrl = new URL(response.url);
            cleanUrl.searchParams.delete("saved");
        }
        swapPage(page, cleanUrl);
    };

    const navigate = async (url, pushHistory = true) => {
        const { response, page } = await fetchPage(url);
        if (!response.ok) throw new Error("Could not open this view. Please try again.");
        swapPage(page, response.url, pushHistory);
    };

    document.addEventListener("submit", (event) => {
        const form = event.target;
        if (!(form instanceof HTMLFormElement) || form.matches(".delete-form, [data-download-form]")) return;
        if (form.method.toLowerCase() === "post") {
            event.preventDefault();
            runUpdate(() => submitForm(form));
        } else if (form.method.toLowerCase() === "get" &&
            new URL(form.action).pathname === pagePath) {
            event.preventDefault();
            const url = new URL(form.action);
            for (const [name, value] of new FormData(form)) url.searchParams.set(name, value);
            runUpdate(() => navigate(url));
        }
    });

    document.addEventListener("confirmed-delete", (event) => {
        const form = event.target;
        if (!(form instanceof HTMLFormElement) || !form.matches(".delete-form")) return;
        event.preventDefault();
        runUpdate(() => submitForm(form, true));
    });

    document.addEventListener("click", (event) => {
        const link = event.target.closest("a[href]");
        if (!link || event.defaultPrevented || event.button !== 0 ||
            event.metaKey || event.ctrlKey || event.shiftKey || event.altKey ||
            link.hasAttribute("download") || link.target) return;
        const url = new URL(link.href);
        if (url.origin !== window.location.origin || url.pathname !== pagePath || url.hash) return;
        event.preventDefault();
        runUpdate(() => navigate(url));
    });

    window.addEventListener("popstate", () => {
        if (updating || window.location.pathname !== pagePath) {
            window.location.reload();
            return;
        }
        runUpdate(() => navigate(window.location.href, false));
    });
}

document.addEventListener("DOMContentLoaded", () => {
    setupNavigation();
    setupDialogs();
    setupDeleteDialog();
    setupSaveNotices();
    setupSmoothUpdates();
});
