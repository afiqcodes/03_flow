function setupTasks() {
    const list = document.querySelector(".task-list");
    const form = document.querySelector("#task-form");
    if (!list || !form) return;

    const heading = document.querySelector(".form-window-heading");
    const cancelEdit = document.querySelector("#task-cancel-edit");
    const submitButton = form.querySelector('[type="submit"]');
    const reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)");
    let busy = false;

    const cardFor = (root, id) => root.querySelector(`[data-task-id="${id}"]`);

    const resetForm = () => {
        form.reset();
        form.action = form.dataset.addAction;
        delete form.dataset.editingId;
        form.elements.title.value = "";
        form.elements.description.value = "";
        form.elements.task_type.value = "Others";
        form.elements.due_at.value = "";
        form.elements.due_at.min = form.dataset.minimumDueAt;
        form.elements.priority.value = "Medium";
        form.elements.difficulty.value = "Medium";
        heading.querySelector(".eyebrow").textContent = "tasks / new";
        heading.querySelector("h2").textContent = "Add a task";
        heading.querySelector(".form-description").textContent =
            "Capture one clear action for your task list.";
        submitButton.textContent = "add task";
        cancelEdit.hidden = true;
        const url = new URL(window.location.href);
        url.searchParams.delete("edit");
        window.history.replaceState(window.history.state, "", url);
    };

    const startEditing = (link) => {
        const { editAction, title, description, taskType, dueAt, priority, difficulty } =
            link.dataset;
        const card = link.closest(".task-card");
        form.action = editAction;
        form.dataset.editingId = card.dataset.taskId;
        form.elements.title.value = title;
        form.elements.description.value = description;
        form.elements.task_type.value = taskType;
        form.elements.due_at.removeAttribute("min");
        form.elements.due_at.value = dueAt;
        form.elements.priority.value = priority;
        form.elements.difficulty.value = difficulty;
        heading.querySelector(".eyebrow").textContent = "tasks / edit";
        heading.querySelector("h2").textContent = "Edit task";
        heading.querySelector(".form-description").textContent = "Update the details below.";
        submitButton.textContent = "save changes";
        cancelEdit.hidden = false;
        const url = new URL(window.location.href);
        url.searchParams.set("edit", card.dataset.taskId);
        window.history.replaceState(window.history.state, "", url);
        if (window.matchMedia("(max-width: 1230px)").matches) {
            form.scrollIntoView({ behavior: reduceMotion.matches ? "auto" : "smooth" });
        }
        form.elements.title.focus({ preventScroll: true });
    };

    const postForm = async (submittedForm) => {
        const response = await fetch(submittedForm.action, {
            method: "POST",
            body: new FormData(submittedForm),
            headers: { "X-Requested-With": "XMLHttpRequest" },
        });
        if (!response.ok) {
            throw new Error("Could not update the task.");
        }
        return new DOMParser().parseFromString(await response.text(), "text/html");
    };

    const replaceTaskList = (page, animatedId) => {
        const freshList = page.querySelector(".task-list");
        if (!freshList) throw new Error("Could not refresh tasks. Please reload the page.");
        const expandedIds = new Set(
            Array.from(list.querySelectorAll('[data-task-toggle][aria-expanded="true"]'))
                .map((button) => button.closest(".task-card").dataset.taskId)
        );
        const scrollTop = list.scrollTop;
        list.replaceChildren(...Array.from(freshList.children, (child) =>
            document.importNode(child, true)
        ));
        list.scrollTop = scrollTop;
        for (const id of expandedIds) {
            const button = cardFor(list, id)?.querySelector("[data-task-toggle]");
            if (!button) continue;
            button.setAttribute("aria-expanded", "true");
            button.setAttribute("aria-label", "Hide task details");
            document.getElementById(button.getAttribute("aria-controls")).hidden = false;
        }
        document.querySelector(".heading .item-count").textContent =
            page.querySelector(".heading .item-count").textContent;
        form.dataset.minimumDueAt = page.querySelector("#task-form").dataset.minimumDueAt;
        const card = animatedId && cardFor(list, animatedId);
        if (card && !reduceMotion.matches) card.classList.add("is-entering");
    };

    const animateOut = async (card) => {
        if (!card || reduceMotion.matches) return;
        card.style.overflow = "hidden";
        await card.animate([
            { height: `${card.offsetHeight}px`, opacity: 1, transform: "translateY(0)" },
            { height: "0px", opacity: 0, transform: "translateY(-8px)" },
        ], { duration: 220, easing: "ease-in", fill: "forwards" }).finished;
    };

    const runMutation = async (operation) => {
        if (busy) return;
        busy = true;
        document.querySelector("[data-app-request-error]")?.remove();
        try {
            await operation();
        } catch (error) {
            showRequestError(error.message || "Could not update the task. Please try again.");
        } finally {
            busy = false;
        }
    };

    list.addEventListener("click", (event) => {
        const editLink = event.target.closest("[data-task-edit]");
        if (editLink) {
            event.preventDefault();
            if (!busy) startEditing(editLink);
            return;
        }
        const toggle = event.target.closest("[data-task-toggle]");
        if (!toggle) return;
        const details = document.getElementById(toggle.getAttribute("aria-controls"));
        const isOpen = toggle.getAttribute("aria-expanded") === "true";
        toggle.setAttribute("aria-expanded", String(!isOpen));
        toggle.setAttribute("aria-label", `${isOpen ? "Show" : "Hide"} task details`);
        details.hidden = isOpen;
    });

    list.addEventListener("submit", (event) => {
        if (!event.target.matches(".task-left form")) return;
        event.preventDefault();
        runMutation(async () => {
            const card = event.target.closest(".task-card");
            const page = await postForm(event.target);
            const freshCard = cardFor(page, card.dataset.taskId);
            if (!freshCard) {
                replaceTaskList(page);
                return;
            }
            const done = freshCard.classList.contains("completed");
            card.classList.toggle("completed", done);
            const checkbox = card.querySelector(".checkbox");
            checkbox.textContent = done ? "✓" : "";
            checkbox.setAttribute("aria-pressed", String(done));
            checkbox.setAttribute("aria-label", `${done ? "Mark incomplete" : "Mark complete"}: ${card.querySelector(".task-title").textContent}`);
        });
    });

    list.addEventListener("confirmed-delete", (event) => {
        if (!event.target.matches(".delete-form")) return;
        event.preventDefault();
        runMutation(async () => {
            const card = event.target.closest(".task-card");
            const page = await postForm(event.target);
            await animateOut(card);
            replaceTaskList(page);
            if (form.dataset.editingId === card.dataset.taskId) resetForm();
        });
    });

    form.addEventListener("submit", (event) => {
        event.preventDefault();
        runMutation(async () => {
            const editingId = form.dataset.editingId;
            const oldIds = new Set(
                Array.from(list.querySelectorAll("[data-task-id]"), (card) => card.dataset.taskId)
            );
            const page = await postForm(form);
            const newCard = Array.from(page.querySelectorAll("[data-task-id]"))
                .find((card) => !oldIds.has(card.dataset.taskId));
            if (editingId) await animateOut(cardFor(list, editingId));
            replaceTaskList(page, editingId || newCard?.dataset.taskId);
            resetForm();
        });
    });

    cancelEdit.addEventListener("click", (event) => {
        event.preventDefault();
        if (!busy) resetForm();
    });

    form.elements.title.focus();
}

document.addEventListener("DOMContentLoaded", setupTasks);
