'use strict';

/* ---------------------------------------------------------------------------
   API client — every call talks to the Flask backend over fetch().
   Session is a cookie set by Flask, so credentials must be included.
--------------------------------------------------------------------------- */

async function apiCall(method, url, body) {
  const opts = {
    method,
    headers: { 'Content-Type': 'application/json' },
    credentials: 'same-origin',
  };
  if (body !== undefined) opts.body = JSON.stringify(body);
  const res = await fetch(url, opts);
  let data = {};
  try { data = await res.json(); } catch (e) { /* no body */ }
  if (!res.ok) {
    throw new Error(data.error || `Request failed (${res.status})`);
  }
  return data;
}

const api = {
  me: () => apiCall('GET', '/api/me'),
  register: (username, password) => apiCall('POST', '/api/register', { username, password }),
  login: (username, password) => apiCall('POST', '/api/login', { username, password }),
  logout: () => apiCall('POST', '/api/logout'),
  onboarding: (payload) => apiCall('POST', '/api/onboarding', payload),
  today: (dateStr) => apiCall('GET', `/api/today${dateStr ? `?date=${dateStr}` : ''}`),
  setChecklistItem: (date, item_key, value) => apiCall('POST', '/api/checklist', { date, item_key, value }),
  submitDay: (date, note) => apiCall('POST', '/api/submit-day', { date, note }),
  getWater: () => apiCall('GET', '/api/water'),
  bumpWater: (delta) => apiCall('POST', '/api/water', { delta }),
  getWeight: () => apiCall('GET', '/api/weight'),
  logWeight: (weight) => apiCall('POST', '/api/weight', { weight }),
  progress: () => apiCall('GET', '/api/progress'),
  resetAccount: () => apiCall('POST', '/api/account/reset'),
  deleteAccount: () => apiCall('POST', '/api/account/delete'),
  exportUrl: () => '/api/export',
};

/* ---------------------------------------------------------------------------
   Toast
--------------------------------------------------------------------------- */

function showToast(message) {
  let el = document.getElementById('sl-toast');
  if (!el) {
    el = document.createElement('div');
    el.id = 'sl-toast';
    el.className = 'toast';
    el.innerHTML = '<span class="toast-dot"></span><span id="sl-toast-text"></span>';
    document.body.appendChild(el);
  }
  document.getElementById('sl-toast-text').textContent = message;
  el.classList.add('show');
  clearTimeout(el._timer);
  el._timer = setTimeout(() => el.classList.remove('show'), 2800);
}

/* ---------------------------------------------------------------------------
   Nav
--------------------------------------------------------------------------- */

function renderNav(activePage) {
  const topbar = document.getElementById('sl-topbar');
  if (topbar) {
    topbar.innerHTML = `
      <div class="topbar-inner">
        <div class="brand"><span class="brand-mark"></span><span>STEALTH LUXE</span></div>
        <nav class="nav-links">
          <a href="/dashboard.html" class="${activePage === 'dashboard' ? 'active' : ''}">Dashboard</a>
          <a href="/progress.html" class="${activePage === 'progress' ? 'active' : ''}">Progress</a>
        </nav>
        <button class="logout-btn" id="sl-logout">Sign out</button>
      </div>
    `;
    document.getElementById('sl-logout').addEventListener('click', async () => {
      await api.logout();
      window.location.href = '/';
    });
  }

  let mnav = document.getElementById('sl-mobile-nav');
  if (!mnav) {
    mnav = document.createElement('div');
    mnav.id = 'sl-mobile-nav';
    mnav.className = 'mobile-nav';
    document.body.appendChild(mnav);
  }
  mnav.innerHTML = `
    <a href="/dashboard.html" class="${activePage === 'dashboard' ? 'active' : ''}">DASHBOARD</a>
    <a href="/progress.html" class="${activePage === 'progress' ? 'active' : ''}">PROGRESS</a>
  `;
}

/* ---------------------------------------------------------------------------
   Countdown banner — now driven by the user's own program length
--------------------------------------------------------------------------- */

function renderCountdown(dayNumber, durationDays, containerId) {
  const container = document.getElementById(containerId);
  if (!container) return;
  const stage = Math.min(4, Math.ceil(dayNumber / Math.max(1, Math.ceil(durationDays / 4))));
  const pct = Math.min(100, (dayNumber / durationDays) * 100);
  container.innerHTML = `
    <div class="countdown-label"><span class="stage">STAGE 0${stage} /</span> DAY <span class="day-num">${dayNumber}</span> OF ${durationDays}</div>
    <div class="countdown-track"><div class="countdown-fill" style="width:${pct}%"></div></div>
  `;
}

/* ---------------------------------------------------------------------------
   Auth guards used at the top of each protected page
--------------------------------------------------------------------------- */

async function requireAuthAndProfile(redirectIfNoProfile) {
  const me = await api.me();
  if (!me.authenticated) {
    window.location.href = '/';
    return null;
  }
  if (redirectIfNoProfile && !me.profile) {
    window.location.href = '/onboarding.html';
    return null;
  }
  return me;
}
