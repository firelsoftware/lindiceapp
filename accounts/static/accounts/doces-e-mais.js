(function () {
    var items = Array.prototype.slice.call(document.querySelectorAll(".reveal"));

    if (!("IntersectionObserver" in window)) {
        items.forEach(function (item) {
            item.classList.add("is-visible");
        });
        return;
    }

    var observer = new IntersectionObserver(function (entries) {
        entries.forEach(function (entry) {
            if (entry.isIntersecting) {
                entry.target.classList.add("is-visible");
                observer.unobserve(entry.target);
            }
        });
    }, { threshold: 0.12, rootMargin: "0px 0px -8% 0px" });

    items.forEach(function (item, index) {
        item.style.transitionDelay = Math.min(index * 35, 220) + "ms";
        observer.observe(item);
    });
})();

(function () {
    var carousels = Array.prototype.slice.call(document.querySelectorAll("[data-doces-carousel]"));

    carousels.forEach(function (carousel) {
        var track = carousel.querySelector("[data-carousel-track]");
        var prev = carousel.querySelector("[data-carousel-prev]");
        var next = carousel.querySelector("[data-carousel-next]");

        if (!track || !prev || !next) {
            return;
        }

        var scrollStep = function () {
            return Math.max(240, Math.round(track.clientWidth * 0.82));
        };

        prev.addEventListener("click", function () {
            track.scrollBy({ left: -scrollStep(), behavior: "smooth" });
        });

        next.addEventListener("click", function () {
            track.scrollBy({ left: scrollStep(), behavior: "smooth" });
        });
    });
})();
