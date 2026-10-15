'use strict';

(() => {
  const client = window.BIM_AUTH;
  const googleBtn = document.getElementById('googleBtn');
  const googleBtnLabel = document.getElementById('googleBtnLabel');
  const errorMsg = document.getElementById('errorMsg');

  const form = document.getElementById('authForm');
  const submit = document.getElementById('authSubmit');
  const successMsg = document.getElementById('successMsg');
  form.addEventListener('submit', async event => {
    event.preventDefault();
    errorMsg.hidden = true;
    successMsg.hidden = true;
    const signup = form.dataset.mode === 'signup';
    const email = document.getElementById('email').value.trim();
    const password = document.getElementById('password').value;
    if (signup && password !== document.getElementById('confirmPassword').value) {
      errorMsg.textContent = 'Passwords do not match.';
      errorMsg.hidden = false;
      return;
    }
    submit.disabled = true;
    submit.textContent = signup ? 'Creating account…' : 'Logging in…';
    try {
      const result = signup
        ? await client.auth.signUp({ email, password, options: { data: { username: document.getElementById('username').value.trim() }, emailRedirectTo: window.location.origin + '/' } })
        : await client.auth.signInWithPassword({ email, password });
      if (result.error) throw result.error;
      if (result.data.session) { window.location.assign('/'); return; }
      successMsg.textContent = 'Check your email to confirm your account, then log in.';
      successMsg.hidden = false;
      form.reset();
    } catch (error) {
      errorMsg.textContent = error.message || 'Could not reach the sign-in service. Please try again.';
      errorMsg.hidden = false;
    } finally {
      submit.disabled = false;
      submit.textContent = signup ? 'Create Account' : 'Log In';
    }
  });

  // Existing sessions and the return from Google go straight to the dashboard.
  client.auth.getSession().then(({ data: { session } }) => {
    if (session) window.location.href = '/';
  });

  googleBtn.addEventListener('click', async () => {
    googleBtn.disabled = true;
    googleBtnLabel.innerText = 'Redirecting to Google…';
    const { error } = await client.auth.signInWithOAuth({
      provider: 'google',
      options: { redirectTo: window.location.origin + '/' }
    });
    if (error) {
      errorMsg.innerText = error.message;
      errorMsg.hidden = false;
      googleBtn.disabled = false;
      googleBtnLabel.innerText = 'Sign in with Google';
    }
  });
})();
