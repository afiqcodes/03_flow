const currencyFormatter = new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
});

function setupBudgetStats() {
    const yearSelect = document.querySelector("#budget-stats-year");
    if (!yearSelect) return;

    const incomeLabel = document.querySelector("#budget-stats-income-label");
    const incomeValue = document.querySelector("#budget-stats-income");
    const expensesValue = document.querySelector("#budget-stats-expenses");
    const plannedValue = document.querySelector("#budget-stats-planned");
    const remainingValue = document.querySelector("#budget-stats-remaining");

    const updateStats = () => {
        const option = yearSelect.selectedOptions[0];
        if (!option) return;

        const income = Number.parseFloat(option.dataset.income || "0");
        const expenses = Number.parseFloat(option.dataset.expenses || "0");
        const remaining = Number.parseFloat(option.dataset.remaining || "0");

        incomeLabel.textContent = `${option.value} income`;
        incomeValue.textContent = currencyFormatter.format(income);
        expensesValue.textContent = currencyFormatter.format(expenses);
        plannedValue.textContent = `${option.dataset.planned}/12 months planned`;
        remainingValue.textContent = currencyFormatter.format(remaining);
        remainingValue.classList.toggle("negative", remaining < 0);
    };

    yearSelect.addEventListener("change", updateStats);
}

function setupBudgetCalculator() {
    const form = document.querySelector("#budget-form");
    const preview = document.querySelector("#budget-remaining-preview");
    if (!form || !preview) return;

    const output = preview.querySelector("strong");
    const valueOf = (fieldName) => {
        const field = form.elements.namedItem(fieldName);
        return Number.parseFloat(field?.value || "0") || 0;
    };
    const updateRemaining = () => {
        const expenses = ["food", "transport", "bills", "entertainment"].reduce(
            (total, fieldName) => total + valueOf(fieldName),
            0
        );
        const remaining = valueOf("income") - valueOf("savings") - expenses;

        output.textContent = currencyFormatter.format(remaining);
        preview.classList.toggle("negative", remaining < 0);
    };

    form.querySelectorAll("[data-budget-value]").forEach((field) => {
        field.addEventListener("input", updateRemaining);
    });
    updateRemaining();
}

function setupBudgets() {
    setupBudgetStats();
    setupBudgetCalculator();
}

document.addEventListener("DOMContentLoaded", setupBudgets);
document.addEventListener("app:content-updated", setupBudgets);
