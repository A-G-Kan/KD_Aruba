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
    renderListingsGrid(listings.filter(l => !l.archived && l.status !== 'sold').slice(0, 4), 'home-listings-grid');
    // Re-render analysis tab so $/m² figures switch currency
    const activeAreaTab = document.querySelector('.area-tab.active');
    if (activeAreaTab) renderAnalysisTab(activeAreaTab.dataset.area);
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
            initApp();
        })
        .catch(() => initApp());
});

function initApp() {
    initSidebarNav();
    renderDashboardStats();
    renderListingsGrid(listings.filter(l => !l.archived && l.status !== 'sold'), 'home-listings-grid', 4);
    renderListingStats();
    renderTrackerTable(trackerItems);
    renderTrackerStats();
    buildPpsmData();
    loadFavorites();
    initAreaTabs();
    renderAnalysisTab('all');
    initListingFilters();
    renderArchivedSection();
    initTrackerFilters();
    setAgentStatus();
    loadNotes();
    initPpsmInteractions();
}

function initPpsmInteractions() {
    // Single delegate for all "N listings" buttons — fixes alternating-row click bug
    document.getElementById('page-market').addEventListener('click', e => {
        const btn = e.target.closest('.ppsm-n-btn');
        if (btn) openPpsmDrilldown(btn.dataset.area, btn.dataset.type);
    });

    // Single delegate for drilldown list: row → view listing, excl-btn → toggle exclusion
    document.querySelector('.ppsm-drilldown-panel').addEventListener('click', e => {
        const exclBtn = e.target.closest('.drill-excl-btn');
        if (exclBtn) {
            e.stopPropagation();
            togglePpsmExclusion(exclBtn.dataset.area, exclBtn.dataset.type, exclBtn.dataset.listingId);
            return;
        }
        const row = e.target.closest('.drill-row:not(.drill-excluded)');
        if (row && row.dataset.listingId) jumpToListing(row.dataset.listingId);
    });
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
    return { land: 'Land', house: 'House', condo: 'Condo', commercial: 'Commercial', timeshare: 'Timeshare', unknown: 'Unknown' }[t] || t;
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
    document.getElementById('l-active').textContent  = listings.filter(l => l.status === 'active' && !l.archived).length;
    document.getElementById('l-reduced').textContent = listings.filter(l => l.status === 'price reduced' && !l.archived).length;
    document.getElementById('l-offer').textContent   = listings.filter(l => l.status === 'under offer' && !l.archived).length;
    document.getElementById('l-sold').textContent    = listings.filter(l => l.status === 'sold' && !l.archived).length;
}

// ── Archive ────────────────────────────────────────────────────────────────

let hasUnsavedArchiveChanges = false;

function toggleArchive(id) {
    const l = listings.find(x => x.id === id);
    if (!l) return;
    l.archived = !l.archived;
    hasUnsavedArchiveChanges = true;
    updateExportBanner();
    applyListingFilters();
    renderArchivedSection();
    renderListingStats();
    // Refresh home snapshot (exclude archived)
    renderListingsGrid(listings.filter(x => !x.archived && x.status !== 'sold').slice(0, 4), 'home-listings-grid');
    showToast(l.archived
        ? `"${l.name}" archived — export data.json to share with partners`
        : `"${l.name}" restored to listings`);
}

function renderArchivedSection() {
    const sec     = document.getElementById('archived-section');
    const grid    = document.getElementById('archived-listings-grid');
    const countEl = document.getElementById('archived-section-count');
    if (!sec || !grid) return;

    const archivedListings = listings.filter(l => l.archived === true);
    if (countEl) countEl.textContent = `${archivedListings.length} archived`;

    sec.style.display = archivedListings.length > 0 ? 'block' : 'none';

    if (archivedListings.length === 0) {
        grid.innerHTML = '';
        return;
    }
    renderListingsGrid(archivedListings, 'archived-listings-grid');
}

function exportDataJson() {
    const exportData = {
        listings:     listings,
        agentMeta:    agentMeta,
        trackerItems: trackerItems,
    };
    const blob = new Blob([JSON.stringify(exportData, null, 2)], { type: 'application/json' });
    const url  = URL.createObjectURL(blob);
    const a    = document.createElement('a');
    a.href     = url;
    a.download = 'data.json';
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
    showToast('data.json downloaded — replace the file in your repo, then git commit & push to share with partners');
    hasUnsavedArchiveChanges = false;
    updateExportBanner();
}

