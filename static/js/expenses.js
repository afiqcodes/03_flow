function setupTransactionCategories() {
    const form = document.querySelector("#transaction-form");
    if (!form) return;

    const kind = form.elements.kind;
    const category = form.elements.category;
    const updateCategories = () => {
        category.querySelectorAll("[data-transaction-kind]").forEach((group) => {
            group.disabled = group.dataset.transactionKind !== kind.value;
            group.hidden = group.disabled;
        });
        if (category.selectedOptions[0]?.parentElement.disabled) {
            category.value = category.querySelector("optgroup:not(:disabled) option").value;
        }
    };

    kind.addEventListener("change", updateCategories);
    updateCategories();
}

document.addEventListener("DOMContentLoaded", setupTransactionCategories);
document.addEventListener("app:content-updated", setupTransactionCategories);
