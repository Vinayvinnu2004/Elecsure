/* -- ElecSure Main JS -- */

// -- Auth -----------------------------------------------------------------
let _refreshPromise = null;
function getToken() { return localStorage.getItem('token'); }
function getRole() { return localStorage.getItem('role'); }

function updateNavbar() {
  const token = getToken(), role = getRole();
  const authDiv = document.getElementById('navAuth');
  const navLinks = document.getElementById('navLinks');

  if (role === 'electrician' && navLinks) {
    navLinks.style.display = 'none';
  } else if (navLinks) {
    navLinks.style.display = 'flex';
  }

  if (!authDiv) return;
  if (role) {
    const dashboardUrl = role === 'admin' ? '/admin' : role === 'electrician' ? '/electrician' : '/customer';
    const userName = localStorage.getItem('userName') || 'User';
    authDiv.innerHTML = `
      <div style="display:flex;align-items:center;gap:12px">
        <span style="font-size:14px;font-weight:600;color:var(--navy);white-space:nowrap">Hi, ${userName}</span>
        <a href="${dashboardUrl}" class="btn btn-primary" style="padding:8px 16px;font-size:13px">Dashboard</a>
        <button onclick="logout()" class="btn btn-outline" style="padding:8px 16px;font-size:13px">Logout</button>
      </div>`;
  } else {
    authDiv.innerHTML = '<a href="/login" class="btn btn-outline">Login</a><a href="/register" class="btn btn-primary">Get Started</a>';
  }
}

async function syncSessionFromCookie() {
  if (_refreshPromise) return _refreshPromise;
  
  _refreshPromise = (async () => {
    try {
      const token = getToken();
      const headers = { 'Content-Type': 'application/json' };
      if (token && token !== 'null' && token !== 'undefined') {
        headers['Authorization'] = 'Bearer ' + token;
      }

      // 1. Try to get fresh profile info
      let res;
      try {
        res = await fetch('/api/v1/users/me', { headers, credentials: 'include' });
      } catch (e) {
        // Network error - don't logout yet, just fail the sync
        return false;
      }

      if (res.ok) {
        const me = await res.json();
        localStorage.setItem('userName', me.name || '');
        localStorage.setItem('role', me.role || '');
        updateNavbar();
        return true;
      }

      // 2. If failed (likely 401), attempt silent refresh via refresh_token cookie
      // If res was not 401, it might be a 500/503. Don't logout on 500s.
      if (res.status !== 401) return false;

      let refRes;
      try {
        refRes = await fetch('/api/v1/auth/refresh', { method: 'POST', credentials: 'include' });
      } catch (e) {
        return false;
      }

      if (refRes.ok) {
        const ref = await refRes.json();
        localStorage.setItem('token', ref.access_token);
        localStorage.setItem('role', ref.role);
        localStorage.setItem('userName', ref.name);
        updateNavbar();
        return true;
      }
      return false;
    } finally { 
      // Small cooldown before allowing another refresh attempt
      setTimeout(() => { _refreshPromise = null; }, 1000);
    }
  })();
  
  return _refreshPromise;
}

async function requireAuthAsync(allowedRoles = []) {
  let token = getToken(), role = getRole();
  // Always try to sync on first load to check for updates
  const synced = await syncSessionFromCookie();
  if (!synced && !token) { window.location = '/login'; return false; }
  
  role = getRole();
  if (allowedRoles.length && !allowedRoles.includes(role)) { logout(); return false; }
  return true;
}

function requireAuth(allowedRoles = []) {
  const token = getToken(), role = getRole();
  if (!role) {
    // No role means definitely not logged in on this browser
    syncSessionFromCookie().then(synced => {
      if (!synced) { window.location = '/login'; return; }
      const r = getRole();
      if (allowedRoles.length && !allowedRoles.includes(r)) { logout(); return; }
    });
    return true; 
  }
  if (allowedRoles.length && !allowedRoles.includes(role)) { 
     // Role mismatch? Sync one last time before killing it
     syncSessionFromCookie().then(synced => {
       const r = getRole();
       if (!synced || (allowedRoles.length && !allowedRoles.includes(r))) logout();
     });
     return true; 
  }
  // Background sync for session info updates
  syncSessionFromCookie().catch(() => {});
  return true;
}

