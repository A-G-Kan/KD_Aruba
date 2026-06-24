// ============================================================
//  KD Aruba — script.js
//
//  DATA FORMAT NOTE FOR AI AGENT:
//  When your monitoring agent updates listings, it should write
//  to the `listings` array below (or replace this file with a
//  version that loads from listings.json via fetch).
//  Each listing object must match the schema shown below.
// ============================================================


// ============================================================
//  AUTH
//  Multi-user login — add/remove entries in USERS to manage access.
// ============================================================

const USERS = {
    "AK": "123",
    "EK": "123",
    "JD": "123"
};

function checkAuth() {
    const user = localStorage.getItem("kd_user");
    if (user && USERS[user]) {
        showApp();
    } else {
        document.getElementById("landing-page").style.display = "flex";
        document.getElementById("app-shell").style.display = "none";
    }
}

function showLogin() {
    document.getElementById("landing-page").style.display = "none";
    document.getElementById("login-page").style.display = "flex";
    setTimeout(() => document.getElementById("login-username").focus(), 80);
}

function showLanding() {
    document.getElementById("login-page").style.display = "none";
    document.getElementById("landing-page").style.display = "flex";
    document.getElementById("login-error").textContent = "";
    document.getElementById("login-username").value = "";
    document.getElementById("login-password").value = "";
}

function doLogin() {
    const username = document.getElementById("login-username").value.trim().toUpperCase();
    const pw       = document.getElementById("login-password").value;
    const err      = document.getElementById("login-error");

    if (USERS[username] && pw === USERS[username]) {
        localStorage.setItem("kd_user", username);
        document.getElementById("login-page").style.display = "none";
        showApp();
    } else {
        err.textContent = "Incorrect username or password. Try again.";
        document.getElementById("login-password").value = "";
        document.getElementById("login-password").focus();
    }
}

function showApp() {
    document.getElementById("landing-page").style.display = "none";
    document.getElementById("login-page").style.display = "none";
    document.getElementById("app-shell").style.display = "contents";
    updateUserUI();
    loadTheme();
    loadSidebarState();
}

function doLogout() {
    localStorage.removeItem("kd_user");
    document.body.removeAttribute("data-user");
    resetTheme();
    document.getElementById("app-shell").style.display = "none";
    showLanding();
}

function updateUserUI() {
    const user = localStorage.getItem("kd_user") || "";
    // Top-right badge
    const badge = document.getElementById("user-badge");
    if (badge) badge.textContent = user;
    // Dashboard greeting
    const greetingUser = document.getElementById("greeting-user");
    if (greetingUser) greetingUser.textContent = user || "KD Team";
    // Sidebar & mobile logo badges — replace KD with user initials
    document.querySelectorAll(".logo-badge").forEach(el => {
        el.textContent = user || "KD";
    });
    // Set data-user on body for per-user avatar styling
    if (user) {
        document.body.setAttribute("data-user", user.toLowerCase());
    } else {
        document.body.removeAttribute("data-user");
    }
}


// ============================================================
//  DATA — loaded from data.json at runtime
//  Agents update data.json directly; the site reads it on load.
//
//  listings schema:
//    status:       "active" | "price reduced" | "under offer" | "sold" | "expired"
//    type:         "land" | "house" | "condo" | "commercial"
//    listedDate:   "YYYY-MM-DD"
//    sourceUrl:    full URL to the original listing
//    priceHistory: array of { date, price } — agent appends on changes
// ============================================================

let listings     = [];
let agentMeta    = { lastSync: null, agentActive: false, totalSyncCount: 0 };
let trackerItems = [];
let monthlyData  = [];
let areaData     = [];

// ── Currency toggle ────────────────────────────────────────────────────────
const AWG_PER_USD = 1.79;
let activeCurrency = 'USD';

function formatPrice(usdPrice) {
    if (usdPrice == null) return 'Price on request';
    if (activeCurrency === 'AWG') {
        const awg = Math.round(usdPrice * AWG_PER_USD);
        return 'Afl. ' + awg.toLocaleString();
    }
    return '$' + usdPrice.toLocaleString();
}

function setCurrency(cur) {
    activeCurrency = cur;
    document.getElementById('btn-usd').classList.toggle('active', cur === 'USD');
    document.getElementById('btn-awg').classList.toggle('active', cur === 'AWG');
    // Re-render all current views that show prices
    refreshPriceDisplays();
}

function refreshPriceDisplays() {
    // Re-render the paginated listings grid and home snapshot
    if (typeof applyListingFilters === 'function') applyListingFilters();
    renderListingsGrid(listings.slice(0, 4), 'home-listings-grid');
}


// ============================================================
//  INIT
// ============================================================

// ============================================================
//  THEME SWITCHER
// ============================================================

const THEMES = {
    classic: {
        name: 'Classic',
        sidebar: '#27272A',
        bg: '#F7F7F8',
        surface: '#FFFFFF',
        accent: '#3F3F46'
    },
    dark: {
        name: 'Dark',
        sidebar: '#1C1C1E',
        bg: '#2C2C2E',
        surface: '#3A3A3C',
        accent: '#D4D4D8'
    },
    bloomberg: {
        name: 'Bloomberg',
        sidebar: '#000000',
        bg: '#000000',
        surface: '#0D0D0D',
        accent: '#FF6600'
    },
    'teal-dark': {
        name: 'Teal Dark',
        sidebar: '#0A1020',
        bg: '#0C1420',
        surface: '#14202E',
        accent: '#2DD4BF'
    },
    'teal-light': {
        name: 'Teal Light',
        sidebar: '#134E4A',
        bg: '#F0F9F8',
        surface: '#FFFFFF',
        accent: '#0D9488'
    }
};

let currentTheme = 'classic';

function setTheme(themeKey) {
    currentTheme = themeKey;
    if (themeKey === 'classic') {
        document.documentElement.removeAttribute('data-theme');
    } else {
        document.documentElement.setAttribute('data-theme', themeKey);
    }
    // Save per user
    const user = localStorage.getItem('kd_user');
    if (user) localStorage.setItem('kd_theme_' + user, themeKey);
    updateThemeSwitcherUI();
    closeThemePanel();
}

function loadTheme() {
    const user  = localStorage.getItem('kd_user');
    const raw   = (user && localStorage.getItem('kd_theme_' + user)) || 'classic';
    const saved = THEMES[raw] ? raw : 'classic';
    currentTheme = saved;
    if (saved === 'classic') {
        document.documentElement.removeAttribute('data-theme');
    } else {
        document.documentElement.setAttribute('data-theme', saved);
    }
    updateThemeSwitcherUI();
}

function resetTheme() {
    currentTheme = 'classic';
    document.documentElement.removeAttribute('data-theme');
    updateThemeSwitcherUI();
}

function toggleThemePanel() {
    const panel = document.getElementById('theme-panel');
    panel.classList.toggle('open');
    if (panel.classList.contains('open')) {
        setTimeout(() => document.addEventListener('click', closePanelOutside), 10);
    }
}

function closePanelOutside(e) {
    const switcher = document.getElementById('theme-switcher');
    if (switcher && !switcher.contains(e.target)) closeThemePanel();
}

function closeThemePanel() {
    const panel = document.getElementById('theme-panel');
    if (panel) panel.classList.remove('open');
    document.removeEventListener('click', closePanelOutside);
}

function updateThemeSwitcherUI() {
    const t = THEMES[currentTheme];
    if (!t) return;

    const swatch = document.getElementById('theme-mini-swatch');
    if (swatch) {
        swatch.innerHTML = `
            <div style="background:${t.sidebar}"></div>
            <div style="background:${t.accent}"></div>
            <div style="background:${t.bg}"></div>
            <div style="background:${t.surface}"></div>
        `;
    }

    const grid = document.getElementById('theme-options-grid');
    if (grid) {
        grid.innerHTML = Object.entries(THEMES).map(([key, theme]) => `
            <div class="theme-option${currentTheme === key ? ' active' : ''}" onclick="setTheme('${key}')">
                <div class="theme-option-preview">
                    <div class="theme-option-sidebar" style="background:${theme.sidebar}"></div>
                    <div class="theme-option-body" style="background:${theme.bg}">
                        <div class="theme-option-bar" style="background:${theme.surface}"></div>
                        <div class="theme-option-bar short" style="background:${theme.surface}"></div>
                        <div class="theme-option-dot" style="background:${theme.accent}"></div>
                    </div>
                </div>
                <div class="theme-option-name">${theme.name}</div>
            </div>
        `).join('');
    }
}


document.addEventListener('DOMContentLoaded', () => {
    checkAuth();
    setDate();
    setGreeting();
    fetch('data.json')
        .then(r => r.json())
        .then(data => {
            listings     = data.listings     || [];
            agentMeta    = data.agentMeta    || agentMeta;
            trackerItems = data.trackerItems || [];
            monthlyData  = data.monthlyData  || [];
            areaData     = data.areaData     || [];
            initApp();
        })
        .catch(() => initApp());
});

