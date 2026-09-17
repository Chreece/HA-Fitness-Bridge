/* OAuth code/token never leaves this Home Assistant origin. */
(async () => {
  "use strict";
  const status = document.getElementById("status"), button = document.getElementById("connect");
  const key = "fitness_bridge_oauth_pending";
  const clientId = location.origin + "/api/fitness_bridge/oauth-client";
  const redirect = location.origin + "/api/fitness_bridge/oauth-callback";
  let tokens, socket;
  try {
    if (location.pathname.endsWith("/setup")) {
      const params = new URLSearchParams(location.hash.slice(1));
      history.replaceState(null, "", location.pathname);
      const fitness = new URL(params.get("fitness_url"));
      const ticket = params.get("ticket");
      if (!/^https?:$/.test(fitness.protocol) || fitness.username || fitness.password || fitness.pathname !== "/" || fitness.search || fitness.hash || !ticket || ticket.length > 128) throw new Error("Open setup from Fitness → Admin → Home Assistant.");
      status.textContent = `Allow ${fitness.origin} to use the Home Assistant bridge? Sign in as a Home Assistant administrator. You choose the permitted features and devices in Fitness after connecting.`;
      button.hidden = false;
      button.onclick = () => {
        button.disabled = true;
        const state = Array.from(crypto.getRandomValues(new Uint8Array(32)), n => n.toString(16).padStart(2,"0")).join("");
        sessionStorage.setItem(key, JSON.stringify({fitness:fitness.origin, ticket, state, created:Date.now()}));
        location.assign(location.origin + "/auth/authorize?" + new URLSearchParams({client_id:clientId, redirect_uri:redirect, state}));
      };
      return;
    }
    if (!location.pathname.endsWith("/oauth-callback")) { status.textContent = "Fitness Bridge authorization client."; return; }
    const query = new URLSearchParams(location.search);
    history.replaceState(null, "", location.pathname);
    const pending = JSON.parse(sessionStorage.getItem(key) || "null");
    sessionStorage.removeItem(key);
    if (!pending || Date.now() - pending.created > 300000 || query.get("state") !== pending.state || !query.get("code")) throw new Error("Authorization expired or was cancelled. Start again from Fitness.");
    status.textContent = "Connecting the authorized bridge…";
    const response = await fetch("/auth/token", {method:"POST", headers:{"Content-Type":"application/x-www-form-urlencoded"},
      body:new URLSearchParams({grant_type:"authorization_code", code:query.get("code"), client_id:clientId})});
    query.delete("code");
    if (!response.ok) throw new Error("Home Assistant authorization failed.");
    tokens = await response.json();
    await new Promise((resolve, reject) => {
      socket = new WebSocket(location.origin.replace(/^http/,"ws") + "/api/websocket");
      const timer = setTimeout(() => {socket.close();reject(new Error("Bridge setup timed out."));}, 30000);
      const finish = error => {clearTimeout(timer);error ? reject(error) : resolve();};
      socket.onerror = () => finish(new Error("Could not reach the HA WebSocket API."));
      socket.onclose = () => finish(new Error("Home Assistant closed the setup connection."));
      socket.onmessage = event => {
        const message = JSON.parse(event.data);
        if (message.type === "auth_required") socket.send(JSON.stringify({type:"auth", access_token:tokens.access_token}));
        else if (message.type === "auth_invalid") finish(new Error("Home Assistant rejected the authorization."));
        else if (message.type === "auth_ok") socket.send(JSON.stringify({id:1, type:"fitness_bridge/pair", fitness_url:pending.fitness, ticket:pending.ticket}));
        else if (message.id === 1) finish(message.success ? null : new Error(message.error?.message || "Pairing failed. Use a Home Assistant administrator account."));
      };
    });
    status.textContent = "Connected. Return to Fitness and choose the users, features and devices to allow. You can close this window.";
    window.opener?.postMessage({type:"fitness-ha-paired"}, pending.fitness);
  } catch (error) {
    status.textContent = String(error?.message || "Connection failed. Start again from Fitness.");
  } finally {
    socket?.close();
    if (tokens?.refresh_token) {
      // Revokes this temporary HA grant and its access token after pairing.
      try {
        let response = await fetch("/auth/revoke", {method:"POST", keepalive:true, headers:{"Content-Type":"application/x-www-form-urlencoded"}, body:new URLSearchParams({token:tokens.refresh_token})});
        if (!response.ok) response = await fetch("/auth/token", {method:"POST", keepalive:true, headers:{"Content-Type":"application/x-www-form-urlencoded"}, body:new URLSearchParams({action:"revoke", token:tokens.refresh_token})});
        if (!response.ok) throw new Error("Revocation failed");
      } catch { status.textContent += " Temporary authorization could not be revoked. Remove the Fitness Bridge grant in your Home Assistant security settings."; }
    }
    tokens = null;
  }
})();