function logout() {
  fetch('/api/v1/auth/logout', { method: 'POST' }).catch(() => { });
  ['token', 'role', 'userName'].forEach(k => localStorage.removeItem(k));
  window.location = '/login';
}

// Redirect logged-in users off auth pages
if (['/login', '/register'].includes(window.location.pathname)) {
  const t = getToken(), r = getRole();
  if (t && r) window.location = r === 'admin' ? '/admin' : r === 'electrician' ? '/electrician' : '/customer';
}

// ── Update Navbar after login (initial) ──────────────────────────────
document.addEventListener('DOMContentLoaded', () => {
    updateNavbar();
    syncSessionFromCookie().catch(() => {});
});

// ── API Wrappers ──────────────────────────────────────────────────────
async function _apiFetch(url, opts = {}) {
  const token = getToken();
  const headers = { 'Content-Type': 'application/json', ...(opts.headers || {}) };
  if (token) headers['Authorization'] = 'Bearer ' + token;
  // Add timeout to prevent hanging requests
  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(), 30000); // 30 second timeout
  
  try {
    const res = await fetch(url, { ...opts, headers, signal: controller.signal });
    clearTimeout(timeoutId);
    
    if (res.status === 401) { 
      // Session might be expired. Try 1 silent refresh.
      if (!opts._retried) {
        const synced = await syncSessionFromCookie();
        if (synced) {
            return _apiFetch(url, { ...opts, _retried: true });
        }
      }
      // Only logout if we are NOT on a page that is already trying to sync (like dashboard init)
      const isAuthPage = window.location.pathname.includes('/login') || window.location.pathname.includes('/register');
      if (!isAuthPage && opts.logoutOnFail !== false) {
          console.warn('Session invalid, but postponing logout to allow sync...');
          // Optional: only logout if we are certain it's a 401/403 and sync failed
      }
    }
    let json;
    try { json = await res.json(); } catch { json = {}; }
    if (!res.ok) {
      let msg = typeof json.detail === 'string' ? json.detail
        : Array.isArray(json.detail) ? json.detail.map(e => {
          let m = e.msg || e.message || JSON.stringify(e);
          m = m.replace(/^Value error,\s*/i, '').replace(/^value_error,\s*/i, '');
          return m;
        }).join(' | ')
          : 'Something went wrong. Please try again.';
      throw new Error(msg);
    }
    return json;
  } catch (error) {
    clearTimeout(timeoutId);
    if (error.name === 'AbortError') {
      throw new Error('Request timed out. Please check your connection and try again.');
    }
    throw error;
  }
}
const apiGet = url => _apiFetch(url);
const apiPost = (url, b) => _apiFetch(url, { method: 'POST', body: JSON.stringify(b) });
const apiPut = (url, b) => _apiFetch(url, { method: 'PUT', body: JSON.stringify(b) });
const apiDelete = url => _apiFetch(url, { method: 'DELETE' });

// ── Toast (15 seconds) ────────────────────────────────────────────────
let _toastTimer = null;
function showToast(msg, type = 'info') {
  const el = document.getElementById('toast');
  if (!el) return;
  el.textContent = msg;
  el.className = 'toast ' + type;
  clearTimeout(_toastTimer);
  _toastTimer = setTimeout(() => el.classList.add('hidden'), 15000);
}

// ── Alert (15 seconds) ────────────────────────────────────────────────
let _alertTimer = null;
function showAlert(msg, type = 'error') {
  const el = document.getElementById('alertBox');
  if (!el) return;
  el.textContent = msg;
  el.className = 'alert ' + type;
  el.classList.remove('hidden');
  clearTimeout(_alertTimer);
  _alertTimer = setTimeout(() => el.classList.add('hidden'), 15000);
}