function updateExportBanner() {
    const banner = document.getElementById('archive-export-banner');
    if (!banner) return;
    banner.style.display = hasUnsavedArchiveChanges ? 'flex' : 'none';
}

function renderSoldSection() {
    const grid     = document.getElementById('sold-listings-grid');
    const countEl  = document.getElementById('sold-section-count');
    if (!grid) return;

    const soldListings = listings.filter(l => l.status === 'sold' && !l.archived);
    if (countEl) countEl.textContent = `${soldListings.length} sold listing${soldListings.length !== 1 ? 's' : ''}`;

    if (soldListings.length === 0) {
        grid.innerHTML = `<div class="empty-state"><div class="empty-icon">🔍</div><p>No recent sold listings.</p></div>`;
        return;
    }
    renderListingsGrid(soldListings, 'sold-listings-grid');
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
                    const szStr = displaySize(l);
                    const sz    = szStr || null;
                    const parts = [beds, baths, sz].filter(Boolean);
                    return parts.length ? `<div class="card-specs">${parts.join(' · ')}</div>` : '';
                })()}
                <div class="card-meta">
                    <div>
                        <div class="card-price">${formatPrice(l.askPrice)}</div>
                        ${priceReduced ? `<div class="card-prev-price">was ${formatPrice(prevPrice)}</div>` : ''}
                        <div class="card-ppsm">${formatPricePerSqm(l.askPrice, l)}</div>
                    </div>
                    <div class="card-agency-block">
                        <div class="card-agency">${l.agency}</div>
                        <div class="card-dom">${dom}d on market</div>
                    </div>
                </div>
                <div class="card-action-row">
                    ${inTracker
                        ? `<button class="add-to-tracker-btn already-tracking" onclick="event.stopPropagation(); removeDeal(${trackerItem.id})">✓ Tracking — Remove</button>`
                        : `<button class="add-to-tracker-btn" onclick="event.stopPropagation(); openAddToTrackerModal('${l.id}')">+ Add to Tracker</button>`
                    }
                    ${l.archived
                        ? `<button class="archive-btn restore" onclick="event.stopPropagation(); toggleArchive('${l.id}')" title="Restore to main listings">Unarchive</button>`
                        : `<button class="archive-btn" onclick="event.stopPropagation(); toggleArchive('${l.id}')" title="Hide from main listings">Archive</button>`
                    }
                </div>
            </div>`;
        grid.appendChild(card);
    });
}

function parseSqm(sizeStr) {
    if (!sizeStr) return null;
    const n = parseFloat(sizeStr.replace(/[^0-9.]/g, ''));
    return isNaN(n) || n === 0 ? null : n;
}

// Returns the m² to use for $/m² calculations.
// Land → lot size.  Houses/condos/commercial/timeshare → building area only.
// Lot size is NEVER substituted into a house/condo calculation.
function ppsmSqm(l) {
    if (l.type === 'land') {
        const s = parseSqm(l.lotSize) || (!l.buildingSize && !l.lotSize ? parseSqm(l.size) : null);
        return s && s >= 10 ? s : null;
    }
    // Non-land: use building area only; fall back to legacy `size` only when
    // neither new field exists (i.e. data pre-dates the two-field schema).
    const s = parseSqm(l.buildingSize) || (!l.buildingSize && !l.lotSize ? parseSqm(l.size) : null);
    return s && s >= 10 ? s : null;
}

// Returns the best available m² for size filtering/sorting (building > lot > legacy).
function primarySqm(l) {
    return parseSqm(l.buildingSize) || parseSqm(l.lotSize) || parseSqm(l.size) || null;
}

// Returns a human-readable size string with "interior" / "lot" labels as needed.
// Returns '' (not 'N/A') when no size data exists, so callers can substitute.
function displaySize(l) {
    const bStr = (l.buildingSize || '').trim();
    const lStr = (l.lotSize      || '').trim();
    const bSqm = parseSqm(bStr);
    const lSqm = parseSqm(lStr);

    if (bSqm && lSqm) return `${bStr} interior · ${lStr} lot`;
    if (bSqm)         return bStr;      // standard interior area — label not needed
    if (lSqm)         return `${lStr} lot`;

    // Legacy: l.size field (pre-dates the two-field schema)
    const legSqm = parseSqm(l.size || '');
    return legSqm ? l.size : '';
}

function formatPricePerSqm(usdPrice, listingOrStr) {
    const sqm = (listingOrStr && typeof listingOrStr === 'object')
        ? ppsmSqm(listingOrStr)
        : parseSqm(listingOrStr);
    if (usdPrice == null || !sqm) return 'N/A';
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

    let activeType      = 'all';
    let activeStatus    = 'all';
    let activeArea      = 'all';
    let searchTerm      = '';
    let activeAgencies  = new Set(); // empty = All

    function apply() {
        const m2Min  = m2MinInput.value !== '' ? parseFloat(m2MinInput.value) : null;
        const m2Max  = m2MaxInput.value !== '' ? parseFloat(m2MaxInput.value) : null;
        const sortBy = sortSel ? sortSel.value : 'default';

        // Archived listings always live in their own section — never in main grid.
        let result = [...listings].filter(l => !l.archived);
        if (activeAgencies.size > 0) result = result.filter(l => activeAgencies.has(l.agency));
        if (activeType !== 'all') result = result.filter(l => l.type === activeType);

        // Sold listings live in their own section; exclude them from the main
        // grid unless the user has explicitly selected "sold" in the filter.
        if (activeStatus === 'all') {
            result = result.filter(l => l.status !== 'sold');
        } else {
            result = result.filter(l => l.status === activeStatus);
        }

        // Show/hide the dedicated sold section (hidden when user is already
        // browsing sold in the main grid to avoid showing them twice).
        const soldSec = document.getElementById('sold-section');
        if (soldSec) soldSec.style.display = (activeStatus === 'sold') ? 'none' : 'block';
        renderSoldSection();

        if (activeArea   !== 'all') result = result.filter(l => l.area === activeArea);
        if (m2Min !== null) result = result.filter(l => { const s = primarySqm(l); return s !== null && s >= m2Min; });
        if (m2Max !== null) result = result.filter(l => { const s = primarySqm(l); return s !== null && s <= m2Max; });
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
                const aSqm = ppsmSqm(a), bSqm = ppsmSqm(b);
                const aV = (a.askPrice != null && aSqm) ? a.askPrice / aSqm : null;
                const bV = (b.askPrice != null && bSqm) ? b.askPrice / bSqm : null;
                return nullsLast(aV, bV, sortBy === 'ppsm-asc' ? 'asc' : 'desc');
            });
        } else if (sortBy === 'size-asc' || sortBy === 'size-desc') {
            result.sort((a, b) => nullsLast(primarySqm(a), primarySqm(b), sortBy === 'size-asc' ? 'asc' : 'desc'));
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

    // Agency filter
    (function buildAgencyFilter() {
        const bar = document.getElementById('agency-filter-bar');
        if (!bar) return;

        // Count listings per agency (excluding archived), sort by count desc
        const counts = {};
        listings.forEach(l => {
            if (!l.archived && l.agency) counts[l.agency] = (counts[l.agency] || 0) + 1;
        });
        const sortedAgencies = Object.keys(counts).sort((a, b) => counts[b] - counts[a]);

        function refreshButtons() {
            bar.querySelectorAll('.agency-filter-btn').forEach(btn => {
                const isAll = btn.dataset.agency === '__all__';
                btn.classList.toggle('active', isAll ? activeAgencies.size === 0 : activeAgencies.has(btn.dataset.agency));
            });
        }

        // Build DOM
        bar.innerHTML = '';
        const label = document.createElement('span');
        label.className = 'agency-filter-label';
        label.textContent = 'Agency';
        bar.appendChild(label);

        const allBtn = document.createElement('button');
        allBtn.className = 'agency-filter-btn active';
        allBtn.dataset.agency = '__all__';
        allBtn.textContent = 'All';
        allBtn.addEventListener('click', () => {
            activeAgencies.clear();
            refreshButtons();
            apply();
        });
        bar.appendChild(allBtn);

        sortedAgencies.forEach(agency => {
            const btn = document.createElement('button');
            btn.className = 'agency-filter-btn';
            btn.dataset.agency = agency;
            btn.textContent = agency;
            btn.addEventListener('click', () => {
                if (activeAgencies.has(agency)) {
                    activeAgencies.delete(agency);
                } else {
                    activeAgencies.add(agency);
                }
                refreshButtons();
                apply();
            });
            bar.appendChild(btn);
        });
    })();

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
        <div class="modal-banner ${l.type}">
            ${l.image ? `<img src="${l.image}" alt="" class="modal-hero-img" onerror="this.style.display='none'">` : ''}
        </div>
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
                    <div class="modal-field-value">${displaySize(l) || 'N/A'}</div>
                </div>
                <div class="modal-field">
                    <div class="modal-field-label">Price / m²</div>
                    <div class="modal-field-value">${formatPricePerSqm(l.askPrice, l)}</div>
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
                        : `<button class="modal-tracker-btn" onclick="closeModal(); openAddToTrackerModal('${l.id}')">+ Add to Deal Tracker</button>`;
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
                    <button class="tform-submit" onclick="confirmAddToTracker('${l.id}')">Add to Tracker →</button>
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
    renderPage(currentPage);
    renderListingsGrid(listings.filter(l => !l.archived && l.status !== 'sold').slice(0, 4), 'home-listings-grid');

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
    renderPage(currentPage);
    renderListingsGrid(listings.filter(l => !l.archived && l.status !== 'sold').slice(0, 4), 'home-listings-grid');
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
    event.stopPropagation();
    if (favorites.has(areaName)) {
        favorites.delete(areaName);
    } else {
        favorites.add(areaName);
    }
    saveFavorites();
    updateFavStars();
    const activeTab = document.querySelector('.area-tab.active');
    if (activeTab) renderAnalysisTab(activeTab.dataset.area);
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
//  MARKET ANALYSIS — PPSM DATA + RENDERING
// ============================================================

const PPSM_TYPES   = ['house', 'condo', 'land', 'commercial', 'timeshare'];
const PPSM_LABELS  = { house: 'Houses', condo: 'Condos', land: 'Land', commercial: 'Commercial', timeshare: 'Timeshare' };
const MIN_LISTINGS = 5;   // below this: flag as limited data

let ppsmData  = {};   // { [area]: { [type]: [{l, ppsm}] } }
let ppsmAreas = [];   // areas sorted by listing count with valid data

const ppsmExclusions   = new Set();  // keys: "area:type:listingId" — view-only, resets on reload
let   ppsmDrilldownCtx = null;       // { area, type } while drilldown is open

function buildPpsmData() {
    ppsmData = {};
    const areaCounts = {};
    for (const l of listings) {
        const area  = (l.area || '').trim();
        const price = l.askPrice;
        const sqm   = ppsmSqm(l);
        if (!area || !price || !sqm) continue;
        if (!ppsmData[area]) { ppsmData[area] = {}; areaCounts[area] = 0; }
        if (!ppsmData[area][l.type]) ppsmData[area][l.type] = [];
        ppsmData[area][l.type].push({ l, ppsm: price / sqm });
        areaCounts[area]++;
    }
    ppsmAreas = Object.entries(areaCounts)
        .sort((a, b) => b[1] - a[1])
        .filter(([, n]) => n >= 3)
        .map(([a]) => a)
        .slice(0, 14);
}

function medianOf(values) {
    if (!values || !values.length) return null;
    const sv = [...values].sort((a, b) => a - b);
    const mid = Math.floor(sv.length / 2);
    return sv.length % 2 ? sv[mid] : (sv[mid - 1] + sv[mid]) / 2;
}

function ppsmDisplay(usdVal) {
    if (activeCurrency === 'AWG')
        return 'Afl. ' + Math.round(usdVal * AWG_PER_USD).toLocaleString();
    return '$' + Math.round(usdVal).toLocaleString();
}

function buildPpsmCell(entries, area, type) {
    if (!entries || !entries.length)
        return `<td class="ppsm-cell ppsm-empty" data-area="${area}" data-type="${type}"><span class="ppsm-dash">—</span></td>`;
    const n       = entries.length;
    const active  = entries.filter(e => !ppsmExclusions.has(`${area}:${type}:${e.l.id}`));
    const nActive = active.length;
    const hasExcl = nActive < n;
    const limited = nActive < MIN_LISTINGS;
    if (!nActive) {
        return `<td class="ppsm-cell ppsm-limited has-exclusions" data-area="${area}" data-type="${type}">
            <span class="ppsm-val">—</span>
            <button class="ppsm-n-btn" data-area="${area}" data-type="${type}">0 of ${n} listing${n !== 1 ? 's' : ''}</button>
        </td>`;
    }
    const med       = medianOf(active.map(e => e.ppsm));
    const countText = hasExcl ? `${nActive} of ${n}` : `${n}`;
    return `<td class="ppsm-cell ${limited ? 'ppsm-limited' : 'ppsm-ok'}${hasExcl ? ' has-exclusions' : ''}" data-area="${area}" data-type="${type}">
        <span class="ppsm-val">${limited ? '~' : ''}${ppsmDisplay(med)}/m²</span>
        <button class="ppsm-n-btn" data-area="${area}" data-type="${type}">${countText}&nbsp;listing${n !== 1 ? 's' : ''}${limited ? ' ⚠' : ''}</button>
    </td>`;
}

function renderAnalysisTab(areaName) {
    if (areaName === 'all') renderAllArubaAnalysis();
    else                    renderAreaAnalysis(areaName);
}

function initAreaTabs() {
    document.querySelectorAll('.area-tab').forEach(btn => {
        btn.addEventListener('click', () => {
            document.querySelectorAll('.area-tab').forEach(b => b.classList.remove('active'));
            btn.classList.add('active');
            renderAnalysisTab(btn.dataset.area);
        });
    });
}

function renderAllArubaAnalysis() {
    const el = document.getElementById('area-overview');
    if (!el) return;

    const totalListings  = listings.length;
    const totalWithPpsm  = ppsmAreas.reduce((s, a) =>
        s + PPSM_TYPES.reduce((t, tp) => t + (ppsmData[a]?.[tp]?.length || 0), 0), 0);
    const favAreas       = ppsmAreas.filter(a => favorites.has(a));
    const cur            = activeCurrency === 'AWG' ? 'Afl.' : '$';

    const favBanner = favAreas.length
        ? `<div class="fav-summary">★ Watching: ${favAreas.map(a => `<strong>${a}</strong>`).join(', ')}</div>`
        : `<div class="fav-summary muted">Click ☆ on an area tab to add it to your watchlist.</div>`;

    // Build matrix
    let thead = `<tr><th>Area</th>${PPSM_TYPES.map(t => `<th>${PPSM_LABELS[t]}</th>`).join('')}</tr>`;
    let tbody = ppsmAreas.map(area => {
        const isFav = favorites.has(area);
        const cells = PPSM_TYPES.map(t => buildPpsmCell(ppsmData[area]?.[t], area, t)).join('');
        return `<tr class="${isFav ? 'focus-row' : ''}">
            <td class="ppsm-area-name">${isFav ? '★ ' : ''}${area}</td>${cells}
        </tr>`;
    }).join('');

    el.innerHTML = `
        <div class="analysis-band">
            <div>
                <div class="analysis-title">All Aruba — Median ${cur}/m² by Area &amp; Category</div>
                <div class="analysis-sub">${totalWithPpsm} of ${totalListings} listings have both price and size · medians computed in USD, displayed in selected currency</div>
            </div>
        </div>
        ${favBanner}
        <div class="ppsm-legend">
            <span class="legend-ok">■</span> ≥${MIN_LISTINGS} listings — reliable &nbsp;
            <span class="legend-ltd">■</span> &lt;${MIN_LISTINGS} listings ⚠ — limited, treat with caution &nbsp;
            <span class="legend-empty">—</span> no data
        </div>
        <div class="table-wrapper">
            <table class="ppsm-table">
                <thead>${thead}</thead>
                <tbody>${tbody}</tbody>
            </table>
        </div>`;
}

function renderAreaAnalysis(areaName) {
    const el = document.getElementById('area-overview');
    if (!el) return;

    const isFav         = favorites.has(areaName);
    const areaListings  = listings.filter(l => (l.area || '').trim() === areaName);
    const withPpsm      = areaListings.filter(l => l.askPrice && ppsmSqm(l) !== null).length;

    // Bar chart data — only types with at least one listing
    const bars = PPSM_TYPES
        .map(t => ({ type: t, label: PPSM_LABELS[t], vals: ppsmData[areaName]?.[t] }))
        .filter(d => d.vals && d.vals.length);

    let barsHtml;
    if (!bars.length) {
        barsHtml = `<p class="no-data-note">No listings in ${areaName} have both a valid price and size — nothing to chart yet.</p>`;
    } else {
        const maxMed = Math.max(...bars.map(d => {
            const act = d.vals.filter(e => !ppsmExclusions.has(`${areaName}:${d.type}:${e.l.id}`));
            return act.length ? medianOf(act.map(e => e.ppsm)) : medianOf(d.vals.map(e => e.ppsm));
        }));
        barsHtml = `<div class="bar-chart">` + bars.map(d => {
            const allVals  = d.vals;
            const actVals  = allVals.filter(e => !ppsmExclusions.has(`${areaName}:${d.type}:${e.l.id}`));
            const nAll     = allVals.length;
            const nAct     = actVals.length;
            const hasExcl  = nAct < nAll;
            const med      = nAct ? medianOf(actVals.map(e => e.ppsm)) : medianOf(allVals.map(e => e.ppsm));
            const limited  = nAct < MIN_LISTINGS;
            const pct      = Math.max(4, Math.round((med / maxMed) * 100));
            const dispVal  = ppsmDisplay(med);
            const cntText  = hasExcl ? `${nAct} of ${nAll}` : `${nAll}`;
            return `<div class="bar-row">
                <div class="bar-label">${d.label}</div>
                <div class="bar-track">
                    <div class="bar-fill type-${d.type}${limited ? ' bar-limited' : ''}" style="width:${pct}%"></div>
                </div>
                <div class="bar-val">
                    ${limited ? '<span class="tilde">~</span>' : ''}${dispVal}/m²
                    <button class="ppsm-n-btn${hasExcl ? ' has-excl' : ''}" data-area="${areaName}" data-type="${d.type}">${cntText}&nbsp;listing${nAll !== 1 ? 's' : ''}${limited ? ' ⚠' : ''}</button>
                </div>
            </div>`;
        }).join('') + `</div>`;
        if (bars.some(d => d.vals.length < MIN_LISTINGS))
            barsHtml += `<p class="ppsm-limited-note">⚠ Limited data (&lt;${MIN_LISTINGS} listings) — treat with caution.</p>`;
    }

    // Mini cross-area reference for this type (houses across all areas)
    const dominantType = bars.length ? bars.reduce((a, b) => (a.vals.length >= b.vals.length ? a : b)).type : null;
    let refHtml = '';
    if (dominantType) {
        const refLabel = PPSM_LABELS[dominantType];
        const refRows  = ppsmAreas
            .filter(a => ppsmData[a]?.[dominantType]?.length)
            .map(a => {
                const vals    = ppsmData[a][dominantType];
                const med     = medianOf(vals.map(e => e.ppsm));
                const limited = vals.length < MIN_LISTINGS;
                const isThis  = a === areaName;
                return { area: a, med, n: vals.length, limited, isThis };
            })
            .sort((a, b) => b.med - a.med);

        if (refRows.length > 1) {
            const maxMed = refRows[0].med;
            refHtml = `
                <h2 class="sub-heading" style="margin-top:28px;">${refLabel} — All Areas (for context)</h2>
                <div class="bar-chart">` +
                refRows.map(r => {
                    const pct  = Math.max(4, Math.round((r.med / maxMed) * 100));
                    const disp = ppsmDisplay(r.med);
                    return `<div class="bar-row${r.isThis ? ' bar-highlight' : ''}">
                        <div class="bar-label">${r.isThis ? '▶ ' : ''}${r.area}</div>
                        <div class="bar-track">
                            <div class="bar-fill type-${dominantType}${r.limited ? ' bar-limited' : ''}" style="width:${pct}%"></div>
                        </div>
                        <div class="bar-val">
                            ${r.limited ? '<span class="tilde">~</span>' : ''}${disp}/m²
                            <span class="bar-n">${r.n}&nbsp;listing${r.n !== 1 ? 's' : ''}${r.limited ? ' ⚠' : ''}</span>
                        </div>
                    </div>`;
                }).join('') + `</div>`;
        }
    }

    el.innerHTML = `
        <div class="analysis-band">
            <div>
                <div class="analysis-title">${areaName} ${isFav ? '★' : ''}</div>
                <div class="analysis-sub">${areaListings.length} total listings · ${withPpsm} with valid price + size</div>
            </div>
            <button class="fav-toggle-btn" onclick="toggleFav(event,'${areaName}')" data-fav="${areaName}">
                ${isFav ? '★ Watching' : '☆ Watch area'}
            </button>
        </div>
        <h2 class="sub-heading" style="margin-top:20px;">Median $/m² by Property Type — ${areaName}</h2>
        ${barsHtml}
        ${refHtml}`;
}

// ============================================================
//  PPSM DRILLDOWN MODAL
// ============================================================

function jumpToListing(id) {
    const l = listings.find(lx => lx.id === id);
    if (l) openListingModal(l);  // stay on current tab — modal is position:fixed
}

function openPpsmDrilldown(area, type) {
    const entries = ppsmData[area]?.[type];
    if (!entries || !entries.length) return;
    ppsmDrilldownCtx = { area, type };
    document.getElementById('ppsm-drilldown-title').textContent = `${area} — ${PPSM_LABELS[type]}`;
    renderDrilldownList();
    document.getElementById('ppsm-drilldown-overlay').classList.add('open');
}

function renderDrilldownList() {
    if (!ppsmDrilldownCtx) return;
    const { area, type } = ppsmDrilldownCtx;
    const entries = ppsmData[area]?.[type] || [];

    const exclKey  = e => `${area}:${type}:${e.l.id}`;
    const active   = entries.filter(e => !ppsmExclusions.has(exclKey(e))).sort((a, b) => b.ppsm - a.ppsm);
    const excluded = entries.filter(e =>  ppsmExclusions.has(exclKey(e))).sort((a, b) => b.ppsm - a.ppsm);
    const n        = entries.length;
    const nAct     = active.length;
    const nExcl    = excluded.length;
    const med      = nAct ? medianOf(active.map(e => e.ppsm)) : null;
    const halfIdx  = nAct >= 3 ? Math.ceil(nAct / 2) - 1 : -1;

    document.getElementById('ppsm-drilldown-sub').textContent =
        `${nAct}${nExcl ? ` of ${n}` : ''} listing${n !== 1 ? 's' : ''}`
        + (nExcl ? ` · ${nExcl} excluded` : '')
        + (med    ? ` · Median ${ppsmDisplay(med)}/m²` : '')
        + ` · Sorted by $/m² high → low`;

    const makeRow = (e, rank, isExcl, isMed) =>
        `<div class="drill-row${isMed ? ' drill-median-row' : ''}${isExcl ? ' drill-excluded' : ''}" data-listing-id="${e.l.id}">
            <span class="drill-rank">${isExcl ? '—' : rank}</span>
            <span class="drill-name">${e.l.name}</span>
            <span class="drill-agency">${e.l.agency.replace(/Real Estate.*/, 'RE').replace(/Realtors?/, '').trim()}</span>
            <span class="drill-price">${formatPrice(e.l.askPrice)}</span>
            <span class="drill-ppsm${isMed ? ' drill-median-val' : ''}">${ppsmDisplay(e.ppsm)}/m²</span>
            <button class="drill-excl-btn${isExcl ? ' restore' : ''}"
                    data-area="${area}" data-type="${type}" data-listing-id="${e.l.id}"
                    title="${isExcl ? 'Restore to median' : 'Exclude from median'}">${isExcl ? '↩' : '✕'}</button>
        </div>`;

    const listEl = document.getElementById('ppsm-drilldown-list');
    listEl.innerHTML =
        active.map((e, i) => makeRow(e, i + 1, false, i === halfIdx)).join('')
        + (nExcl ? `<div class="drill-excl-divider">— ${nExcl} excluded from median —</div>` : '')
        + excluded.map(e => makeRow(e, null, true, false)).join('');
}

function closePpsmDrilldown() {
    document.getElementById('ppsm-drilldown-overlay').classList.remove('open');
    ppsmDrilldownCtx = null;
}

function togglePpsmExclusion(area, type, listingId) {
    const key = `${area}:${type}:${listingId}`;
    if (ppsmExclusions.has(key)) ppsmExclusions.delete(key);
    else                          ppsmExclusions.add(key);
    renderDrilldownList();
    refreshPpsmMatrix();
}

function refreshPpsmMatrix() {
    const activeTab = document.querySelector('.area-tab.active');
    if (!activeTab) return;
    renderAnalysisTab(activeTab.dataset.area);
}

document.addEventListener('keydown', e => { if (e.key === 'Escape') closePpsmDrilldown(); });


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
