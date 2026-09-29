// Sign-in step of "Sign in to PROTrader with your Academy account" (/app-login).
// Uses the Academy's normal /api/login, then reloads: the server then sends the
// browser back to the app with a one-time code.
(() => {
  const form = document.getElementById('f'), status = document.getElementById('s'), button = document.getElementById('b');
  form.addEventListener('submit', async (event) => {
    event.preventDefault();
    const data = Object.fromEntries(new FormData(form));
    if (!data.email || !data.password) { status.textContent = 'Enter your email and password.'; return; }
    button.disabled = true; status.textContent = '';
    try {
      const res = await fetch('/api/login', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ email: data.email, password: data.password }) });
      const body = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(body.error || 'Sign-in failed. Try again.');
      button.textContent = 'Signed in. Opening PROTrader…';
      // continue without prompt=login, so the server now issues the code
      const next = new URL(location.href); next.searchParams.delete('prompt');
      location.replace(next.toString());
    } catch (e) {
      status.textContent = e.message;
      button.disabled = false;
    }
  });
})();