// ── Section Switcher ──────────────────────────────────────────────────
function showSection(id) {
  document.querySelectorAll('.dash-section').forEach(s => s.classList.remove('active'));
  const el = document.getElementById(id);
  if (el) el.classList.add('active');
  document.querySelectorAll('.sidebar-nav .nav-item').forEach(a => a.classList.remove('active'));
  if (typeof event !== 'undefined' && event && event.currentTarget) event.currentTarget.classList.add('active');
  const titles = {
    dashboardHomeSection: 'Dashboard', allBookingsSection: 'Track Your Services',
    bookSection: 'My Bookings', newBookSection: 'Book a Service',
    profileSection: 'My Profile', trackSection: 'Track Electrician',
    analyticsSection: 'Analytics', ordersSection: 'My Orders',
    slotsSection: 'Manage Slots', areasSection: 'Service Areas',
    scoreSection: 'EL Score', statsSection: 'Dashboard',
    usersSection: 'Users', bookingsSection: 'Bookings',
    leaderSection: 'EL Leaderboard', servicesSection: 'Services',
    settingsSection: 'Settings',
  };
  const t = document.getElementById('dashTitle');
  if (t && titles[id]) t.textContent = titles[id];
  document.getElementById('sidebar')?.classList.remove('open');
}

// ── Modal ─────────────────────────────────────────────────────────────
function closeModal(id) { document.getElementById(id)?.classList.add('hidden'); }

// ── Password toggle ───────────────────────────────────────────────────
function togglePwd(id) {
  const el = document.getElementById(id);
  el.type = el.type === 'password' ? 'text' : 'password';
}

// ── Date formatters (IST) ─────────────────────────────────────────────
function formatDate(iso) {
  if (!iso) return '—';
  try {
    const d = new Date(iso);
    if (isNaN(d.valueOf())) return iso;
    return d.toLocaleDateString('en-IN', { day: '2-digit', month: 'short', year: 'numeric', timeZone: 'Asia/Kolkata' });
  } catch (e) { return iso; }
}
function formatDateTime(iso) {
  if (!iso) return '—';
  try {
    const d = new Date(iso);
    if (isNaN(d.valueOf())) return iso;
    return d.toLocaleString('en-IN', { day: '2-digit', month: 'short', year: 'numeric', hour: '2-digit', minute: '2-digit', hour12: true, timeZone: 'Asia/Kolkata' });
  } catch (e) { return iso; }
}
function formatTime(iso) {
  if (!iso) return '—';
  try {
    // If iso is a time-only string like "10:00:00", we must prefix it with a date
    const timeStr = String(iso).includes('T') ? iso : (String(iso).includes(':') ? `1970-01-01T${iso}` : iso);
    const d = new Date(timeStr);
    if (isNaN(d.valueOf())) return iso;
    return d.toLocaleTimeString('en-IN', { hour: '2-digit', minute: '2-digit', hour12: true, timeZone: 'Asia/Kolkata' });
  } catch (e) { return iso; }
}

// ── Chatbot ───────────────────────────────────────────────────────────
let chatHistory = [], chatOpen = false;

function toggleChat() {
  chatOpen = !chatOpen;
  const w = document.getElementById('chatWidget');
  if (w) w.classList.toggle('hidden', !chatOpen);
}

async function sendChat() {
  const input = document.getElementById('chatInput');
  const msg = input?.value?.trim();
  if (!msg) return;
  input.value = '';
  appendChatMsg(msg, 'user');
  chatHistory.push({ role: 'user', content: msg });
  const typing = appendChatMsg('...', 'bot', true);
  try {
    const token = getToken();
    const endpoint = token ? '/api/v1/chat/' : '/api/v1/chat/guest';
    const res = await _apiFetch(endpoint, {
      method: 'POST',
      body: JSON.stringify({ message: msg, history: chatHistory.slice(-8) }),
    });
    typing.remove();
    appendChatMsg(res.reply, 'bot');
    chatHistory.push({ role: 'model', content: res.reply });
    // Handle action results
    if (res.action === 'cancel_booking' && res.action_data?.booking_id) {
      showToast('Booking cancelled successfully!', 'success');
      if (typeof loadBookings === 'function') setTimeout(loadBookings, 1000);
    }
  } catch (e) {
    typing.remove();
    appendChatMsg('Sorry, something went wrong. Please try again.', 'bot');
  }
}

function appendChatMsg(text, role, isTyping = false) {
  const msgs = document.getElementById('chatMessages');
  if (!msgs) return null;
  const div = document.createElement('div');
  div.className = 'chat-msg ' + role;
  const formatted = isTyping ? '<em>Typing...</em>' : text.replace(/\n/g, '<br/>').replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>');
  div.innerHTML = `<div class="chat-bubble-msg">${formatted}</div>`;
  msgs.appendChild(div);
  msgs.scrollTop = msgs.scrollHeight;
  return div;
}

