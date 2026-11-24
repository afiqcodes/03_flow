/* Browser interaction regressions using Node's built-in test runner. */
const assert = require("node:assert/strict");
const { readFileSync } = require("node:fs");
const { test } = require("node:test");
const vm = require("node:vm");

function element() {
    return {
        listeners: {},
        dataset: {},
        classList: { contains: () => false, add() {} },
        scrollTop: 0,
        addEventListener(type, listener) { this.listeners[type] = listener; },
        querySelectorAll: () => [],
        replaceWith() {},
        removeAttribute() {},
        scrollIntoView() {},
        focus() {},
    };
}

function browser(url) {
    const window = {
        location: new URL(url),
        matchMedia: () => ({ matches: true }),
        setTimeout() {},
        addEventListener() {},
    };
    const history = [];
    const update = (method) => (state, title, nextUrl) => {
        window.location = new URL(nextUrl, window.location);
        history.push({ method, url: window.location.href });
    };
    window.history = { state: {}, replaceState: update("replace"), pushState: update("push") };
    return { window, history };
}

function loadScript(filename, globals) {
    const context = vm.createContext({ URL, Event, ...globals });
    vm.runInContext(readFileSync(`${__dirname}/../static/js/${filename}`, "utf8"), context);
    return context;
}

function navigationBrowser(storage = new Map()) {
    const { window } = browser("http://localhost/notes");
    const node = () => ({
        ...element(),
        attributes: new Map(),
        setAttribute(name, value) { this.attributes.set(name, value); },
        hasAttribute(name) { return this.attributes.has(name); },
        toggleAttribute(name, force) {
            if (force) this.attributes.set(name, "");
            else this.attributes.delete(name);
        },
        contains(target) { return target === this || target?.parent === this; },
    });
    const root = node();
    const toggle = node();
    const navigation = node();
    const scrim = node();
    const listeners = {};
    const windowListeners = {};
    window.addEventListener = (name, listener) => { windowListeners[name] = listener; };
    window.sessionStorage = {
        getItem: (key) => storage.get(key) ?? null,
        setItem: (key, value) => storage.set(key, value),
    };
    const nodes = { "#nav-toggle": toggle, "#side-nav": navigation, "#nav-scrim": scrim };
    const document = {
        documentElement: root,
        querySelector: (selector) => nodes[selector],
        addEventListener: (name, listener) => { listeners[name] = listener; },
    };
    toggle.focus = () => { document.activeElement = toggle; };
    const context = loadScript("app.js", { window, document });
    return { root, toggle, navigation, scrim, document, listeners, windowListeners, storage,
        start: () => vm.runInContext("setupNavigation()", context) };
}

test("an open sidebar is restored before page setup and stays open across navigation", () => {
    const first = navigationBrowser();
    first.start();
    assert.equal(first.navigation.inert, true);
    first.toggle.listeners.click();
    assert.equal(first.root.hasAttribute("data-nav-open"), true);
    assert.equal(first.toggle.attributes.get("aria-expanded"), "true");
    assert.equal(first.navigation.attributes.get("aria-hidden"), "false");
    assert.equal(first.navigation.inert, false);

    const link = { parent: first.navigation };
    first.listeners.click({ target: link });
    assert.equal(first.root.hasAttribute("data-nav-open"), true);
    const next = navigationBrowser(first.storage);
    assert.equal(next.root.hasAttribute("data-nav-open"), true, "restored before DOMContentLoaded");
    next.start();
    assert.equal(next.toggle.attributes.get("aria-label"), "Close navigation");
    assert.equal(next.navigation.inert, false);

    next.listeners.click({ target: next.scrim });
    assert.equal(next.root.hasAttribute("data-nav-open"), false);
    assert.equal(next.navigation.inert, true);
    assert.equal(next.scrim.attributes.get("aria-hidden"), "true");
    assert.equal(navigationBrowser(next.storage).root.hasAttribute("data-nav-open"), false);
});

test("page interaction dismisses the sidebar while interaction inside it keeps it open", () => {
    for (const interaction of ["click", "focusin", "wheel", "touchmove"]) {
        const page = navigationBrowser();
        page.start();
        page.toggle.listeners.click();
        page.listeners[interaction]({ target: { parent: page.navigation } });
        assert.equal(page.root.hasAttribute("data-nav-open"), true, interaction);
        page.listeners[interaction]({ target: page.toggle });
        assert.equal(page.root.hasAttribute("data-nav-open"), true, interaction);
        page.listeners[interaction]({ target: {} });
        assert.equal(page.root.hasAttribute("data-nav-open"), false, interaction);
    }
});

