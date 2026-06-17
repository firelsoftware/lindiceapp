const CACHE_NAME = "lindice-store-v4";
const APP_SHELL = [
  "{{ store_front_url }}",
  "{{ offline_url }}",
  "/static/accounts/lindice-icon.svg?v=20260531",
  "/static/accounts/lindice-icon-192.png?v=20260531",
  "/static/accounts/lindice-icon-512.png?v=20260531",
  "/static/accounts/site.webmanifest?v=20260531"
];

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME).then((cache) => cache.addAll(APP_SHELL))
  );
  self.skipWaiting();
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(
        keys
          .filter((key) => key !== CACHE_NAME)
          .map((key) => caches.delete(key))
      )
    )
  );
  self.clients.claim();
});

self.addEventListener("fetch", (event) => {
  if (event.request.method !== "GET") {
    return;
  }

  const request = event.request;
  const acceptsHtml = request.headers.get("accept") && request.headers.get("accept").includes("text/html");

  if (request.mode === "navigate" || acceptsHtml) {
    // Sempre busca a pagina fresca na rede. Nao guardamos HTML no cache para
    // nunca servir uma versao antiga (ex.: deslogada) que faz o usuario
    // parecer fora da conta e ter que entrar de novo. Offline cai na pagina padrao.
    event.respondWith(
      fetch(request).catch(() => caches.match("{{ offline_url }}"))
    );
    return;
  }

  event.respondWith(
    caches.match(request).then((cached) => {
      if (cached) {
        return cached;
      }

      return fetch(request)
        .then((response) => {
          if (!response || response.status !== 200 || response.type === "opaque") {
            return response;
          }

          const copy = response.clone();
          caches.open(CACHE_NAME).then((cache) => cache.put(request, copy));
          return response;
        })
        .catch(() => caches.match(request));
    })
  );
});