function escapeHtml(s) {
  return String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
}

// ── Voice input for chatbot ───────────────────────────────────────────
function startVoiceInput() {
  if (!('webkitSpeechRecognition' in window) && !('SpeechRecognition' in window)) {
    showToast('Voice input not supported in this browser', 'error'); return;
  }
  const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
  const rec = new SR();
  rec.lang = 'en-IN';
  rec.interimResults = false;
  rec.onresult = e => {
    const text = e.results[0][0].transcript;
    document.getElementById('chatInput').value = text;
    sendChat();
  };
  rec.onerror = () => showToast('Voice input failed. Please type instead.', 'error');
  rec.start();
}

// ── Nav mobile toggle ─────────────────────────────────────────────────
document.getElementById('navToggle')?.addEventListener('click', () => {
  const links = document.getElementById('navLinks');
  if (links) {
    const isVisible = links.style.display === 'flex';
    links.style.display = isVisible ? 'none' : 'flex';
    links.style.flexDirection = 'column';
    links.style.position = 'absolute';
    links.style.top = '64px';
    links.style.left = '0';
    links.style.right = '0';
    links.style.background = '#fff';
    links.style.padding = '16px 24px';
    links.style.boxShadow = '0 4px 16px rgba(0,0,0,.1)';
    links.style.zIndex = '200';
  }
});

// ── Karimnagar Pincodes with Center Coordinates ──────────────────────
const KARIMNAGAR_PINCODES = {
  "505001": { area: "Karimnagar Head PO", lat: 18.4386, lng: 79.1288 },
  "505002": { area: "Market Area/Ramnagar", lat: 18.4418, lng: 79.1364 },
  "505003": { area: "Kamanpur", lat: 18.4326, lng: 79.1352 },
  "505004": { area: "Karimnagar Rural", lat: 18.4486, lng: 79.1088 },
  "505005": { area: "Industrial Area", lat: 18.4186, lng: 79.1388 },
  "505122": { area: "Jammikunta", lat: 18.3000, lng: 79.4300 },
  "505184": { area: "Huzurabad", lat: 18.2300, lng: 79.3800 },
  "505208": { area: "Ramagundam", lat: 18.7600, lng: 79.4600 },
  "505215": { area: "Gangadhara", lat: 18.5700, lng: 79.0300 },
  "505305": { area: "Manakondur", lat: 18.4100, lng: 79.1900 },
  "505402": { area: "Kodurpaka", lat: 18.5100, lng: 78.9600 },
  "505445": { area: "Veenavanka", lat: 18.3600, lng: 79.3100 },
  "505450": { area: "Kothapalli", lat: 18.4700, lng: 79.0800 },
  "505460": { area: "Thimmapur", lat: 18.3500, lng: 79.1200 },
  "505469": { area: "Ganneruvaram", lat: 18.2800, lng: 79.2400 },
  "505471": { area: "Mulkanur", lat: 18.1700, lng: 79.2800 },
  "505472": { area: "Ramadugu", lat: 18.5500, lng: 79.0700 },
  "505481": { area: "Nustulapur", lat: 18.3700, lng: 79.1600 },
  "505501": { area: "Husnabad", lat: 18.1300, lng: 79.1200 },
  "505531": { area: "Huzurabad (Alt)", lat: 18.2320, lng: 79.3850 },
};

function buildPincodeDropdown(selectId, inputId) {
  const sel = document.getElementById(selectId);
  const inp = document.getElementById(inputId);
  if (!sel) return;
  sel.innerHTML = '<option value="">Select Pincode</option>' +
    Object.keys(KARIMNAGAR_PINCODES).map(pin =>
      `<option value="${pin}">${pin} — ${KARIMNAGAR_PINCODES[pin].area}</option>`
    ).join('');
  if (inp) {
    sel.onchange = () => { inp.value = sel.value; };
  }
}