function initApp() {
    initSidebarNav();
    renderDashboardStats();
    renderListingsGrid(listings, 'home-listings-grid', 4);
    renderListingStats();
    renderTrackerTable(trackerItems);
    renderTrackerStats();
    loadFavorites();
    initAreaTabs();
    renderAreaOverview('all');
    renderAreaCards();
    renderAreaTable();
    initListingFilters();
    initTrackerFilters();
    setAgentStatus();
    loadNotes();
}


// ============================================================
//  UTILITY
// ============================================================

function setDate() {
    const el = document.getElementById('sidebar-date');
    if (el) el.textContent = new Date().toLocaleDateString('en-US', {
        weekday: 'short', month: 'short', day: 'numeric', year: 'numeric'
    });
}

function setGreeting() {
    const h = new Date().getHours();
    const el = document.getElementById('greeting-time');
    if (el) el.textContent = h < 12 ? 'morning' : h < 18 ? 'afternoon' : 'evening';
}

function daysOnMarket(dateStr) {
    const listed = new Date(dateStr);
    const today  = new Date();
    return Math.floor((today - listed) / (1000 * 60 * 60 * 24));
}

function formatType(t) {
    return { land: 'Land', house: 'House', condo: 'Condo', commercial: 'Commercial' }[t] || t;
}


// ============================================================
//  SIDEBAR & NAVIGATION
// ============================================================

function initSidebarNav() {
    document.querySelectorAll('.nav-item').forEach(btn => {
        btn.addEventListener('click', () => {
            goToPage(btn.dataset.page);
            document.getElementById('sidebar').classList.remove('open');
            document.getElementById('sidebar-overlay').classList.remove('open');
        });
    });
}

function goToPage(pageId) {
    document.querySelectorAll('.nav-item').forEach(b =>
        b.classList.toggle('active', b.dataset.page === pageId));
    document.querySelectorAll('.page').forEach(p =>
        p.classList.toggle('active', p.id === 'page-' + pageId));
    window.scrollTo(0, 0);
}

function toggleSidebar() {
    document.getElementById('sidebar').classList.toggle('open');
    document.getElementById('sidebar-overlay').classList.toggle('open');
}

function toggleSidebarCollapse() {
    const shell = document.getElementById('app-shell');
    const collapsed = shell.classList.toggle('sidebar-collapsed');
    localStorage.setItem('kd_sidebar_collapsed', collapsed ? '1' : '0');
}

function loadSidebarState() {
    if (localStorage.getItem('kd_sidebar_collapsed') === '1') {
        document.getElementById('app-shell').classList.add('sidebar-collapsed');
    }
}


// ============================================================
//  AGENT STATUS
// ============================================================

function setAgentStatus() {
    const dot  = document.querySelector('.agent-dot');
    const text = document.getElementById('agent-status-text');
    const lastUpdated = document.getElementById('last-updated-label');
    const syncEl = document.getElementById('last-sync-time');

    // Sidebar agent status
    if (agentMeta.agentActive) {
        if (dot) dot.classList.add('active');
        if (text) text.textContent = 'Agent connected';
    } else {
        if (text) text.textContent = 'Awaiting agent';
    }

    const syncLabel = agentMeta.lastSync
        ? new Date(agentMeta.lastSync).toLocaleString('en-US', {
            timeZone: 'America/Aruba',
            month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit'
          })
        : 'never';

    if (lastUpdated) lastUpdated.textContent = agentMeta.lastSync ? `Updated ${syncLabel}` : '';
    if (syncEl) syncEl.textContent = syncLabel;

    // Listings page banner
    const bannerDot    = document.getElementById('agent-banner-dot');
    const bannerStatus = document.getElementById('agent-banner-status');
    if (bannerDot && bannerStatus) {
        if (agentMeta.agentActive) {
            bannerDot.classList.add('active');
            bannerStatus.textContent = 'Active';
            bannerStatus.classList.add('active');
        } else {
            bannerDot.classList.remove('active');
            bannerStatus.textContent = 'Inactive';
            bannerStatus.classList.remove('active');
        }
    }
}


// ============================================================
//  DASHBOARD
// ============================================================

function renderDashboardStats() {
    const active   = listings.filter(l => l.status === 'active' || l.status === 'price reduced');
    const reduced  = listings.filter(l => l.status === 'price reduced');
    const watching = trackerItems.filter(t => t.stage !== 'passed');

    document.getElementById('hs-total').textContent    = listings.length;
    document.getElementById('hs-active').textContent   = active.length;
    document.getElementById('hs-watching').textContent = watching.length;
    document.getElementById('hs-reduced').textContent  = reduced.length;

    const activeListings = listings.filter(l => l.status === 'active' || l.status === 'price reduced');
    document.getElementById('hc-listings-count').textContent =
        `${activeListings.length} active · ${listings.length} total tracked`;
    const activeTracker = trackerItems.filter(t => t.stage !== 'passed');
    document.getElementById('hc-tracker-count').textContent =
        `${activeTracker.length} active · ${trackerItems.length} total`;
}


// ============================================================
//  MARKET LISTINGS
// ============================================================

function renderListingStats() {
    document.getElementById('l-total').textContent   = listings.length;
    document.getElementById('l-active').textContent  = listings.filter(l => l.status === 'active').length;
    document.getElementById('l-reduced').textContent = listings.filter(l => l.status === 'price reduced').length;
    document.getElementById('l-offer').textContent   = listings.filter(l => l.status === 'under offer').length;
}

function renderListingsGrid(list, gridId, limit = null) {
    const grid = document.getElementById(gridId);
    if (!grid) return;
    grid.innerHTML = '';

    const items = limit ? list.slice(0, limit) : list;

    if (items.length === 0) {
        grid.innerHTML = `<div class="empty-state"><div class="empty-icon">🔍</div><p>No listings match your filters.</p></div>`;
        return;
    }

    items.forEach(l => {
        const dom   = daysOnMarket(l.listedDate);
        const priceReduced = l.priceHistory.length > 1;
        const prevPrice    = priceReduced ? l.priceHistory[l.priceHistory.length - 2].price : null;
        const card = document.createElement('div');
        const inTracker   = trackerItems.some(t => t.listingId === l.id);
        const trackerItem = trackerItems.find(t => t.listingId === l.id);
        card.className = 'listing-card' + (inTracker ? ' in-tracker' : '');
        card.onclick = () => openListingModal(l);
        card.innerHTML = `
            <div class="card-img-wrap ${l.type}">
                ${l.image
                    ? `<img src="${l.image}" alt="${l.name}" class="card-img" onerror="this.style.display='none'">`
                    : ''}
                <div class="card-img-badges">
                    <span class="card-type-label">${formatType(l.type)}</span>
                    ${priceReduced ? `<span class="price-reduced-tag">Price Reduced</span>` : ''}
                </div>
                ${inTracker ? `<span class="in-tracker-tag">Tracking</span>` : ''}
            </div>
            <div class="card-body">
                <div class="card-top">
                    <div class="card-name">${l.name}</div>
                    <span class="status-badge ${l.status.replace(' ', '-')}">${l.status}</span>
                </div>
                <div class="card-location">${l.location}</div>
                ${(() => {
                    const beds  = l.bedrooms  != null ? (l.bedrooms === 0 ? 'Studio' : `${l.bedrooms} bed`) : null;
                    const baths = l.bathrooms != null ? `${l.bathrooms} bath` : null;
                    const sz    = l.size || null;
                    const parts = [beds, baths, sz].filter(Boolean);
                    return parts.length ? `<div class="card-specs">${parts.join(' · ')}</div>` : '';
                })()}
                <div class="card-meta">
                    <div>
                        <div class="card-price">${formatPrice(l.askPrice)}</div>
                        ${priceReduced ? `<div class="card-prev-price">was ${formatPrice(prevPrice)}</div>` : ''}
                        <div class="card-ppsm">${formatPricePerSqm(l.askPrice, l.size)}</div>
                    </div>
                    <div class="card-agency-block">
                        <div class="card-agency">${l.agency}</div>
                        <div class="card-dom">${dom}d on market</div>
                    </div>
                </div>
                ${inTracker
                    ? `<div class="tracker-btn-group">
                        <button class="add-to-tracker-btn already-tracking" onclick="event.stopPropagation(); goToPage('tracker')">View in Tracker</button>
                        <button class="remove-from-tracker-btn" onclick="event.stopPropagation(); removeDeal(${trackerItem.id})">× Remove</button>
                       </div>`
                    : `<button class="add-to-tracker-btn" onclick="event.stopPropagation(); openAddToTrackerModal(${l.id})">+ Add to Tracker</button>`
                }
            </div>`;
        grid.appendChild(card);
    });
}

