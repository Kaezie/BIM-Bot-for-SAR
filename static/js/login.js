'use strict';
(() => {
  const client = window.BIM_AUTH;
  const googleBtn = document.getElementById('googleBtn'), label = document.getElementById('googleBtnLabel');
  const errorMsg = document.getElementById('errorMsg');
  const showError = message => { errorMsg.textContent = message; errorMsg.hidden = false; };
  if (new URLSearchParams(location.search).get('reason') === 'expired') showError('Your local session ended. Connect to internet and sign in with Google again.');
  client.auth.getSession().then(({data: {session}, error}) => {
    if (session) window.location.assign('/');
    else if (error) showError(error.message);
  });
  googleBtn.addEventListener('click', async () => {
    googleBtn.disabled = true; errorMsg.hidden = true; label.textContent = 'Connecting to Google…';
    try {
      const {error} = await client.auth.signInWithOAuth({provider: 'google', options: {redirectTo: window.location.origin + '/'}});
      if (error) throw error;
    } catch (error) {
      showError(error.message || 'Connect to internet to sign in with Google.');
      googleBtn.disabled = false; label.textContent = 'Sign in with Google';
    }
  });
})();