// Distance helper (Haversine formula in KM)
function getDistanceKm(lat1, lon1, lat2, lon2) {
    const R = 6371;
    const dLat = (lat2 - lat1) * Math.PI / 180;
    const dLon = (lon2 - lon1) * Math.PI / 180;
    const a = Math.sin(dLat / 2) * Math.sin(dLat / 2) +
              Math.cos(lat1 * Math.PI / 180) * Math.cos(lat2 * Math.PI / 180) *
              Math.sin(dLon / 2) * Math.sin(dLon / 2);
    const c = 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1 - a));
    return R * c; 
}

// ── Karimnagar District Geo-boundary ─────────────────────────────────
// Approximate bounding box for Karimnagar district, Telangana.
const KARIMNAGAR_BOUNDS = { minLat: 17.95, maxLat: 18.85, minLng: 78.60, maxLng: 79.75 };
function isInsideKarimnagar(lat, lng) {
  const b = KARIMNAGAR_BOUNDS;
  return lat >= b.minLat && lat <= b.maxLat && lng >= b.minLng && lng <= b.maxLng;
}

// ── Services taxonomy (for sidebar + booking) ─────────────────────────
const SERVICES_TAXONOMY = {
  "Electrical Appliance Repair": {
    icon: "🔧", subcategories: {
      "Laundry Appliances": ["Washing machines (all types)", "Washer", "Dryer", "Electric iron (dry iron)", "Steam iron", "Geyser", "Vacuum cleaner"],
      "Cooling Appliances": ["Refrigerator repair", "Deep freezer repair", "Air conditioner electrical repair", "Air cooler repair", "Water cooler repair", "Deep freezer", "Beverage cooler"],
      "Kitchen Appliances": ["Microwave oven repair", "Induction stove repair", "Mixer grinder repair", "Electric kettle repair", "Rice cooker repair", "OTG oven repair", "Dishwasher repair", "Water purifier repair", "Food processor", "Blender", "Coffee maker", "Coffee grinder", "Toaster", "Air fryer", "Waffle maker"],
      "Computing & IT Devices": ["Laptop electrical repair", "Desktop computer repair", "Monitor repair", "Printer repair", "Router / modem repair", "UPS repair", "Workstation", "All-in-one PC", "Mini PC", "Point-of-sale (POS) system"],
      "Entertainment Appliances": ["Television repair", "Set-top box repair", "Home theatre system repair", "Audio system repair", "Soundbar", "Speakers", "DVD / Blu-ray player", "Streaming media player", "Gaming console"],
    }
  },
  "Wiring & Circuit Repairs": {
    icon: "⚡", subcategories: {
      "Wiring Fault Repairs": ["Short circuit repair", "Loose wiring repair", "Neutral wire fault", "Phase wire fault", "Earth leakage fault", "Power failure diagnosis", "Power fluctuation issue", "Cable joint repair", "Main line fault repair"],
      "Circuit Protection": ["MCB tripping fix", "MCB replacement", "Fuse replacement", "Distribution board repair", "ELCB / RCCB repair", "Main switch replacement", "Socket repair"],
      "Wiring Upgrades": ["Burnt wire replacement", "Old wiring replacement", "Load capacity upgrade", "Concealed wiring repair", "Single-phase wiring repair", "Three-phase wiring repair"],
    }
  },
  "Lighting Services": {
    icon: "💡", subcategories: {
      "Lighting Repairs": ["LED bulb not working", "Tube light not working", "Flickering light repair", "Dim light issue", "Loose light holder repair", "Burnt holder replacement", "LED driver replacement", "Starter / choke replacement"],
      "Lighting Installations": ["LED bulb installation", "Tube light installation", "Ceiling light installation", "Wall light installation", "Decorative light setup", "Outdoor / balcony lighting", "Smart light installation"],
      "Lighting Upgrades": ["Conversion to LED lighting", "Energy-efficient lighting upgrade", "Smart lighting automation", "Dimming system installation"],
    }
  },
  "Installations": {
    icon: "🔌", subcategories: {
      "Basic Electrical": ["Switch installation", "Power socket (5A / 15A)", "Switch board installation", "Plug point installation", "Extension board installation"],
      "Appliance Installations": ["Ceiling fan installation", "Exhaust fan installation", "Geyser installation", "Air cooler installation", "Cooker / induction setup", "Microwave / OTG setup"],
      "Safety Installations": ["MCB installation / replacement", "New room wiring", "Switchboard rewiring", "Distribution board installation"],
      "Backup & Security": ["UPS installation", "CCTV installation", "Electric meter installation"],
    }
  },
  "Safety Checks & Inspections": {
    icon: "🛡️", subcategories: {
      "Safety Inspection": ["Electrical safety audit", "Short-circuit risk check", "Overload check", "Voltage fluctuation check", "Fire risk inspection", "Power quality inspection"],
      "Earthing Checks": ["Earthing repair", "Earthing continuity", "Earthing resistance", "Ground fault inspection"],
      "Protection Testing": ["MCB condition check", "Fuse health check", "RCCB / ELCB test", "MCB trip test", "Surge protection assessment"],
    }
  },
  "Power Backup Services": {
    icon: "🔋", subcategories: {
      "Inverter Services": ["Inverter installation", "Inverter repair", "Inverter battery connection", "Inverter load configuration"],
      "Battery Services": ["Battery replacement", "Battery health check", "Battery terminal cleaning", "Battery capacity testing"],
      "Backup Switching": ["Changeover switch setup", "Manual changeover switch installation", "Automatic changeover switch installation"],
    }
  },
  "Electrical Service Packages": {
    icon: "📦", subcategories: {
      "Home Packages": ["Old house electrical upgrade", "Home renovation electrical package", "Complete home electrical wiring service", "Complete home lighting installation"],
      "Safety Packages": ["Complete home safety check", "Comprehensive electrical inspection", "Electrical safety audit package"],
      "Energy Efficiency": ["Home load balancing package", "Energy-efficient lighting conversion", "Power consumption optimization"],
      "Festival Packages": ["Festival lighting full-home package", "Wedding lighting setup", "Outdoor decorative lighting package"],
    }
  },
};

