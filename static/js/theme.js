/* The selected color drives both the light and dark interface palettes. */
(() => {
    const colorStorageKey = "todo-background-color";
    const modeStorageKey = "todo-color-mode";
    const defaultColor = "#e9e9ec";
    const root = document.documentElement;
    let selectedColor = defaultColor;
    let mode = "light";
    let hasCustomColor = false;

    const mix = (first, second, amount) => first.map((value, index) =>
        Math.round(value * (1 - amount) + second[index] * amount));
    const hex = (channels) => `#${channels.map((value) => value.toString(16).padStart(2, "0")).join("")}`;
    const luminance = (channels) => {
        const linear = channels.map((value) => {
            const channel = value / 255;
            return channel <= 0.04045 ? channel / 12.92 : ((channel + 0.055) / 1.055) ** 2.4;
        });
        return linear[0] * 0.2126 + linear[1] * 0.7152 + linear[2] * 0.0722;
    };
    const contrast = (first, second) => {
        const values = [luminance(first), luminance(second)].sort((a, b) => b - a);
        return (values[0] + 0.05) / (values[1] + 0.05);
    };

    const toHsl = ([red, green, blue]) => {
        const [r, g, b] = [red, green, blue].map((value) => value / 255);
        const max = Math.max(r, g, b);
        const min = Math.min(r, g, b);
        const difference = max - min;
        const lightness = (max + min) / 2;
        if (!difference) return [0, 0, lightness];
        const saturation = difference / (1 - Math.abs(2 * lightness - 1));
        let hue;
        if (max === r) hue = ((g - b) / difference) % 6;
        else if (max === g) hue = (b - r) / difference + 2;
        else hue = (r - g) / difference + 4;
        return [((hue * 60) + 360) % 360, saturation, lightness];
    };

    const fromHsl = (hue, saturation, lightness) => {
        const chroma = (1 - Math.abs(2 * lightness - 1)) * saturation;
        const portion = hue / 60;
        const second = chroma * (1 - Math.abs(portion % 2 - 1));
        const pairs = [[chroma, second, 0], [second, chroma, 0], [0, chroma, second],
            [0, second, chroma], [second, 0, chroma], [chroma, 0, second]];
        const offset = lightness - chroma / 2;
        return pairs[Math.floor(portion) % 6].map((value) => Math.round((value + offset) * 255));
    };

    const applyTheme = (color, colorMode) => {
        if (!/^#[0-9a-f]{6}$/i.test(color)) return;
        const selected = [1, 3, 5].map((index) => parseInt(color.slice(index, index + 2), 16));
        const [hue, saturation, lightness] = toHsl(selected);
        const dark = colorMode === "dark";
        const background = fromHsl(hue, saturation, dark
            ? Math.min(lightness, 0.18) : Math.max(lightness, 0.78));
        const switchFill = fromHsl(hue, saturation, dark
            ? Math.min(Math.max(lightness, 0.16), 0.28)
            : Math.max(Math.min(lightness, 0.84), 0.72));
        const tint = fromHsl(hue, Math.min(0.38, saturation * 0.55), dark ? 0.38 : 0.72);
        const neutral = saturation < 0.08;
        const accentSaturation = neutral ? 0 : Math.max(0.45, Math.min(0.7, saturation));
        const accentText = dark ? [22, 24, 28] : [255, 255, 255];
        const palette = dark ? {
            window: mix([22, 24, 28], tint, 0.16),
            surface: mix([30, 32, 37], tint, 0.15),
            raised: mix([35, 37, 43], tint, 0.15),
            soft: mix([40, 42, 48], tint, 0.18),
            muted: mix([48, 51, 58], tint, 0.22),
            hover: mix([57, 61, 68], tint, 0.20),
            border: mix([79, 83, 92], tint, 0.16),
            text: mix([246, 247, 249], tint, 0.03),
            secondary: mix([211, 214, 220], tint, 0.04),
            quiet: mix([177, 182, 191], tint, 0.07),
        } : {
            window: mix([255, 255, 255], tint, 0.07),
            surface: mix([255, 255, 255], tint, 0.12),
            raised: mix([255, 255, 255], tint, 0.04),
            soft: mix([255, 255, 255], tint, 0.19),
            muted: mix([246, 247, 249], tint, 0.24),
            hover: mix([239, 241, 244], tint, 0.28),
            border: mix([200, 203, 210], tint, 0.13),
            text: mix([27, 29, 33], tint, 0.04),
            secondary: mix([75, 78, 84], tint, 0.06),
            quiet: mix([96, 100, 108], tint, 0.08),
        };
        let accentLightness = dark ? 0.68 : 0.38;
        let accent = fromHsl(hue, accentSaturation, accentLightness);
        while (contrast(accent, accentText) < 4.5 || contrast(accent, palette.window) < 4.5) {
            accentLightness += dark ? 0.01 : -0.01;
            accent = fromHsl(hue, accentSaturation, accentLightness);
        }

        // Keep the chosen color visible on task icons, even with a very dark or pale background.
        let iconSurface = palette.raised;
        const iconSurfaceTarget = contrast(selected, [255, 255, 255]) > contrast(selected, [0, 0, 0])
            ? [255, 255, 255] : [0, 0, 0];
        for (let step = 1; step <= 20 && contrast(selected, iconSurface) < 4.5; step++) {
            iconSurface = mix(palette.raised, iconSurfaceTarget, step / 20);
        }

        // Neutral backgrounds need the opposite shade for calendar dates to stand out.
        const calendarHighlight = neutral ? (dark ? [255, 255, 255] : [0, 0, 0]) : selected;
        const calendarHighlightText = contrast(calendarHighlight, [255, 255, 255]) >=
            contrast(calendarHighlight, [0, 0, 0]) ? "#ffffff" : "#000000";
        const lightSwitchIcon = contrast(switchFill, [255, 255, 255]) >= contrast(switchFill, [0, 0, 0]);

        root.dataset.theme = dark ? "dark" : "light";
        root.toggleAttribute("data-custom-color", hasCustomColor);
        root.style.setProperty("--app-background-color", hex(background));
        root.style.setProperty("--selected-background-color", color);
        root.style.setProperty("--theme-switch-fill", hex(switchFill));
        root.style.setProperty("--theme-on-switch-fill", lightSwitchIcon ? "#ffffff" : "#1d1d1f");
        root.style.setProperty("--theme-switch-icon-filter", lightSwitchIcon ? "invert(1)" : "none");
        root.style.setProperty("--calendar-highlight", hex(calendarHighlight));
        root.style.setProperty("--calendar-on-highlight", calendarHighlightText);
        root.style.setProperty("--theme-on-background",
            contrast(background, [255, 255, 255]) >= contrast(background, [0, 0, 0]) ? "#ffffff" : "#000000");
        root.style.setProperty("--theme-background-glow",
            dark ? hex(mix(background, [100, 104, 114], 0.65)) : "#ffffff");
        for (const [name, channels] of Object.entries(palette)) {
            root.style.setProperty(`--theme-${name}`, hex(channels));
        }
        root.style.setProperty("--theme-accent", hex(accent));
        root.style.setProperty("--theme-accent-hover", hex(mix(accent,
            dark ? [255, 255, 255] : [0, 0, 0], 0.10)));
        root.style.setProperty("--theme-on-accent", hex(accentText));
        root.style.setProperty("--theme-success", dark ? "#79d693" : "#277641");
        root.style.setProperty("--task-icon-surface", hex(iconSurface));

        root.style.colorScheme = dark ? "dark" : "light";
    };

    try {
        const savedColor = localStorage.getItem(colorStorageKey);
        if (savedColor && /^#[0-9a-f]{6}$/i.test(savedColor)) {
            selectedColor = savedColor;
            hasCustomColor = true;
        }
        const savedMode = localStorage.getItem(modeStorageKey);
        if (savedMode === "dark" || savedMode === "light") {
            mode = savedMode;
        } else if (hasCustomColor) {
            const channels = [1, 3, 5].map((index) =>
                parseInt(selectedColor.slice(index, index + 2), 16));
            mode = luminance(channels) < 0.3 ? "dark" : "light";
        }
    } catch (_) {
        // Storage can be unavailable in privacy-restricted browsers.
    }
    applyTheme(selectedColor, mode);

    document.addEventListener("DOMContentLoaded", () => {
        const button = document.querySelector("#background-color-button");
        const input = document.querySelector("#background-color-input");
        const modeSwitch = document.querySelector("#theme-switch");

        const updateSwitch = () => {
            if (!modeSwitch) return;
            const dark = mode === "dark";
            modeSwitch.setAttribute("aria-checked", String(dark));
            modeSwitch.setAttribute("aria-label", dark ? "Dark mode" : "Light mode");
            modeSwitch.title = dark ? "Switch to light mode" : "Switch to dark mode";
        };
        updateSwitch();
        root.classList.add("theme-ready");

        modeSwitch?.addEventListener("click", () => {
            mode = mode === "light" ? "dark" : "light";
            applyTheme(selectedColor, mode);
            updateSwitch();
            try {
                localStorage.setItem(modeStorageKey, mode);
            } catch (_) {
                // The selected mode still applies for the current page.
            }
        });

        if (button && input) {
            input.value = selectedColor;
            button.addEventListener("click", () => input.click());
            input.addEventListener("input", () => {
                selectedColor = input.value;
                hasCustomColor = true;
                applyTheme(selectedColor, mode);
                try {
                    localStorage.setItem(colorStorageKey, selectedColor);
                } catch (_) {
                    // The color still applies for the current page.
                }
            });
        }
    });
})();