function parseSqm(sizeStr) {
    if (!sizeStr) return null;
    const n = parseFloat(sizeStr.replace(/[^0-9.]/g, ''));
    return isNaN(n) ? null : n;
}

function formatPricePerSqm(usdPrice, sizeStr) {
    const sqm = parseSqm(sizeStr);
    if (usdPrice == null || sqm == null || sqm === 0) return 'N/A';
    const usdPerSqm = usdPrice / sqm;
    if (activeCurrency === 'AWG') {
        return 'Afl. ' + Math.round(usdPerSqm * AWG_PER_USD).toLocaleString() + '/m²';
    }
    return '$' + Math.round(usdPerSqm).toLocaleString() + '/m²';
}

// Pagination + filter state (module-level so renderPage can access)
let filteredListings = [];
let currentPage  = 1;
let pageSize     = 50;
let applyListingFilters = null; // set by initListingFilters, used by setCurrency

function initListingFilters() {
    const typeButtons = document.querySelectorAll('[data-lfilter]');
    const statusSel   = document.getElementById('l-status-filter');
    const areaSel     = document.getElementById('l-area-filter');
    const sortSel     = document.getElementById('l-sort');
    const searchInput = document.getElementById('l-search');
    const m2MinInput  = document.getElementById('l-m2-min');
    const m2MaxInput  = document.getElementById('l-m2-max');

    let activeType   = 'all';
    let activeStatus = 'all';
    let activeArea   = 'all';
    let searchTerm   = '';

    function apply() {
        const m2Min  = m2MinInput.value !== '' ? parseFloat(m2MinInput.value) : null;
        const m2Max  = m2MaxInput.value !== '' ? parseFloat(m2MaxInput.value) : null;
        const sortBy = sortSel ? sortSel.value : 'default';

        let result = [...listings];
        if (activeType   !== 'all') result = result.filter(l => l.type === activeType);
        if (activeStatus !== 'all') result = result.filter(l => l.status === activeStatus);
        if (activeArea   !== 'all') result = result.filter(l => l.area === activeArea);
        if (m2Min !== null) result = result.filter(l => { const s = parseSqm(l.size); return s !== null && s >= m2Min; });
        if (m2Max !== null) result = result.filter(l => { const s = parseSqm(l.size); return s !== null && s <= m2Max; });
        if (searchTerm)             result = result.filter(l =>
            l.name.toLowerCase().includes(searchTerm) ||
            l.location.toLowerCase().includes(searchTerm) ||
            l.agency.toLowerCase().includes(searchTerm));

        // Sort — nulls always go to the bottom regardless of direction
        const nullsLast = (aV, bV, dir) => {
            if (aV == null && bV == null) return 0;
            if (aV == null) return 1;
            if (bV == null) return -1;
            return dir === 'asc' ? aV - bV : bV - aV;
        };
        if (sortBy === 'price-asc' || sortBy === 'price-desc') {
            result.sort((a, b) => nullsLast(a.askPrice, b.askPrice, sortBy === 'price-asc' ? 'asc' : 'desc'));
        } else if (sortBy === 'ppsm-asc' || sortBy === 'ppsm-desc') {
            result.sort((a, b) => {
                const aSqm = parseSqm(a.size), bSqm = parseSqm(b.size);
                const aV = (a.askPrice != null && aSqm) ? a.askPrice / aSqm : null;
                const bV = (b.askPrice != null && bSqm) ? b.askPrice / bSqm : null;
                return nullsLast(aV, bV, sortBy === 'ppsm-asc' ? 'asc' : 'desc');
            });
        } else if (sortBy === 'size-asc' || sortBy === 'size-desc') {
            result.sort((a, b) => nullsLast(parseSqm(a.size), parseSqm(b.size), sortBy === 'size-asc' ? 'asc' : 'desc'));
        } else if (sortBy === 'dom-asc' || sortBy === 'dom-desc') {
            // dom-asc = fewest days on market first (newest listing)
            // dom-desc = most days on market first (oldest listing)
            // achieved by sorting listedDate descending / ascending respectively
            result.sort((a, b) => {
                const aV = a.listedDate ? new Date(a.listedDate).getTime() : null;
                const bV = b.listedDate ? new Date(b.listedDate).getTime() : null;
                return nullsLast(aV, bV, sortBy === 'dom-asc' ? 'desc' : 'asc');
            });
        }

        filteredListings = result;
        currentPage = 1;
        renderPage(1);
        document.getElementById('l-results-count').textContent =
            `${result.length} listing${result.length !== 1 ? 's' : ''} found`;
    }

    // expose for currency toggle refresh
    applyListingFilters = apply;

    typeButtons.forEach(btn => btn.addEventListener('click', () => {
        typeButtons.forEach(b => b.classList.remove('active'));
        btn.classList.add('active');
        activeType = btn.dataset.lfilter;
        apply();
    }));

    statusSel.addEventListener('change',   () => { activeStatus = statusSel.value;   apply(); });
    areaSel.addEventListener('change',     () => { activeArea   = areaSel.value;     apply(); });
    if (sortSel) sortSel.addEventListener('change', () => apply());
    m2MinInput.addEventListener('input',   () => apply());
    m2MaxInput.addEventListener('input',   () => apply());
    searchInput.addEventListener('input',  () => { searchTerm = searchInput.value.trim().toLowerCase(); apply(); });

    // Page size buttons
    document.querySelectorAll('.page-size-btn').forEach(btn => {
        btn.addEventListener('click', () => {
            document.querySelectorAll('.page-size-btn').forEach(b => b.classList.remove('active'));
            btn.classList.add('active');
            pageSize = parseInt(btn.dataset.size, 10);
            currentPage = 1;
            renderPage(1);
        });
    });

    // Initial render
    apply();
}

function renderPage(page) {
    currentPage = page;
    const start = (page - 1) * pageSize;
    const pageItems = filteredListings.slice(start, start + pageSize);
    renderListingsGrid(pageItems, 'listings-grid');
    const totalPages = Math.ceil(filteredListings.length / pageSize);
    renderPagination(page, totalPages, 'pagination-top');
    renderPagination(page, totalPages, 'pagination-bottom');
}

function renderPagination(page, totalPages, containerId) {
    const el = document.getElementById(containerId);
    if (!el) return;
    if (totalPages <= 1) { el.innerHTML = ''; return; }

    const start = (page - 1) * pageSize + 1;
    const end   = Math.min(page * pageSize, filteredListings.length);
    let html = '';

    html += `<button class="pg-btn" onclick="renderPage(${page - 1})" ${page === 1 ? 'disabled' : ''}>&#8592; Prev</button>`;

    // Page number buttons with ellipsis for large page counts
    const pages = [];
    if (totalPages <= 7) {
        for (let i = 1; i <= totalPages; i++) pages.push(i);
    } else {
        pages.push(1);
        if (page > 3) pages.push('…');
        for (let i = Math.max(2, page - 1); i <= Math.min(totalPages - 1, page + 1); i++) pages.push(i);
        if (page < totalPages - 2) pages.push('…');
        pages.push(totalPages);
    }

    pages.forEach(p => {
        if (p === '…') {
            html += `<span class="pg-ellipsis">…</span>`;
        } else {
            html += `<button class="pg-btn${p === page ? ' active' : ''}" onclick="renderPage(${p})">${p}</button>`;
        }
    });

    html += `<button class="pg-btn" onclick="renderPage(${page + 1})" ${page === totalPages ? 'disabled' : ''}>Next &#8594;</button>`;
    html += `<span class="pg-label">${start}–${end} of ${filteredListings.length}</span>`;

    el.innerHTML = html;
}


// ============================================================
//  LISTING MODAL
// ============================================================

