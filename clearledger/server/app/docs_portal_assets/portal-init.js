/* Own glue around pinned Swagger UI; tokens stay in Swagger's memory only. */
"use strict";
(() => {
  const config = JSON.parse(document.getElementById("docs-config").textContent);
  const origin = window.location.origin;
  if (new URL(config.authorizationUrl).origin !== origin || new URL(config.apiUrl).origin !== origin) throw new Error("Same-space docs configuration required");
  let generation = 0;
  let businessToken;
  let expiryTimer;
  let popup;
  const random = () => btoa(String.fromCharCode(...crypto.getRandomValues(new Uint8Array(32)))).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
  const fail = (system, auth, message) => system.errActions.newAuthErr({ authId: auth.name, source: "auth", level: "error", message });
  async function revoke(token) {
    if (!token) return;
    await fetch(config.revokeUrl, { method: "POST", credentials: "omit", cache: "no-store", keepalive: true,
      headers: { "Content-Type": "application/x-www-form-urlencoded" },
      body: new URLSearchParams({ client_id: config.clientId, token }) });
  }
  function forget() {
    generation++;
    if (popup && !popup.closed) popup.close();
    delete window.swaggerUIRedirectOauth2;
    delete window.docsOAuthPending;
    clearTimeout(expiryTimer);
    const token = businessToken;
    businessToken = undefined;
    if (window.ui) window.ui.authActions.logout(["ProductOAuth"]);
    void revoke(token).catch(() => {}); // Local authority is gone even if revocation transport fails.
  }
  const authPlugin = () => ({ statePlugins: { auth: { wrapActions: {
    logout: (original) => (...args) => {
      const token = businessToken; businessToken = undefined;
      generation++; clearTimeout(expiryTimer);
      if (popup && !popup.closed) popup.close();
      delete window.docsOAuthPending; delete window.swaggerUIRedirectOauth2;
      void revoke(token).catch(() => {});
      return original(...args);
    },
    authPopup: (_original, system) => (url, redirect) => {
      if (!config.sandboxReady) return fail(system, redirect.auth, "Сначала настройте тестовый API");
      const target = new URL(url, origin);
      const scopes = (target.searchParams.get("scope") || "").split(" ").filter(Boolean);
      if (target.href.split("?")[0] !== config.authorizationUrl || target.searchParams.get("client_id") !== config.clientId
          || !scopes.length || scopes.some((scope) => !config.businessScopes.includes(scope))
          || redirect.auth.clientSecret) return fail(system, redirect.auth, "Недопустимые параметры публичного клиента");
      popup = window.open("about:blank", "elsy-docs-business-consent");
      if (!popup) return fail(system, redirect.auth, "Разрешите окно авторизации");
      const current = ++generation;
      const verifier = random(), state = random(), nonce = random();
      crypto.subtle.digest("SHA-256", new TextEncoder().encode(verifier)).then((hash) => {
        if (current !== generation || popup.closed) return;
        const challenge = btoa(String.fromCharCode(...new Uint8Array(hash))).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
        target.search = new URLSearchParams({ response_type: "code", client_id: config.clientId,
          redirect_uri: config.swaggerRedirectUri, scope: scopes.join(" "), state, nonce,
          code_challenge: challenge, code_challenge_method: "S256", prompt: "consent" }).toString();
        redirect.state = state;
        redirect.redirectUrl = config.swaggerRedirectUri;
        redirect.auth.codeVerifier = verifier;
        redirect.auth.docsGeneration = current;
        redirect.auth.docsExpiresAt = Date.now() + 300000;
        delete redirect.auth.clientSecret;
        window.swaggerUIRedirectOauth2 = redirect;
        window.docsOAuthPending = { state, nonce, generation: current, expiresAt: Date.now() + 300000, used: false };
        popup.location.replace(target.href);
      }).catch(() => { popup.close(); fail(system, redirect.auth, "Не удалось подготовить PKCE"); });
    },
    authorizeOauth2: (original) => (payload) => {
      const token = payload.token;
      if (payload.auth.docsGeneration !== generation || payload.auth.docsExpiresAt <= Date.now()) {
        void revoke(token?.access_token).catch(() => {});
        throw new Error("Запрос авторизации отменён или просрочен");
      }
      if (payload.auth.clientId !== config.clientId || !token || token.token_type?.toLowerCase() !== "bearer"
          || !token.access_token || (token.scope || "").split(" ").some((scope) => !config.businessScopes.includes(scope))) throw new Error("Invalid business authorization");
      businessToken = token.access_token;
      clearTimeout(expiryTimer);
      expiryTimer = setTimeout(forget, Math.max(0, Math.min(Number(token.expires_in) * 1000, 300000)));
      return original(payload);
    },
  } } } });
  document.getElementById("docs-mode").textContent = config.sandboxReady
    ? "Тестовый контур. Authorize выдаёт отдельное согласие на выбранные действия."
    : "Требуется настройка тестового контура. Документация доступна для чтения; выполнение запросов отключено.";
  window.ui = SwaggerUIBundle({ dom_id: "#swagger-ui", url: "/api/developer/docs/openapi.json",
    validatorUrl: null, queryConfigEnabled: false, persistAuthorization: false,
    oauth2RedirectUrl: config.swaggerRedirectUri, supportedSubmitMethods: config.sandboxReady ? ["get"] : [],
    presets: [SwaggerUIBundle.presets.apis], plugins: [authPlugin], layout: "BaseLayout",
    requestInterceptor: async (request) => {
      const target = new URL(request.url, origin);
      const authorization = new Headers(request.headers).get("Authorization");
      const method = (request.method || "GET").toUpperCase();
      if (target.origin !== origin) throw new Error("External requests are disabled");
      if (target.pathname === "/api/developer/docs/openapi.json" && !target.search && method === "GET") {
        request.credentials = "same-origin";
        delete request.headers.Authorization; delete request.headers.authorization;
      } else if (target.href === config.tokenUrl && method === "POST") {
        const body = new URLSearchParams(request.body);
        if (body.get("client_id") !== config.clientId || body.get("grant_type") !== "authorization_code"
            || body.get("redirect_uri") !== config.swaggerRedirectUri || body.get("client_secret")
            || authorization) throw new Error("Invalid public code exchange");
        body.delete("client_secret"); request.body = body.toString(); request.credentials = "omit";
      } else if (target.pathname.startsWith("/api/v1/") && config.sandboxReady && method === "GET") {
        const live = await fetch("/api/developer/docs/session", { credentials: "same-origin", cache: "no-store" });
        if (!live.ok || !(await live.json()).sandboxReady) throw new Error("Тестовый контур недоступен. Выполнение запроса отключено.");
        if (!businessToken || authorization !== "Bearer " + businessToken) throw new Error("Authorize business scopes first");
        request.credentials = "omit";
      } else throw new Error("Request target is not allowed");
      return request;
    },
  });
  window.ui.initOAuth({ clientId: config.clientId, usePkceWithAuthorizationCodeGrant: true, scopes: [], scopeSeparator: " " });
  document.getElementById("docs-auth-logout").addEventListener("click", forget);
  window.addEventListener("message", (event) => {
    if (event.origin === origin && event.source === window.parent && event.data?.type === "docs:logout") forget();
  });
  setInterval(async () => {
    try {
      const response = await fetch("/api/developer/docs/session", { credentials: "same-origin", cache: "no-store" });
      if (response.ok) return;
    } catch { /* fail closed on unavailable live authority */ }
    forget(); document.body.replaceChildren(document.createTextNode("Доступ к документации завершён. Войдите заново."));
  }, 10000);
})();
