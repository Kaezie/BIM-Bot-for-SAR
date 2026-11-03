'use strict';

// Robot-network sessions are verified by Flask's HttpOnly cookie. Loading the
// dashboard requires no CDN or cloud token refresh while this cookie is valid.
(() => {
  const config = JSON.parse(document.getElementById('bim-config').textContent);
  const SDK_URL = 'https://cdn.jsdelivr.net/npm/@supabase/supabase-js@2.49.8/dist/umd/supabase.js';
  const logoutKey = 'bim-explicit-signout', expiryKey = 'bim-local-session-expiry', oauthKey = 'bim-google-signin-pending';
  const listeners = new Set();
  let sdk, sdkLoading, bootstrap, current = null, expiryTimer, exchanging;
  const stored = key => { try { return localStorage.getItem(key); } catch { return null; } };
  const remember = (key, value) => { try { value === null ? localStorage.removeItem(key) : localStorage.setItem(key, String(value)); } catch { /* Cookie remains authoritative. */ } };
  const bounded = (promise, milliseconds = 12000) => new Promise((resolve, reject) => {
    const timer = setTimeout(() => reject(new Error('Connect to internet and try Google sign-in again.')), milliseconds);
    Promise.resolve(promise).then(value => { clearTimeout(timer); resolve(value); }, error => { clearTimeout(timer); reject(error); });
  });
  function publish(event, session) {
    current = session; clearTimeout(expiryTimer);
    if (session?.expires_at) {
      remember(expiryKey, session.expires_at);
      expiryTimer = setTimeout(() => publish('SESSION_EXPIRED', null), Math.max(0, session.expires_at * 1000 - Date.now()));
    }
    listeners.forEach(callback => callback(event, current));
  }
  async function localSession(method = 'GET', token) {
    const response = await fetch('/api/local-session', {
      method, credentials: 'same-origin', cache: 'no-store',
      headers: token ? {Authorization: `Bearer ${token}`} : {}, signal: AbortSignal.timeout(12000)
    });
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || 'The local sign-in could not be verified.');
    return data.session || null;
  }
  const oauthCallback = () => new URLSearchParams(location.search).has('code') || /(?:access_token)=/.test(location.hash);
  function oauthError() {
    return new URLSearchParams(location.search).get('error_description') || new URLSearchParams(location.hash.slice(1)).get('error_description');
  }
  function hasCloudSession() {
    try { return Object.keys(localStorage).some(key => /^sb-.+-auth-token$/.test(key)); } catch { return false; }
  }
  async function exchange(cloudSession) {
    if (!cloudSession?.access_token || stored(logoutKey)) return null;
    if (!exchanging) exchanging = localSession('POST', cloudSession.access_token).then(session => {
      if (stored(logoutKey)) { localSession('DELETE').catch(() => {}); return null; }
      if (!session) throw new Error('Google sign-in did not create a local session.');
      publish('SIGNED_IN', session);
      if (oauthCallback()) history.replaceState(null, '', location.pathname);
      return session;
    }).finally(() => { exchanging = null; });
    return exchanging;
  }
  async function cloudClient() {
    if (sdk) return sdk;
    if (!sdkLoading) sdkLoading = (async () => {
      if (!window.supabase) await bounded(new Promise((resolve, reject) => {
        const script = document.createElement('script'); script.src = SDK_URL; script.async = true;
        script.onload = resolve; script.onerror = () => { script.remove(); reject(new Error('Google sign-in needs internet. Connect to internet, then try again.')); };
        document.head.append(script);
      }));
      sdk = window.supabase.createClient(config.url, config.key);
      // SDK locks may still be held inside its callback. Defer all async work.
      // A failed cloud refresh never revokes a valid local session.
      sdk.auth.onAuthStateChange((_event, cloudSession) => {
        setTimeout(() => {
          if (current || stored(logoutKey) || !cloudSession) return;
          exchange(cloudSession).catch(() => {});
        }, 0);
      });
      return sdk;
    })().catch(error => { sdkLoading = null; throw error; });
    return sdkLoading;
  }
  async function getSession() {
    if (!bootstrap) bootstrap = (async () => {
      try {
        const local = await localSession();
        if (local) { publish('INITIAL_SESSION', local); return {data: {session: local}, error: null}; }
        current = null;
        if (oauthError()) { remember(oauthKey, null); throw new Error(oauthError()); }
        if (oauthCallback() && stored(oauthKey)) { remember(logoutKey, null); remember(oauthKey, null); }
        if (stored(logoutKey)) return {data: {session: null}, error: null};
        if (stored(expiryKey) && !oauthCallback()) return {data: {session: null}, error: new Error('Your local session ended. Connect to internet and sign in with Google again.')};
        if (!oauthCallback() && !hasCloudSession()) return {data: {session: null}, error: null};
        const cloud = await cloudClient(), result = await bounded(cloud.auth.getSession());
        if (result.error) throw result.error;
        const session = await exchange(result.data.session);
        return {data: {session}, error: null};
      } catch (error) { return {data: {session: null}, error}; }
    })();
    const result = await bootstrap;
    if (current && current.expires_at * 1000 <= Date.now()) publish('SESSION_EXPIRED', null);
    return current ? {data: {session: current}, error: null} : result.data.session ? {data: {session: null}, error: new Error('Your local session expired. Sign in with Google while online.')} : result;
  }
  window.BIM_AUTH = {auth: {
    getSession,
    onAuthStateChange(callback) { listeners.add(callback); return {data: {subscription: {unsubscribe: () => listeners.delete(callback)}}}; },
    async signInWithOAuth(options) {
      if (options?.provider !== 'google') return {error: new Error('Use Google to sign in.')};
      // Keep stale INITIAL_SESSION events blocked until the new OAuth callback.
      // Cancelling Google or an initiation error must not restore the old login.
      remember(logoutKey, '1'); remember(oauthKey, '1'); remember(expiryKey, null); bootstrap = null;
      try {
        const cloud = await cloudClient();
        try { await bounded(cloud.auth.signOut({scope: 'local'}), 3000); } catch { /* Callback verification remains mandatory. */ }
        const result = await bounded(cloud.auth.signInWithOAuth(options));
        if (result.error) remember(oauthKey, null);
        return result;
      } catch (error) { remember(oauthKey, null); return {error}; }
    },
    async signOut() {
      remember(logoutKey, '1'); remember(oauthKey, null);
      try { await localSession('DELETE'); } catch (error) { return {error}; }
      remember(logoutKey, '1'); remember(expiryKey, null); bootstrap = null; publish('SIGNED_OUT', null);
      if (sdk) bounded(sdk.auth.signOut({scope: 'local'}), 3000).catch(() => {});
      return {error: null};
    }
  }};
})();