function openListingModal(l) {
    const dom = daysOnMarket(l.listedDate);
    const priceReduced = l.priceHistory.length > 1;

    // Build price history HTML
    const historyHTML = l.priceHistory.length > 1
        ? `<div style="margin-top:14px;">
            <div class="modal-notes-label">Price History</div>
            <div style="margin-top:6px;">
                ${l.priceHistory.map((h, i) => `
                    <div style="display:flex;justify-content:space-between;font-size:12px;padding:4px 0;border-bottom:1px solid #E5E9F0;">
                        <span style="color:#6B7280;">${h.date}</span>
                        <strong${i === l.priceHistory.length - 1 ? '' : ' style="color:#6B7280;text-decoration:line-through"'}>${formatPrice(h.price)}</strong>
                    </div>`).join('')}
            </div>
          </div>` : '';

    document.getElementById('modal-content').innerHTML = `
        <div class="modal-banner ${l.type}">${l.emoji}</div>
        <div class="modal-body">
            <div style="display:flex;align-items:flex-start;justify-content:space-between;gap:12px;margin-bottom:4px;">
                <div class="modal-title">${l.name}</div>
                <span class="status-badge ${l.status.replace(' ', '-')}">${l.status}</span>
            </div>
            <div class="modal-location">${l.location}</div>
            <div class="modal-row">
                <div class="modal-field">
                    <div class="modal-field-label">Ask Price</div>
                    <div class="modal-field-value">${formatPrice(l.askPrice)}</div>
                </div>
                <div class="modal-field">
                    <div class="modal-field-label">Type</div>
                    <div class="modal-field-value">${formatType(l.type)}</div>
                </div>
                <div class="modal-field">
                    <div class="modal-field-label">Size</div>
                    <div class="modal-field-value">${l.size || 'N/A'}</div>
                </div>
                <div class="modal-field">
                    <div class="modal-field-label">Price / m²</div>
                    <div class="modal-field-value">${formatPricePerSqm(l.askPrice, l.size)}</div>
                </div>
                ${l.bedrooms != null ? `
                <div class="modal-field">
                    <div class="modal-field-label">Beds / Baths</div>
                    <div class="modal-field-value">${l.bedrooms === 0 ? 'Studio' : l.bedrooms} / ${l.bathrooms != null ? l.bathrooms : 'N/A'}</div>
                </div>` : ''}
            </div>
            <div class="modal-row">
                <div class="modal-field">
                    <div class="modal-field-label">Agency</div>
                    <div class="modal-field-value" style="font-size:13px;">${l.agency}</div>
                </div>
                <div class="modal-field">
                    <div class="modal-field-label">Listed</div>
                    <div class="modal-field-value" style="font-size:13px;">${l.listedDate}</div>
                </div>
                <div class="modal-field">
                    <div class="modal-field-label">Days on Market</div>
                    <div class="modal-field-value">${dom}</div>
                </div>
            </div>
            ${l.notes ? `<div style="margin-bottom:12px;"><div class="modal-notes-label">Notes</div><div class="modal-notes-text">${l.notes}</div></div>` : ''}
            ${historyHTML}
            ${l.sourceUrl ? `<div style="margin-top:16px;"><a href="${l.sourceUrl}" target="_blank" class="listing-link-btn">View Original Listing →</a></div>` : `<div style="margin-top:16px;font-size:12px;color:#9CA3AF;">Source URL will be populated by the monitoring agent.</div>`}

            <!-- Tracker & Files section -->
            <div class="modal-actions-bar">
                ${(() => {
                    const ti = trackerItems.find(t => t.listingId === l.id);
                    return ti
                        ? `<div style="display:flex;gap:8px;">
                            <button class="modal-tracker-btn already" style="flex:1;" onclick="closeModal(); goToPage('tracker')">📋 Already in Tracker — View</button>
                            <button class="modal-tracker-btn danger" onclick="removeDeal(${ti.id})">× Remove</button>
                           </div>`
                        : `<button class="modal-tracker-btn" onclick="closeModal(); openAddToTrackerModal(${l.id})">+ Add to Deal Tracker</button>`;
                })()}
            </div>

        </div>`;

    document.getElementById('modal-overlay').classList.add('open');
}

// ============================================================
//  ADD TO TRACKER MODAL
// ============================================================

function openAddToTrackerModal(listingId) {
    const l = listings.find(x => x.id === listingId);
    if (!l) return;

    document.getElementById('modal-content').innerHTML = `
        <div class="modal-body" style="padding-top:24px;">
            <div class="modal-title" style="margin-bottom:4px;">Add to Deal Tracker</div>
            <div class="modal-location" style="margin-bottom:20px;">📍 ${l.name} · ${l.location}</div>

            <div class="tracker-form">
                <div class="tform-row">
                    <div class="tform-field">
                        <label>Priority</label>
                        <select id="tf-priority">
                            <option value="high">▲ High</option>
                            <option value="medium" selected>● Medium</option>
                            <option value="low">▼ Low</option>
                        </select>
                    </div>
                </div>
                <div class="tform-field" style="margin-top:14px;">
                    <label>Notes</label>
                    <textarea id="tf-notes" placeholder="Why are you tracking this? What to investigate next?..." rows="3"></textarea>
                </div>
                <div class="tform-actions">
                    <button class="tform-cancel" onclick="closeModal()">Cancel</button>
                    <button class="tform-submit" onclick="confirmAddToTracker(${l.id})">Add to Tracker →</button>
                </div>
            </div>
        </div>`;
    document.getElementById('modal-overlay').classList.add('open');
}

function confirmAddToTracker(listingId) {
    const l       = listings.find(x => x.id === listingId);
    const stage    = 'viewing';
    const priority = document.getElementById('tf-priority').value;
    const notes    = document.getElementById('tf-notes').value.trim();

    // Add to trackerItems array
    const newItem = {
        id:        trackerItems.length + 1,
        listingId: l.id,
        name:      l.name,
        type:      l.type,
        area:      l.area,
        askPrice:  l.askPrice,
        agency:    l.agency,
        stage,
        priority,
        notes: notes || `Added from market listings on ${new Date().toLocaleDateString()}.`
    };
    trackerItems.push(newItem);

    closeModal();

    // Refresh all affected views
    renderTrackerTable(trackerItems);
    renderTrackerStats();
    renderDashboardStats();
    renderListingsGrid(listings, 'listings-grid');
    renderListingsGrid(listings, 'home-listings-grid', 4);

    // Confirm toast
    showToast(`"${l.name}" added to Deal Tracker`);
}


// ============================================================
//  DEAL DETAIL MODAL
// ============================================================

function openDealDetailModal(item) {
    const comments = getCommentsForDeal(item.id);
    const files    = getFilesForListing(item.id);

    document.getElementById('modal-content').innerHTML = `
        <div class="modal-banner ${item.type}">${
            { land: '🌴', house: '🏡', condo: '🏖️', commercial: '🏢' }[item.type] || '🏠'
        }</div>
        <div class="modal-body">

            <!-- Header -->
            <div style="display:flex;align-items:flex-start;justify-content:space-between;gap:12px;margin-bottom:4px;">
                <div class="modal-title">${item.name}</div>
                <span class="stage-badge ${stageCss[item.stage]}" id="dm-stage-badge">${stageLabels[item.stage]}</span>
            </div>
            <div class="modal-location">${item.area} · ${item.agency}</div>

            <div class="modal-row" style="margin-top:14px;">
                <div class="modal-field">
                    <div class="modal-field-label">Ask Price</div>
                    <div class="modal-field-value">${formatPrice(item.askPrice)}</div>
                </div>
                <div class="modal-field">
                    <div class="modal-field-label">Type</div>
                    <div class="modal-field-value">${formatType(item.type)}</div>
                </div>
                <div class="modal-field">
                    <div class="modal-field-label">Priority</div>
                    <div class="modal-field-value">
                        <span class="priority-badge priority-${item.priority}">
                            ${item.priority === 'high' ? '▲ High' : item.priority === 'medium' ? '● Medium' : '▼ Low'}
                        </span>
                    </div>
                </div>
            </div>

            <!-- Stage -->
            <div class="dm-section-label">Stage</div>
            ${(() => {
                const idx = stageOrder.indexOf(item.stage);
                const hasNext = item.stage !== 'passed' && idx >= 0 && idx < stageOrder.length - 1;
                return hasNext
                    ? `<button class="dm-action-btn" id="dm-advance-btn" onclick="advanceStage(${item.id})">→ Advance to ${stageLabels[stageOrder[idx + 1]]}</button>`
                    : item.stage !== 'passed'
                        ? `<span style="font-size:12px;color:#6B7280;">At final active stage — mark as passed or close the deal below.</span>`
                        : ``;
            })()}

            <!-- Comments -->
            <div class="dm-section-label">Notes & Comments <span style="font-weight:400;color:#9CA3AF;text-transform:none;letter-spacing:0;">(${comments.length})</span></div>
            <div class="dm-comments-list" id="dm-comments-list-${item.id}">
                ${comments.length === 0
                    ? `<div style="font-size:12px;color:#9CA3AF;padding:6px 0;">No comments yet.</div>`
                    : comments.map(c => `
                        <div class="dm-comment-entry">
                            <div class="dm-comment-ts">${new Date(c.ts).toLocaleString('en-US', { month:'short', day:'numeric', year:'numeric', hour:'2-digit', minute:'2-digit' })}</div>
                            <div>${c.text}</div>
                        </div>`).join('')}
            </div>
            <div class="tform-field">
                <textarea id="dm-new-comment" placeholder="Add a note or comment..." rows="2"></textarea>
            </div>
            <button class="tform-submit" style="margin-top:8px;width:100%;" onclick="addDealComment(${item.id})">Add Comment</button>

            <!-- Files -->
            <div class="dm-section-label">Analysis Files <span style="font-weight:400;color:#9CA3AF;text-transform:none;letter-spacing:0;">(${files.length})</span></div>
            <div class="modal-files-sub">Upload Excel models, PDFs, or any deal analysis for this property.</div>
            <div class="modal-files-list" id="files-list-${item.id}"></div>
            <label class="file-upload-btn" style="margin-top:6px;">
                + Upload File
                <input type="file" multiple accept=".xlsx,.xls,.csv,.pdf,.docx,.doc,.txt"
                    onchange="handleFileUpload(event, ${item.id})">
            </label>

            <!-- Quick Actions -->
            <div class="dm-actions-bar">
                ${item.stage !== 'passed'
                    ? `<button class="dm-action-btn" onclick="updateDealStage(${item.id},'passed');closeModal()">Mark as Passed</button>`
                    : `<button class="dm-action-btn" onclick="updateDealStage(${item.id},'viewing');closeModal()">Reactivate</button>`
                }
                ${item.listingId
                    ? `<button class="dm-action-btn" onclick="closeModal();goToPage('listings')">View Listing</button>`
                    : ''}
                <button class="dm-action-btn danger" onclick="removeDeal(${item.id})">Remove</button>
            </div>

        </div>`;

    document.getElementById('modal-overlay').classList.add('open');
    renderFileList(item.id);
}

