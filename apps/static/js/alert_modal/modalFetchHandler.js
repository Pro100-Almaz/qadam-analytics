function registerModalFetchHandler(className){
    document.addEventListener("click", function (e) {
            const target = e.target.closest("." + className);
            if (!target) return;

            e.preventDefault();

            const url = target.dataset.url;
            if (!url) return;

            fetch(url, {
                headers: {"X-Requested-With": "XMLHttpRequest"}
            })
                .then(response => {
                    const type = response.headers.get("content-type") || "";

                    // JSON --> show modal
                    if (type.includes("application/json")) {
                        return response.json();
                    }

                    // HTML --> redirect
                    window.location.href = url;
                    throw new Error("Redirecting");
                })
                .then(data => {
                    if (data.status === "show_modal") {
                        document.getElementById("alertModal")?.remove();

                        document.body.insertAdjacentHTML(
                            "beforeend",
                            data.html_content
                        );

                        const modalEl = document.getElementById("alertModal");
                        const modal = new bootstrap.Modal(modalEl);
                        modal.show();
                    }
                })
                .catch(() => {
                });
        });
}