// ── Build services sidebar HTML ───────────────────────────────────────
function buildServicesSidebar(containerId, onSelectCallback) {
  const container = document.getElementById(containerId);
  if (!container) return;
  let html = '';
  for (const [cat, catData] of Object.entries(SERVICES_TAXONOMY)) {
    html += `<div class="srv-cat">
      <div class="srv-cat-title" onclick="this.parentElement.classList.toggle('open')">
        ${catData.icon} ${cat} <span class="srv-arrow">▼</span>
      </div>
      <div class="srv-cat-body">`;
    for (const [subcat, services] of Object.entries(catData.subcategories)) {
      html += `<div class="srv-subcat">${subcat}</div>`;
      for (const svc of services) {
        const safe = svc.replace(/'/g, "\\'");
        html += `<div class="srv-item" onclick="selectServiceFromSidebar('${safe}', this)">${svc}</div>`;
      }
    }
    html += `</div></div>`;
  }
  container.innerHTML = html;
}

function selectServiceFromSidebar(serviceName, el) {
  // Highlight selected
  document.querySelectorAll('.srv-item').forEach(i => i.classList.remove('active'));
  if (el) el.classList.add('active');

  const token = getToken();
  if (!token) {
    // Redirect to register with service pre-selected
    window.location = `/register?service=${encodeURIComponent(serviceName)}`;
    return;
  }

  // Close sidebar overlay if exists
  const overlay = document.getElementById('servicesSidebarOverlay');
  if (overlay) overlay.classList.add('hidden');

  // If on customer dashboard, switch to booking section and select service
  if (typeof switchToBookingWithService === 'function') {
    switchToBookingWithService(serviceName);
  } else {
    window.location = `/customer?book=${encodeURIComponent(serviceName)}`;
  }
}

// ── Render inline analytics ───────────────────────────────────────────
function renderCustomerAnalytics(data, containerId) {
  const el = document.getElementById(containerId);
  if (!el) return;
  const b = data.booking_overview;
  const sp = data.spending;
  const svc = data.service_usage;
  const perf = data.service_performance;
  el.innerHTML = `
    <div class="analytics-grid">
      <div class="an-card"><div class="an-num">${b.total_bookings}</div><div class="an-label">Total Bookings</div></div>
      <div class="an-card green"><div class="an-num">${b.completed}</div><div class="an-label">Completed</div></div>
      <div class="an-card red"><div class="an-num">${b.cancelled}</div><div class="an-label">Cancelled</div></div>
      <div class="an-card blue"><div class="an-num">${b.ongoing + b.accepted + b.assigned + b.requested}</div><div class="an-label">Active</div></div>
      <div class="an-card amber"><div class="an-num">₹${sp.total_spent.toLocaleString()}</div><div class="an-label">Total Spent</div></div>
      <div class="an-card"><div class="an-num">₹${sp.avg_cost_per_service}</div><div class="an-label">Avg Cost/Service</div></div>
      <div class="an-card"><div class="an-num">₹${sp.monthly_spending}</div><div class="an-label">This Month</div></div>
      <div class="an-card amber"><div class="an-num">${perf.avg_rating_given}★</div><div class="an-label">Avg Rating Given</div></div>
    </div>
    <div class="an-section"><strong>Most Requested:</strong> ${svc.most_requested_service}</div>
    <div class="an-section"><strong>Top Category:</strong> ${svc.most_requested_category}</div>
  `;
}

function renderElectricianAnalytics(data, containerId) {
  const el = document.getElementById(containerId);
  if (!el) return;
  const op = data.order_performance;
  const earn = data.earnings;
  const sa = data.service_analytics;
  const rf = data.rating_feedback;
  const we = data.work_efficiency;
  el.innerHTML = `
    <div class="analytics-grid">
      <div class="an-card"><div class="an-num">${op.completed}</div><div class="an-label">Completed</div></div>
      <div class="an-card blue"><div class="an-num">${op.total_assigned}</div><div class="an-label">Total Assigned</div></div>
      <div class="an-card green"><div class="an-num">${op.accepted}</div><div class="an-label">Accepted</div></div>
      <div class="an-card red"><div class="an-num">${op.rejected}</div><div class="an-label">Cancelled</div></div>
      <div class="an-card amber"><div class="an-num">₹${earn.total_earnings.toLocaleString()}</div><div class="an-label">Total Earnings</div></div>
      <div class="an-card"><div class="an-num">₹${earn.weekly_earnings}</div><div class="an-label">This Week</div></div>
      <div class="an-card"><div class="an-num">₹${earn.monthly_earnings}</div><div class="an-label">This Month</div></div>
      <div class="an-card amber"><div class="an-num">${rf.average_rating}★</div><div class="an-label">Avg Rating</div></div>
    </div>
    <div class="an-section">
      <strong>EL Score:</strong> ${we.el_score}/100 &nbsp;|&nbsp;
      <strong>Avg Completion:</strong> ${we.avg_completion_minutes} min &nbsp;|&nbsp;
      <strong>Reviews:</strong> ${rf.total_reviews} (${rf.positive_reviews}👍 ${rf.negative_reviews}👎)
    </div>
    <div class="an-section"><strong>Top Service:</strong> ${sa.most_performed_service}</div>
    ${Object.keys(sa.category_breakdown).length ? `
    <div class="an-section">
      <strong>Category Breakdown:</strong><br/>
      ${Object.entries(sa.category_breakdown).map(([k, v]) =>
    `<span class="an-bar-label">${k}</span>
         <div class="an-bar"><div class="an-bar-fill" style="width:${v}%"></div></div>
         <span>${v}%</span><br/>`
  ).join('')}
    </div>` : ''}
  `;
}

// ── ACCOUNT-WIDE REVIEW LOCK ──────────────────────────────────────────
let _currentReviewBookingId = null;
let _reviewRating = 5;

async function checkAccountReviewLock() {
  const token = getToken(), role = getRole();
  if (!token || !role || role === 'admin') return;
  try {
    const data = await apiGet('/api/v1/bookings/my?per_page=10');
    const bookings = data.items || [];
    if (role === 'customer') {
      const pending = bookings.find(b => b.status === 'COMPLETED');
      if (pending) openReviewLock(pending.id, true);
    } else if (role === 'electrician') {
      const pending = bookings.find(b => b.status === 'REVIEWED' && !b.acknowledged_at);
      if (pending) openReviewAckLock(pending);
    }
  } catch (e) { }
}

// Customer Review Lock
function openReviewLock(id, forced = false) {
  _currentReviewBookingId = id;
  _reviewRating = 5;
  updateReviewStars(5);
  const ov = document.getElementById('reviewOverlay');
  if (ov) ov.classList.remove('hidden');

  if (forced) {
    const sider = document.getElementById('sidebar');
    const topbar = document.querySelector('.dash-topbar');
    const main = document.querySelector('.dash-main');
    if (sider) sider.style.display = 'none';
    if (topbar) topbar.style.display = 'none';
    if (main) main.style.marginLeft = '0';
    const skip = document.getElementById('skipReviewBtn');
    if (skip) skip.style.display = 'none';
  }
}

function setRating(r) { _reviewRating = r; updateReviewStars(r); }
function updateReviewStars(r) {
  document.querySelectorAll('#starRating span').forEach((s, i) => s.classList.toggle('active', i < r));
}

function dismissReviewOverlay() {
  const ov = document.getElementById('reviewOverlay');
  if (ov) ov.classList.add('hidden');
  const sider = document.getElementById('sidebar');
  const topbar = document.querySelector('.dash-topbar');
  const main = document.querySelector('.dash-main');
  if (sider) sider.style.display = 'flex';
  if (topbar) topbar.style.display = 'flex';
  if (main) main.style.marginLeft = '';
}

async function submitReview() {
  if (_reviewRating < 1) { showToast('Please select a rating', 'error'); return; }
  try {
    await apiPost('/api/v1/bookings/' + _currentReviewBookingId + '/review', {
      rating: _reviewRating,
      comment: document.getElementById('reviewComment').value || null
    });
    showToast('Review submitted! Thank you.', 'success');
    dismissReviewOverlay();
    // Refresh page or data
    if (window.location.pathname.includes('dashboard') || window.location.pathname.endsWith('/customer')) {
      if (typeof loadBookings === 'function') loadBookings();
    } else {
      window.location.reload();
    }
  } catch (e) { showToast(e.message, 'error'); }
}

// Electrician Acknowledgment Lock
let _currentAckBookingId = null;
function openReviewAckLock(booking) {
  _currentAckBookingId = booking.id;
  const rev = booking.review || {};
  const stars = '★'.repeat(rev.rating || 0) + '☆'.repeat(5 - (rev.rating || 0));
  const content = document.getElementById('reviewReceivedContent');
  if (content) {
    content.innerHTML = `
      <div style="font-size:24px; color:var(--amber); margin-bottom:8px;">${stars}</div>
      <div style="font-size:14px; color:var(--gray-700); font-style:italic;">"${rev.comment || 'No comment provided.'}"</div>
      <p style="font-size:12px; color:var(--gray-500); margin-top:12px;">Order #${booking.id} — ${booking.service ? booking.service.name : 'Service'}</p>
    `;
  }
  const ov = document.getElementById('reviewReceivedOverlay');
  if (ov) ov.classList.remove('hidden');

  const sider = document.getElementById('sidebar');
  const topbar = document.querySelector('.dash-topbar');
  const main = document.querySelector('.dash-main');
  if (sider) sider.style.display = 'none';
  if (topbar) topbar.style.display = 'none';
  if (main) main.style.marginLeft = '0';
}

async function acknowledgeCurrentReview() {
  if (!_currentAckBookingId) return;
  const btn = document.getElementById('ackReviewBtn');
  if (btn) { btn.disabled = true; btn.textContent = 'Acknowledging...'; }
  try {
    await apiPost('/api/v1/bookings/' + _currentAckBookingId + '/acknowledge', {});
    showToast('Review acknowledged', 'success');
    const ov = document.getElementById('reviewReceivedOverlay');
    if (ov) ov.classList.add('hidden');
    const sider = document.getElementById('sidebar');
    const topbar = document.querySelector('.dash-topbar');
    const main = document.querySelector('.dash-main');
    if (sider) sider.style.display = 'flex';
    if (topbar) topbar.style.display = 'flex';
    if (main) main.style.marginLeft = '';

    if (window.location.pathname.includes('dashboard') || window.location.pathname.endsWith('/electrician')) {
      if (typeof loadOrders === 'function') loadOrders();
    } else {
      window.location.reload();
    }
  } catch (e) {
    showToast(e.message, 'error');
  } finally {
    if (btn) { btn.disabled = false; btn.textContent = 'Done (Dismiss)'; }
  }
}
