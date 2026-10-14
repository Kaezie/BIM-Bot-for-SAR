'use strict';

// Flask supplies public connection settings as JSON; credentials stay in .env.
// The service-role key must never be included in this configuration.
(() => {
  const config = JSON.parse(document.getElementById('bim-config').textContent);
  window.BIM_AUTH = window.supabase.createClient(config.url, config.key);
})();