function addDealComment(dealId) {
    const input = document.getElementById('dm-new-comment');
    const text  = input.value.trim();
    if (!text) return;

    const comments = getCommentsForDeal(dealId);
    comments.push({ ts: new Date().toISOString(), text });
    saveCommentsForDeal(dealId, comments);
    input.value = '';

    // Re-render just the comments list
    const listEl = document.getElementById(`dm-comments-list-${dealId}`);
    if (listEl) {
        listEl.innerHTML = comments.map(c => `
            <div class="dm-comment-entry">
                <div class="dm-comment-ts">${new Date(c.ts).toLocaleString('en-US', { month:'short', day:'numeric', year:'numeric', hour:'2-digit', minute:'2-digit' })}</div>
                <div>${c.text}</div>
            </div>`).join('');
        listEl.scrollTop = listEl.scrollHeight;
    }

    // Refresh table row hints
    renderTrackerTable(trackerItems);
}


// ============================================================
//  TRACKER FILES MODAL (legacy — kept for compatibility)
// ============================================================

function openTrackerFilesModal(trackerId) {
    const item = trackerItems.find(t => t.id === trackerId);
    if (!item) return;

    document.getElementById('modal-content').innerHTML = `
        <div class="modal-body" style="padding-top:24px;">
            <div class="modal-title" style="margin-bottom:4px;">📎 Analysis Files</div>
            <div class="modal-location" style="margin-bottom:20px;">${item.name} · ${item.area}</div>

            <div class="modal-files-sub">Upload Excel sheets, PDFs, or any analysis documents for this property.</div>
            <div class="modal-files-list" id="files-list-${trackerId}"></div>
            <label class="file-upload-btn" style="margin-top:8px;">
                + Upload File
                <input type="file" multiple accept=".xlsx,.xls,.csv,.pdf,.docx,.doc,.txt"
                    onchange="handleFileUpload(event, ${trackerId}); refreshTrackerFilesModal(${trackerId})">
            </label>
        </div>`;

    document.getElementById('modal-overlay').classList.add('open');
    renderFileList(trackerId);
}

function refreshTrackerFilesModal(trackerId) {
    renderFileList(trackerId);
    // Refresh the Files button count in the table row
    renderTrackerTable(trackerItems.filter(t => {
        const activeFilter = document.querySelector('[data-tfilter].active');
        const f = activeFilter ? activeFilter.dataset.tfilter : 'all';
        return f === 'all' || t.stage === f;
    }));
}


// ============================================================
//  FILE UPLOAD (stored in localStorage per tracker item)
// ============================================================

function getFilesForListing(listingId) {
    return JSON.parse(localStorage.getItem(`kd_files_${listingId}`) || '[]');
}

function saveFilesForListing(listingId, files) {
    localStorage.setItem(`kd_files_${listingId}`, JSON.stringify(files));
}

function getCommentsForDeal(dealId) {
    return JSON.parse(localStorage.getItem(`kd_comments_${dealId}`) || '[]');
}

function saveCommentsForDeal(dealId, comments) {
    localStorage.setItem(`kd_comments_${dealId}`, JSON.stringify(comments));
}

function handleFileUpload(event, listingId) {
    const files    = Array.from(event.target.files);
    const existing = getFilesForListing(listingId);

    files.forEach(file => {
        existing.push({
            name:     file.name,
            size:     file.size,
            type:     file.type,
            uploaded: new Date().toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' })
        });
    });

    saveFilesForListing(listingId, existing);
    renderFileList(listingId);
    event.target.value = '';
}

function renderFileList(listingId) {
    const el = document.getElementById(`files-list-${listingId}`);
    if (!el) return;
    const files = getFilesForListing(listingId);

    if (files.length === 0) {
        el.innerHTML = `<div style="font-size:12px;color:#9CA3AF;padding:8px 0;">No files uploaded yet.</div>`;
        return;
    }

    el.innerHTML = files.map((f, i) => `
        <div class="file-item">
            <span class="file-icon">${fileIcon(f.name)}</span>
            <div class="file-info">
                <div class="file-name">${f.name}</div>
                <div class="file-meta">${formatBytes(f.size)} · Uploaded ${f.uploaded}</div>
            </div>
            <button class="file-delete" onclick="deleteFile(${listingId}, ${i})" title="Remove">✕</button>
        </div>`).join('');
}

function deleteFile(listingId, index) {
    const files = getFilesForListing(listingId);
    files.splice(index, 1);
    saveFilesForListing(listingId, files);
    renderFileList(listingId);
}

function fileIcon(name) {
    const ext = name.split('.').pop().toLowerCase();
    if (['xlsx','xls','csv'].includes(ext)) return '📊';
    if (['pdf'].includes(ext))              return '📄';
    if (['doc','docx'].includes(ext))       return '📝';
    return '📎';
}

function formatBytes(bytes) {
    if (bytes < 1024)       return bytes + ' B';
    if (bytes < 1048576)    return (bytes / 1024).toFixed(1) + ' KB';
    return (bytes / 1048576).toFixed(1) + ' MB';
}


// ============================================================
//  TOAST NOTIFICATION
// ============================================================

function showToast(message) {
    let toast = document.getElementById('kd-toast');
    if (!toast) {
        toast = document.createElement('div');
        toast.id = 'kd-toast';
        document.body.appendChild(toast);
    }
    toast.textContent = message;
    toast.classList.add('show');
    clearTimeout(toast._timer);
    toast._timer = setTimeout(() => toast.classList.remove('show'), 3000);
}


function closeModal() {
    document.getElementById('modal-overlay').classList.remove('open');
}

document.addEventListener('keydown', e => { if (e.key === 'Escape') closeModal(); });


// ============================================================
//  DEAL TRACKER
// ============================================================

const stageLabels = {
    'viewing':       'Viewing',
    'offer':         'Offer Pending',
    'due diligence': 'Due Diligence',
    'passed':        'Passed'
};

const stageCss = {
    'viewing':       'stage-viewing',
    'offer':         'stage-offer',
    'due diligence': 'stage-due-diligence',
    'passed':        'stage-passed'
};

// Forward progression order (passed is a terminal state set separately)
const stageOrder = ['viewing', 'offer', 'due diligence'];

function updateDealStage(dealId, newStage) {
    const item = trackerItems.find(t => t.id === dealId);
    if (!item) return;
    item.stage = newStage;
    const badge = document.getElementById('dm-stage-badge');
    if (badge) {
        badge.className = `stage-badge ${stageCss[newStage]}`;
        badge.textContent = stageLabels[newStage];
    }
    renderTrackerTable(trackerItems);
    renderTrackerStats();
    renderDashboardStats();
    showToast(`Stage updated to "${stageLabels[newStage]}"`);
}

function advanceStage(dealId) {
    const item = trackerItems.find(t => t.id === dealId);
    if (!item) return;
    const idx = stageOrder.indexOf(item.stage);
    if (idx < 0 || idx >= stageOrder.length - 1) return;
    const nextStage = stageOrder[idx + 1];
    updateDealStage(dealId, nextStage);
    const advBtn = document.getElementById('dm-advance-btn');
    if (advBtn) {
        const newIdx = idx + 1;
        if (newIdx >= stageOrder.length - 1) {
            advBtn.style.display = 'none';
        } else {
            advBtn.textContent = `→ Advance to ${stageLabels[stageOrder[newIdx + 1]]}`;
        }
    }
}

function removeDeal(dealId) {
    const item = trackerItems.find(t => t.id === dealId);
    if (!item) return;
    if (item.stage === 'viewing') {
        doRemoveDeal(dealId);
    } else {
        showRemoveConfirmation(dealId);
    }
}