test("logo and Escape close navigation and return focus from hidden links", () => {
    const page = navigationBrowser();
    page.start();
    page.toggle.listeners.click();
    page.toggle.listeners.click();
    assert.equal(page.toggle.attributes.get("aria-expanded"), "false");
    page.toggle.listeners.click();
    page.document.activeElement = { parent: page.navigation };
    page.listeners.keydown({ key: "Escape" });
    assert.equal(page.root.hasAttribute("data-nav-open"), false);
    assert.equal(page.document.activeElement, page.toggle);
});

test("back/forward cache restores the most recent sidebar choice", () => {
    const page = navigationBrowser();
    page.start();
    page.toggle.listeners.click();
    const next = navigationBrowser(page.storage);
    next.start();
    next.listeners.click({ target: next.scrim });
    page.windowListeners.pageshow({ persisted: true });
    assert.equal(page.root.hasAttribute("data-nav-open"), false);
    assert.equal(page.navigation.inert, true);
});

test("sidebar remains usable when browser storage is blocked", () => {
    const storage = { get() { throw new Error("Storage blocked"); },
        set() { throw new Error("Storage blocked"); } };
    const page = navigationBrowser(storage);
    page.start();
    page.toggle.listeners.click();
    assert.equal(page.root.hasAttribute("data-nav-open"), true);
    page.windowListeners.pageshow({ persisted: true });
    assert.equal(page.root.hasAttribute("data-nav-open"), true);
    page.listeners.click({ target: page.scrim });
    assert.equal(page.root.hasAttribute("data-nav-open"), false);
});

test("task editing and cancellation keep the reload URL consistent with the form", () => {
    const { window } = browser("http://localhost/?edit=7");
    const list = element();
    const cancel = element();
    const form = element();
    form.reset = () => {};
    form.dataset = { addAction: "/add", editingId: "7", minimumDueAt: "2026-11-04T10:00" };
    form.elements = Object.fromEntries(
        ["title", "description", "task_type", "due_at", "priority", "difficulty"].map((key) => [key, element()])
    );
    const heading = { querySelector: () => element() };
    form.querySelector = () => element();
    const nodes = { ".task-list": list, "#task-form": form,
        "#task-cancel-edit": cancel, ".form-window-heading": heading };
    const document = { querySelector: (selector) => nodes[selector], addEventListener() {} };
    const context = loadScript("tasks.js", { window, document });
    vm.runInContext("setupTasks()", context);

    cancel.listeners.click({ preventDefault() {} });
    assert.equal(window.location.search, "");
    assert.equal(form.action, "/add");
    assert.equal(form.dataset.editingId, undefined);

    const link = { dataset: { editAction: "/tasks/edit/8", title: "Task", description: "Details",
        taskType: "Work", dueAt: "2026-11-05T10:00", priority: "High", difficulty: "Easy" },
    closest: () => ({ dataset: { taskId: "8" } }) };
    list.listeners.click({ target: { closest: () => link }, preventDefault() {} });
    assert.equal(window.location.search, "?edit=8");
    assert.equal(form.action, "/tasks/edit/8");
    assert.equal(form.elements.title.value, "Task");

    cancel.listeners.click({ preventDefault() {} });
    assert.equal(window.location.search, "");
    assert.equal(form.elements.title.value, "");
});

test("in-place navigation updates history before page events and removes save flags", async () => {
    const { window, history } = browser("http://localhost/notes?q=old");
    const content = element();
    const formPanel = element();
    const listeners = {};
    const notices = [{ dataset: { autoDismiss: "3000" } }];
    let updatedUrl;
    const errors = [];
    const nodes = { ".content-window > .content": content, ".form-window-content": formPanel };
    const document = {
        querySelector: (selector) => nodes[selector],
        querySelectorAll: (selector) => selector === "[data-auto-dismiss]" ? notices : [],
        addEventListener(type, listener) { listeners[type] = listener; },
        importNode: (node) => node,
        dispatchEvent() { updatedUrl = window.location.href; },
    };
    const page = { title: "Notes", querySelector: document.querySelector, querySelectorAll: () => [] };
    const context = loadScript("app.js", {
        window, document, errors,
        fetch: async (url) => ({ ok: true, url: String(url), text: async () => "" }),
        DOMParser: class { parseFromString() { return page; } },
    });
    vm.runInContext("showRequestError = (message) => errors.push(message); setupSmoothUpdates()", context);
    const link = { href: "http://localhost/notes?q=new&saved=1", hasAttribute: () => false };
    listeners.click({ target: { closest: () => link }, button: 0, preventDefault() {} });
    await new Promise(setImmediate);

    assert.deepEqual(errors, []);
    assert.equal(updatedUrl, "http://localhost/notes?q=new&saved=1");
    assert.equal(window.location.href, "http://localhost/notes?q=new");
    assert.deepEqual(history.map((entry) => entry.method), ["push", "replace"]);
});
