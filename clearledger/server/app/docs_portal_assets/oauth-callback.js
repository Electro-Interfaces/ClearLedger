"use strict";
(() => {
  const query = new URLSearchParams(window.location.search);
  history.replaceState(null, "", window.location.pathname);
  const result = document.getElementById("oauth-result");
  try {
    const opener = window.opener;
    if (!opener || opener.location.origin !== location.origin) throw new Error();
    const pending = opener.docsOAuthPending;
    const redirect = opener.swaggerUIRedirectOauth2;
    if (!pending || !redirect || pending.used || pending.expiresAt <= Date.now() || pending.generation !== redirect.auth.docsGeneration
        || query.getAll("state").length !== 1 || query.get("state") !== pending.state || redirect.state !== pending.state
        || query.getAll("code").length > 1 || query.has("access_token") || query.has("id_token")) throw new Error();
    pending.used = true;
    delete opener.docsOAuthPending;
    delete opener.swaggerUIRedirectOauth2;
    if (query.has("error") || !query.get("code")) {
      redirect.errCb({ authId: redirect.auth.name, source: "auth", level: "error", message: "Согласие не получено" });
    } else {
      delete redirect.state;
      redirect.auth.code = query.get("code");
      redirect.callback({ auth: redirect.auth, redirectUrl: redirect.redirectUrl });
    }
    window.close();
  } catch { result.textContent = "Недействительный или просроченный ответ авторизации. Начните заново."; }
})();