function showRemoveConfirmation(dealId) {
    const item = trackerItems.find(t => t.id === dealId);
    if (!item) return;
    document.getElementById('modal-content').innerHTML = `
        <div class="modal-body" style="padding:40px 24px;text-align:center;">
            <div style="font-size:28px;margin-bottom:14px;">⚠️</div>
            <div class="modal-title" style="margin-bottom:10px;">Remove from Tracker?</div>
            <div style="font-size:13px;color:#6B7280;margin-bottom:28px;">
                <strong>${item.name}</strong> is at <strong>${stageLabels[item.stage] || item.stage}</strong>.
                Removing it will permanently delete it from your deal tracker.
            </div>
            <div style="display:flex;gap:12px;justify-content:center;">
                <button class="dm-action-btn" style="min-width:90px;" onclick="closeModal()">Keep</button>
                <button class="dm-action-btn danger" style="min-width:90px;" onclick="doRemoveDeal(${dealId})">Remove</button>
            </div>
        </div>`;
    document.getElementById('modal-overlay').classList.add('open');
}

function doRemoveDeal(dealId) {
    const item = trackerItems.find(t => t.id === dealId);
    const name = item ? item.name : '';
    trackerItems = trackerItems.filter(t => t.id !== dealId);
    closeModal();
    renderTrackerTable(trackerItems);
    renderTrackerStats();
    renderDashboardStats();
    renderListingsGrid(listings, 'listings-grid');
    renderListingsGrid(listings, 'home-listings-grid', 4);
    showToast(`"${name}" removed from tracker`);
}

function renderTrackerStats() {
    const active = trackerItems.filter(t => t.stage !== 'passed');
    document.getElementById('tracker-active-count').textContent = active.length;
    document.getElementById('tracker-total-count').textContent  = trackerItems.length;
}

function renderTrackerTable(list) {
    const tbody = document.getElementById('tracker-table-body');
    if (!tbody) return;
    tbody.innerHTML = '';

    if (list.length === 0) {
        tbody.innerHTML = `<tr><td colspan="8" style="text-align:center;padding:40px;color:#6B7280;">No items match this filter.</td></tr>`;
        return;
    }

    list.forEach(item => {
        const tr = document.createElement('tr');
        const fileCount = getFilesForListing(item.id).length;
        const commentCount = getCommentsForDeal(item.id).length;
        tr.classList.add('tracker-row-clickable');
        tr.addEventListener('click', () => openDealDetailModal(item));
        tr.innerHTML = `
            <td>
                <strong>${item.name}</strong>
                ${item.listingId ? `<div style="font-size:11px;color:#9CA3AF;margin-top:2px;">In market listings</div>` : `<div style="font-size:11px;color:#D97706;margin-top:2px;">Off-market / not listed yet</div>`}
            </td>
            <td>${formatType(item.type)}</td>
            <td>📍 ${item.area}</td>
            <td>${formatPrice(item.askPrice)}</td>
            <td style="font-size:12px;color:#6B7280;">${item.agency}</td>
            <td><span class="stage-badge ${stageCss[item.stage]}">${stageLabels[item.stage]}</span></td>
            <td><span class="priority-badge priority-${item.priority}">${item.priority === 'high' ? '▲ High' : item.priority === 'medium' ? '● Med' : '▼ Low'}</span></td>
            <td>
                <div class="tracker-row-hints">
                    ${fileCount > 0 ? `<span class="row-hint">${fileCount} file${fileCount > 1 ? 's' : ''}</span>` : ''}
                    ${commentCount > 0 ? `<span class="row-hint">${commentCount} note${commentCount > 1 ? 's' : ''}</span>` : ''}
                    <span class="row-open-hint">Open →</span>
                </div>
                <button class="row-remove-btn" onclick="event.stopPropagation(); removeDeal(${item.id})" title="Remove">×</button>
            </td>`;
        tbody.appendChild(tr);
    });
}

function initTrackerFilters() {
    document.querySelectorAll('[data-tfilter]').forEach(btn => {
        btn.addEventListener('click', () => {
            document.querySelectorAll('[data-tfilter]').forEach(b => b.classList.remove('active'));
            btn.classList.add('active');
            const f = btn.dataset.tfilter;
            renderTrackerTable(f === 'all' ? trackerItems : trackerItems.filter(t => t.stage === f));
        });
    });
}


// ============================================================
//  FAVORITES
// ============================================================

let favorites = new Set();

function loadFavorites() {
    const saved = localStorage.getItem('kd_fav_areas');
    // Default: Noord favorited if nothing saved yet
    favorites = new Set(saved ? JSON.parse(saved) : ['Noord']);
    updateFavStars();
}

function saveFavorites() {
    localStorage.setItem('kd_fav_areas', JSON.stringify([...favorites]));
}

function toggleFav(event, areaName) {
    event.stopPropagation(); // don't trigger tab switch
    if (favorites.has(areaName)) {
        favorites.delete(areaName);
    } else {
        favorites.add(areaName);
    }
    saveFavorites();
    updateFavStars();
    // Re-render comparison cards/table so stars update there too
    renderAreaCards();
    renderAreaTable();
    // If currently viewing this area, re-render its header
    const activeTab = document.querySelector('.area-tab.active');
    if (activeTab && activeTab.dataset.area === areaName) {
        renderAreaOverview(areaName);
    }
}

function updateFavStars() {
    document.querySelectorAll('.fav-btn').forEach(btn => {
        const area = btn.dataset.fav;
        const isFav = favorites.has(area);
        btn.textContent = isFav ? '★' : '☆';
        btn.classList.toggle('is-fav', isFav);
    });
}


// ============================================================
//  MARKET ANALYSIS — AREA TABS
// ============================================================

function initAreaTabs() {
    document.querySelectorAll('.area-tab').forEach(btn => {
        btn.addEventListener('click', () => {
            document.querySelectorAll('.area-tab').forEach(b => b.classList.remove('active'));
            btn.classList.add('active');
            renderAreaOverview(btn.dataset.area);
        });
    });
}

// Derive area-specific monthly estimates by scaling Aruba-wide data
// using each area's performance ratio relative to the Aruba average
const ARUBA_AVG = { adrHigh: 352, adrLow: 213, occHigh: 85, occLow: 62 };

function getAreaMonthly(area) {
    const adrHighRatio = area.adrHigh / ARUBA_AVG.adrHigh;
    const adrLowRatio  = area.adrLow  / ARUBA_AVG.adrLow;
    const occHighRatio = area.occHigh  / ARUBA_AVG.occHigh;
    const occLowRatio  = area.occLow   / ARUBA_AVG.occLow;

    return monthlyData.map(m => ({
        ...m,
        adr:       Math.round(m.adr       * (m.season === 'high' ? adrHighRatio : adrLowRatio)),
        occupancy: Math.round(m.occupancy * (m.season === 'high' ? occHighRatio : occLowRatio))
    }));
}

