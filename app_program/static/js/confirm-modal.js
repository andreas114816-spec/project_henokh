(function () {
    let pendingForm = null;

    function ensureModal() {
        let modal = document.getElementById("confirmModal");

        if (modal) {
            return modal;
        }

        modal = document.createElement("div");
        modal.id = "confirmModal";
        modal.className = "fixed inset-0 z-50 hidden items-center justify-center bg-black/50 px-4";
        modal.innerHTML = `
            <div class="w-full max-w-md rounded-lg bg-white p-5 shadow-xl">
                <h2 id="confirmModalTitle" class="text-lg font-semibold text-gray-900">Confirm Action</h2>
                <p id="confirmModalMessage" class="mt-2 text-sm leading-6 text-gray-600"></p>
                <div class="mt-5 flex flex-col-reverse gap-3 sm:flex-row sm:justify-end">
                    <button
                        type="button"
                        id="confirmModalCancel"
                        class="rounded-lg border border-gray-300 px-4 py-2 text-sm font-medium text-gray-800 hover:bg-gray-50">
                        Cancel
                    </button>
                    <button
                        type="button"
                        id="confirmModalConfirm"
                        class="rounded-lg bg-red-600 px-4 py-2 text-sm font-medium text-white hover:bg-red-700">
                        Continue
                    </button>
                </div>
            </div>
        `;
        document.body.appendChild(modal);

        modal.querySelector("#confirmModalCancel").addEventListener("click", closeModal);
        modal.addEventListener("click", function (event) {
            if (event.target === modal) {
                closeModal();
            }
        });
        modal.querySelector("#confirmModalConfirm").addEventListener("click", function () {
            const form = pendingForm;
            closeModal();

            if (form) {
                form.dataset.confirmed = "true";
                form.submit();
            }
        });

        document.addEventListener("keydown", function (event) {
            if (event.key === "Escape" && !modal.classList.contains("hidden")) {
                closeModal();
            }
        });

        return modal;
    }

    function closeModal() {
        const modal = document.getElementById("confirmModal");
        pendingForm = null;

        if (modal) {
            modal.classList.add("hidden");
            modal.classList.remove("flex");
        }
    }

    function openModal(form) {
        const modal = ensureModal();
        const title = form.dataset.confirmTitle || "Confirm Action";
        const message = form.dataset.confirmMessage || "Are you sure you want to continue?";
        const action = form.dataset.confirmAction || "Continue";

        pendingForm = form;
        modal.querySelector("#confirmModalTitle").textContent = title;
        modal.querySelector("#confirmModalMessage").textContent = message;
        modal.querySelector("#confirmModalConfirm").textContent = action;
        modal.classList.remove("hidden");
        modal.classList.add("flex");
        modal.querySelector("#confirmModalCancel").focus();
    }

    document.addEventListener("submit", function (event) {
        const form = event.target;

        if (!form.matches("[data-confirm-message]") || form.dataset.confirmed === "true") {
            return;
        }

        if (
            form.action.includes("/settings/restore-selected-archived")
            && !form.querySelector("input[name='item_ids']:checked")
        ) {
            event.preventDefault();
            return;
        }

        event.preventDefault();
        openModal(form);
    });

    document.addEventListener("change", function (event) {
        const selectAll = event.target.closest("[data-select-archive-group]");

        if (!selectAll) {
            return;
        }

        const group = selectAll.dataset.selectArchiveGroup;
        document
            .querySelectorAll(`[data-archive-group="${group}"]`)
            .forEach(function (checkbox) {
                checkbox.checked = selectAll.checked;
            });
    });
})();