function renderAllArubaOverview() {
    const overviewEl = document.getElementById('area-overview');

    // Compute averages across all areas for the summary row
    const avg = (key) => Math.round(areaData.reduce((s, a) => s + a[key], 0) / areaData.length);
    const revparHigh = Math.round((ARUBA_AVG.occHigh / 100) * ARUBA_AVG.adrHigh);
    const revparLow  = Math.round((ARUBA_AVG.occLow  / 100) * ARUBA_AVG.adrLow);

    // Favorited areas summary
    const favAreas = areaData.filter(a => favorites.has(a.name));
    const favSummary = favAreas.length > 0
        ? `<div class="fav-summary">⭐ Favorited: ${favAreas.map(a =>
            `<span style="color:${a.color};font-weight:600;">${a.name}</span>`).join(', ')}</div>`
        : `<div class="fav-summary" style="color:#9CA3AF;">No areas favorited yet — click ☆ on any tab to save your focus areas.</div>`;

    overviewEl.innerHTML = `
        <div class="area-identity" style="border-left: 4px solid #1B2B4B;">
            <div class="area-identity-left">
                <div class="area-identity-name">All Aruba — Market Overview</div>
                <div class="area-identity-tag">Island-wide averages across all tracked areas</div>
            </div>
            <div class="area-identity-prices">
                <div class="area-price-item">
                    <span class="area-price-label">Avg Land / m²</span>
                    <span class="area-price-val">$${avg('landPerSqm')}</span>
                </div>
                <div class="area-price-item">
                    <span class="area-price-label">Avg Villa</span>
                    <span class="area-price-val">$${avg('avgVilla').toLocaleString()}</span>
                </div>
            </div>
        </div>

        ${favSummary}

        <h2 class="sub-heading" style="margin-top:24px;">Key Metrics — All Aruba</h2>
        <div class="metrics-grid">
            <div class="metric-card season-high">
                <div class="metric-season-tag">High Season</div>
                <div class="metric-label">Occupancy Rate</div>
                <div class="metric-value">${ARUBA_AVG.occHigh}%</div>
                <div class="metric-sub">Dec – Apr avg</div>
            </div>
            <div class="metric-card season-low">
                <div class="metric-season-tag">Low Season</div>
                <div class="metric-label">Occupancy Rate</div>
                <div class="metric-value">${ARUBA_AVG.occLow}%</div>
                <div class="metric-sub">May – Nov avg</div>
            </div>
            <div class="metric-card season-high">
                <div class="metric-season-tag">High Season</div>
                <div class="metric-label">ADR</div>
                <div class="metric-value">$${ARUBA_AVG.adrHigh}</div>
                <div class="metric-sub">Avg Daily Rate</div>
            </div>
            <div class="metric-card season-low">
                <div class="metric-season-tag">Low Season</div>
                <div class="metric-label">ADR</div>
                <div class="metric-value">$${ARUBA_AVG.adrLow}</div>
                <div class="metric-sub">Avg Daily Rate</div>
            </div>
            <div class="metric-card neutral">
                <div class="metric-season-tag">High Season</div>
                <div class="metric-label">RevPAR</div>
                <div class="metric-value">$${revparHigh}</div>
                <div class="metric-sub">Revenue per Avail. Room</div>
            </div>
            <div class="metric-card neutral">
                <div class="metric-season-tag">Low Season</div>
                <div class="metric-label">RevPAR</div>
                <div class="metric-value">$${revparLow}</div>
                <div class="metric-sub">Revenue per Avail. Room</div>
            </div>
        </div>

        <h2 class="sub-heading" style="margin-top:36px;">Monthly Breakdown — All Aruba</h2>
        <div class="table-wrapper">
            <table class="market-table">
                <thead>
                    <tr><th>Month</th><th>Season</th><th>Occupancy</th><th>ADR</th><th>RevPAR</th><th>Notes</th></tr>
                </thead>
                <tbody>
                    ${monthlyData.map(row => {
                        const revpar = Math.round((row.occupancy / 100) * row.adr);
                        return `<tr>
                            <td><strong>${row.month}</strong></td>
                            <td><span class="season-chip ${row.season}">${row.season === 'high' ? 'High' : 'Low'}</span></td>
                            <td>
                                <div class="occ-bar-wrap">
                                    <div class="occ-bar ${row.season}" style="width:${row.occupancy * 0.8}px;max-width:80px;"></div>
                                    <span>${row.occupancy}%</span>
                                </div>
                            </td>
                            <td>$${row.adr}</td>
                            <td>$${revpar}</td>
                            <td style="color:#6B7280;font-style:italic;font-size:12px;">${row.notes}</td>
                        </tr>`;
                    }).join('')}
                </tbody>
            </table>
        </div>

        <div class="comparison-divider"></div>
    `;
}

function renderAreaOverview(areaName) {
    if (areaName === 'all') {
        renderAllArubaOverview();
        return;
    }

    const area = areaData.find(a => a.name === areaName);
    if (!area) return;

    const revparHigh = Math.round((area.occHigh / 100) * area.adrHigh);
    const revparLow  = Math.round((area.occLow  / 100) * area.adrLow);
    const monthly    = getAreaMonthly(area);
    const isFav      = favorites.has(areaName);

    const overviewEl = document.getElementById('area-overview');
    overviewEl.innerHTML = `
        <!-- Area identity bar -->
        <div class="area-identity" style="border-left: 4px solid ${area.color};">
            <div class="area-identity-left">
                <div class="area-identity-name">${area.name} ${isFav ? '<span class="focus-label">★ Favorited</span>' : ''}</div>
                <div class="area-identity-tag">${area.tag} · ${area.profile}</div>
            </div>
            <div class="area-identity-prices">
                <div class="area-price-item">
                    <span class="area-price-label">Avg Land / m²</span>
                    <span class="area-price-val">$${area.landPerSqm}</span>
                </div>
                <div class="area-price-item">
                    <span class="area-price-label">Avg Villa Price</span>
                    <span class="area-price-val">$${area.avgVilla.toLocaleString()}</span>
                </div>
            </div>
        </div>

        <!-- Key metrics -->
        <h2 class="sub-heading" style="margin-top:24px;">Key Metrics — ${area.name}</h2>
        <div class="metrics-grid">
            <div class="metric-card season-high">
                <div class="metric-season-tag">High Season</div>
                <div class="metric-label">Occupancy Rate</div>
                <div class="metric-value">${area.occHigh}%</div>
                <div class="metric-sub">Dec – Apr avg</div>
            </div>
            <div class="metric-card season-low">
                <div class="metric-season-tag">Low Season</div>
                <div class="metric-label">Occupancy Rate</div>
                <div class="metric-value">${area.occLow}%</div>
                <div class="metric-sub">May – Nov avg</div>
            </div>
            <div class="metric-card season-high">
                <div class="metric-season-tag">High Season</div>
                <div class="metric-label">ADR</div>
                <div class="metric-value">$${area.adrHigh}</div>
                <div class="metric-sub">Avg Daily Rate</div>
            </div>
            <div class="metric-card season-low">
                <div class="metric-season-tag">Low Season</div>
                <div class="metric-label">ADR</div>
                <div class="metric-value">$${area.adrLow}</div>
                <div class="metric-sub">Avg Daily Rate</div>
            </div>
            <div class="metric-card neutral">
                <div class="metric-season-tag">High Season</div>
                <div class="metric-label">RevPAR</div>
                <div class="metric-value">$${revparHigh}</div>
                <div class="metric-sub">Revenue per Avail. Room</div>
            </div>
            <div class="metric-card neutral">
                <div class="metric-season-tag">Low Season</div>
                <div class="metric-label">RevPAR</div>
                <div class="metric-value">$${revparLow}</div>
                <div class="metric-sub">Revenue per Avail. Room</div>
            </div>
        </div>

        <!-- Monthly breakdown -->
        <h2 class="sub-heading" style="margin-top:36px;">Monthly Breakdown — ${area.name}</h2>
        <p style="font-size:12px;color:#9CA3AF;margin-bottom:12px;margin-top:-10px;">Estimates derived from Aruba-wide data scaled to ${area.name} performance ratios.</p>
        <div class="table-wrapper">
            <table class="market-table">
                <thead>
                    <tr><th>Month</th><th>Season</th><th>Occupancy</th><th>ADR</th><th>RevPAR</th></tr>
                </thead>
                <tbody>
                    ${monthly.map(row => {
                        const revpar = Math.round((row.occupancy / 100) * row.adr);
                        return `<tr>
                            <td><strong>${row.month}</strong></td>
                            <td><span class="season-chip ${row.season}">${row.season === 'high' ? 'High' : 'Low'}</span></td>
                            <td>
                                <div class="occ-bar-wrap">
                                    <div class="occ-bar ${row.season}" style="width:${row.occupancy * 0.8}px;max-width:80px;"></div>
                                    <span>${row.occupancy}%</span>
                                </div>
                            </td>
                            <td>$${row.adr}</td>
                            <td>$${revpar}</td>
                        </tr>`;
                    }).join('')}
                </tbody>
            </table>
        </div>

        <div class="comparison-divider"></div>
    `;
}


// ============================================================
//  AREA COMPARISON (shown below area overview)
// ============================================================

function renderAreaCards() {
    const grid = document.getElementById('area-grid');
    if (!grid) return;
    grid.innerHTML = '';
    areaData.forEach(area => {
        const revparHigh = Math.round((area.occHigh / 100) * area.adrHigh);
        const isFav = favorites.has(area.name);
        const card = document.createElement('div');
        card.className = 'area-card' + (isFav ? ' area-card-focus' : '');
        card.innerHTML = `
            <div class="area-card-header" style="background:${area.color};">
                <h3>${area.name}</h3>
                <span class="area-tag">${isFav ? '★ · ' : ''}${area.tag}</span>
            </div>
            <div class="area-body">
                <div class="area-row"><span class="area-row-label">Land / m²</span><span class="area-row-value">$${area.landPerSqm}</span></div>
                <div class="area-row"><span class="area-row-label">Avg villa</span><span class="area-row-value">$${area.avgVilla.toLocaleString()}</span></div>
                <div class="area-row"><span class="area-row-label">Occ. high</span><span class="area-row-value">${area.occHigh}%</span></div>
                <div class="area-row"><span class="area-row-label">ADR high</span><span class="area-row-value">$${area.adrHigh}</span></div>
                <div class="area-row"><span class="area-row-label">RevPAR high</span><span class="area-row-value">$${revparHigh}</span></div>
                <div class="area-row" style="border-bottom:none;padding-top:8px;">
                    <span style="font-size:11px;color:#6B7280;font-style:italic;">${area.profile}</span>
                </div>
            </div>`;
        card.addEventListener('click', () => {
            document.querySelectorAll('.area-tab').forEach(b =>
                b.classList.toggle('active', b.dataset.area === area.name));
            renderAreaOverview(area.name);
            document.getElementById('area-overview').scrollIntoView({ behavior: 'smooth' });
        });
        grid.appendChild(card);
    });
}

function renderAreaTable() {
    const tbody = document.getElementById('area-table-body');
    if (!tbody) return;
    tbody.innerHTML = '';
    areaData.forEach(area => {
        const revparHigh = Math.round((area.occHigh / 100) * area.adrHigh);
        const isFav = favorites.has(area.name);
        const tr = document.createElement('tr');
        if (isFav) tr.classList.add('focus-row');
        tr.innerHTML = `
            <td>
                <span style="display:inline-block;width:10px;height:10px;border-radius:50%;background:${area.color};margin-right:8px;vertical-align:middle;"></span>
                <strong>${area.name}</strong>
                ${isFav ? `<span style="font-size:10px;color:#D97706;font-weight:600;margin-left:6px;">★</span>` : ''}
            </td>
            <td>$${area.landPerSqm}/m²</td>
            <td>$${area.avgVilla.toLocaleString()}</td>
            <td>${area.occHigh}%</td>
            <td>${area.occLow}%</td>
            <td>$${area.adrHigh}</td>
            <td>$${area.adrLow}</td>
            <td><strong>$${revparHigh}</strong></td>
            <td style="font-size:12px;color:#6B7280;">${area.profile}</td>`;
        tbody.appendChild(tr);
    });
}


// ============================================================
//  ROI CALCULATOR
// ============================================================

function v(id) { return parseFloat(document.getElementById(id).value) || 0; }

function calcROI() {
    const purchase     = v('roi-purchase');
    const capex        = v('roi-capex');
    const closing      = v('roi-closing');
    const downPct      = v('roi-downpct') / 100;
    const annualRate   = v('roi-rate') / 100;
    const termYears    = v('roi-term');
    const rateHigh     = v('roi-rate-high');
    const occHigh      = v('roi-occ-high') / 100;
    const rateLow      = v('roi-rate-low');
    const occLow       = v('roi-occ-low') / 100;
    const highMonths   = v('roi-high-months');
    const lowMonths    = 12 - highMonths;
    const mgmtPct      = v('roi-mgmt') / 100;
    const hoa          = v('roi-hoa');
    const insurance    = v('roi-insurance');
    const tax          = v('roi-tax');
    const other        = v('roi-other');
    const holdYears    = v('roi-hold');
    const appreciation = v('roi-appreciation') / 100;
    const sellCostPct  = v('roi-sell-cost') / 100;

    const loanAmount    = purchase * (1 - downPct);
    const totalEquityIn = purchase * downPct + capex + closing;

    const daysHigh  = (highMonths / 12) * 365;
    const daysLow   = (lowMonths  / 12) * 365;
    const grossRent = (daysHigh * occHigh * rateHigh) + (daysLow * occLow * rateLow);

    const monthlyRate  = annualRate / 12;
    const numPayments  = termYears * 12;
    let annualMortgage = 0;
    if (loanAmount > 0 && monthlyRate > 0) {
        const mp = loanAmount * (monthlyRate * Math.pow(1 + monthlyRate, numPayments))
                              / (Math.pow(1 + monthlyRate, numPayments) - 1);
        annualMortgage = mp * 12;
    }

    const mgmtFee   = grossRent * mgmtPct;
    const totalOpEx = mgmtFee + hoa + insurance + tax + other;
    const noi       = grossRent - totalOpEx;
    const cashFlow  = noi - annualMortgage;

    const capRate    = purchase > 0 ? (noi / purchase) * 100 : 0;
    const grossYield = purchase > 0 ? (grossRent / purchase) * 100 : 0;
    const cocReturn  = totalEquityIn > 0 ? (cashFlow / totalEquityIn) * 100 : 0;

    const exitValue = purchase * Math.pow(1 + appreciation, holdYears);
    const sellCosts = exitValue * sellCostPct;

    let loanBalance = loanAmount;
    if (loanAmount > 0 && monthlyRate > 0) {
        loanBalance = loanAmount * Math.pow(1 + monthlyRate, holdYears * 12)
                    - (annualMortgage / 12) * (Math.pow(1 + monthlyRate, holdYears * 12) - 1) / monthlyRate;
        loanBalance = Math.max(loanBalance, 0);
    }

    const exitProceeds   = exitValue - sellCosts - loanBalance;
    const totalEquityOut = exitProceeds + (cashFlow * holdYears);

    const cashFlows = [-totalEquityIn];
    for (let y = 1; y <= holdYears; y++) {
        cashFlows.push(y < holdYears ? cashFlow : cashFlow + exitProceeds);
    }
    const irr  = calcIRR(cashFlows);
    const moic = totalEquityIn > 0 ? totalEquityOut / totalEquityIn : 0;

    document.getElementById('roi-results').innerHTML = `
        <div class="roi-results-card">
            <div class="roi-results-title">📊 Deal Summary</div>
            <div class="roi-kpi-grid">
                <div class="roi-kpi highlight">
                    <div class="roi-kpi-label">IRR (${holdYears}-year hold)</div>
                    <div class="roi-kpi-value">${irr !== null ? irr.toFixed(1) + '%' : 'N/A'}</div>
                    <div class="roi-kpi-sub">Internal Rate of Return</div>
                </div>
                <div class="roi-kpi">
                    <div class="roi-kpi-label">MOIC</div>
                    <div class="roi-kpi-value">${moic.toFixed(2)}x</div>
                    <div class="roi-kpi-sub">Equity multiple</div>
                </div>
                <div class="roi-kpi">
                    <div class="roi-kpi-label">Cash-on-Cash</div>
                    <div class="roi-kpi-value">${cocReturn.toFixed(1)}%</div>
                    <div class="roi-kpi-sub">Year 1 return</div>
                </div>
                <div class="roi-kpi">
                    <div class="roi-kpi-label">Cap Rate</div>
                    <div class="roi-kpi-value">${capRate.toFixed(1)}%</div>
                    <div class="roi-kpi-sub">NOI / Purchase price</div>
                </div>
                <div class="roi-kpi">
                    <div class="roi-kpi-label">Gross Yield</div>
                    <div class="roi-kpi-value">${grossYield.toFixed(1)}%</div>
                    <div class="roi-kpi-sub">Gross rent / Purchase</div>
                </div>
            </div>
            <hr class="roi-divider">
            <div class="roi-summary-row"><span>Total Equity In</span><strong>$${Math.round(totalEquityIn).toLocaleString()}</strong></div>
            <div class="roi-summary-row"><span>Gross Annual Rent</span><strong>$${Math.round(grossRent).toLocaleString()}</strong></div>
            <div class="roi-summary-row"><span>Operating Expenses</span><strong>$${Math.round(totalOpEx).toLocaleString()}</strong></div>
            <div class="roi-summary-row"><span>Annual NOI</span><strong>$${Math.round(noi).toLocaleString()}</strong></div>
            <div class="roi-summary-row"><span>Annual Mortgage</span><strong>$${Math.round(annualMortgage).toLocaleString()}</strong></div>
            <div class="roi-summary-row"><span>Annual Cash Flow</span><strong style="color:${cashFlow >= 0 ? '#6EE7B7' : '#FCA5A5'}">$${Math.round(cashFlow).toLocaleString()}</strong></div>
            <hr class="roi-divider">
            <div class="roi-summary-row"><span>Exit Value (Year ${holdYears})</span><strong>$${Math.round(exitValue).toLocaleString()}</strong></div>
            <div class="roi-summary-row"><span>Net Exit Proceeds</span><strong>$${Math.round(exitProceeds).toLocaleString()}</strong></div>
            <div class="roi-summary-row"><span>Total Equity Out</span><strong>$${Math.round(totalEquityOut).toLocaleString()}</strong></div>
            ${cashFlow < 0 ? `<div class="roi-warning" style="display:block;">⚠️ Negative cash flow — this deal requires additional cash each year to cover the mortgage.</div>` : ''}
        </div>`;
}

function calcIRR(cashFlows, guess = 0.1) {
    let rate = guess;
    for (let i = 0; i < 200; i++) {
        let npv = 0, dnpv = 0;
        for (let t = 0; t < cashFlows.length; t++) {
            npv  += cashFlows[t] / Math.pow(1 + rate, t);
            if (t > 0) dnpv -= t * cashFlows[t] / Math.pow(1 + rate, t + 1);
        }
        const newRate = rate - npv / dnpv;
        if (Math.abs(newRate - rate) < 1e-7) return newRate * 100;
        rate = newRate;
    }
    return null;
}


// ============================================================
//  NOTES
// ============================================================

function saveNotes() {
    localStorage.setItem('kd_market_notes', document.getElementById('market-notes').value);
    const msg = document.getElementById('notes-saved-msg');
    msg.textContent = '✓ Saved';
    setTimeout(() => msg.textContent = '', 2500);
}

function loadNotes() {
    const saved = localStorage.getItem('kd_market_notes');
    if (saved) document.getElementById('market-notes').value = saved;
}
