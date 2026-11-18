/**
 * KSP AHNRFZI - Core Client Application Logic
 */

const App = {
  // Theme Management
  initTheme() {
    const savedTheme = localStorage.getItem('ksp_theme') || 'light';
    document.documentElement.setAttribute('data-theme', savedTheme);
    const themeBtn = document.getElementById('theme-toggle-btn');
    if (themeBtn) {
      themeBtn.innerHTML = savedTheme === 'dark' ? '☀️' : '🌙';
    }
  },

  toggleTheme() {
    const current = document.documentElement.getAttribute('data-theme') || 'light';
    const next = current === 'dark' ? 'light' : 'dark';
    document.documentElement.setAttribute('data-theme', next);
    localStorage.setItem('ksp_theme', next);
    const themeBtn = document.getElementById('theme-toggle-btn');
    if (themeBtn) {
      themeBtn.innerHTML = next === 'dark' ? '☀️' : '🌙';
    }
  },

  // Toast Notification System
  showToast(message, type = 'info') {
    let container = document.getElementById('toast-container');
    if (!container) {
      container = document.createElement('div');
      container.id = 'toast-container';
      container.className = 'toast-container';
      document.body.appendChild(container);
    }

    const toast = document.createElement('div');
    toast.className = `toast card-glass`;
    
    let icon = 'ℹ️';
    if (type === 'success') icon = '✅';
    if (type === 'error') icon = '❌';
    if (type === 'warning') icon = '⚠️';

    toast.innerHTML = `
      <span>${icon}</span>
      <div style="flex-grow: 1; font-size: 0.9rem;">${message}</div>
    `;

    container.appendChild(toast);
    setTimeout(() => {
      toast.style.opacity = '0';
      toast.style.transform = 'translateX(100%)';
      toast.style.transition = 'all 0.3s ease';
      setTimeout(() => toast.remove(), 300);
    }, 3500);
  },

  // Role Context Switcher — reset AIChat context on role switch
  async switchRole(targetRole) {
    try {
      const response = await fetch('/api/v1/auth/switch-role', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ target_role: targetRole })
      });
      const data = await response.json();
      if (response.ok) {
        App.showToast(`Berhasil beralih ke peran: ${targetRole}`, 'success');
        // Reset AI context so it reloads with new role on next open
        if (typeof AIChat !== 'undefined') AIChat.resetContext();
        setTimeout(() => window.location.reload(), 600);
      } else {
        App.showToast(data.detail || 'Gagal mengubah peran', 'error');
      }
    } catch (e) {
      App.showToast('Gagal menghubungi server', 'error');
    }
  },

  // Logout — reset AI context
  async logout() {
    try {
      if (typeof AIChat !== 'undefined') AIChat.resetContext();
      await fetch('/api/v1/auth/logout', { method: 'POST' });
      window.location.href = '/login';
    } catch (e) {
      window.location.href = '/login';
    }
  },

  // Mobile Sidebar Toggle
  toggleSidebar() {
    const sidebar = document.querySelector('.sidebar');
    if (sidebar) {
      sidebar.classList.toggle('open');
    }
  }
};

/* Notification Center client (Prompt #13) */
const Notif = {
  esc(s) {
    return String(s == null ? '' : s)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;')
      .replace(/>/g, '&gt;').replace(/"/g, '&quot;');
  },
  async refreshBadge() {
    const badge = document.getElementById('notif-badge');
    if (!badge) return;
    try {
      const r = await fetch('/api/v1/notifications/unread-count');
      if (r.status === 401) return;
      if (!r.ok) return;
      const n = (await r.json()).unread_count || 0;
      badge.style.display = n > 0 ? 'flex' : 'none';
      badge.textContent = n > 99 ? '99+' : n;
    } catch (e) { /* abaikan: badge opsional */ }
  },
  async toggle() {
    const dd = document.getElementById('notif-dropdown');
    if (!dd) return;
    const open = dd.style.display !== 'none';
    dd.style.display = open ? 'none' : 'block';
    if (!open) await this.load();
  },
  async load() {
    const list = document.getElementById('notif-list');
    if (!list) return;
    list.innerHTML = '<div style="padding:1rem;text-align:center;color:var(--text-muted);">Memuat…</div>';
    try {
      const r = await fetch('/api/v1/notifications?limit=8');
      if (!r.ok) { list.innerHTML = '<div style="padding:1rem;text-align:center;">Gagal memuat.</div>'; return; }
      const items = (await r.json()).data || [];
      if (!items.length) { list.innerHTML = '<div style="padding:1.5rem;text-align:center;color:var(--text-muted);">Tidak ada notifikasi.</div>'; return; }
      list.innerHTML = items.map(n =>
        '<div data-nid="' + n.id + '" data-link="' + this.esc(n.link_url || '') + '" class="notif-item" style="padding:.7rem 1rem;border-bottom:1px solid var(--border-subtle);cursor:pointer;' +
        (n.is_read ? 'opacity:.65;' : 'font-weight:600;') + '">' +
        '<div style="font-size:.85rem;">' + this.esc(n.title) + '</div>' +
        '<div style="font-size:.78rem;color:var(--text-secondary);">' + this.esc((n.message || '').slice(0, 120)) + '</div>' +
        '<div style="font-size:.7rem;color:var(--text-muted);">' + this.esc((n.created_at || '').toString().slice(0, 16).replace('T', ' ')) + '</div></div>'
      ).join('');
      list.querySelectorAll('.notif-item').forEach(el => {
        el.addEventListener('click', () => this.open(el.dataset.nid, el.dataset.link));
      });
    } catch (e) { list.innerHTML = '<div style="padding:1rem;text-align:center;">Gagal memuat.</div>'; }
  },
  async open(id, link) {
    try { await fetch('/api/v1/notifications/' + id + '/read', { method: 'PATCH' }); } catch (e) { /* abaikan */ }
    this.refreshBadge();
    if (link) window.location.href = link;
    else { const dd = document.getElementById('notif-dropdown'); if (dd) dd.style.display = 'none'; this.load(); }
  },
  async readAll(e) {
    if (e) e.stopPropagation();
    await fetch('/api/v1/notifications/read-all', { method: 'POST' });
    this.refreshBadge();
    this.load();
  },
};

/* AI Assistant chat global (Prompt #12) — tersedia di semua halaman */
const AIChat = {
  history: [],
  busy: false,
  contextLoaded: false,
  abort: null,

  openModal() {
    const m = document.getElementById('ai-assistant-modal');
    if (m) m.style.display = 'flex';
    if (!this.contextLoaded) {
      this.loadContext();
    }
    const i = document.getElementById('ai-chat-input');
    if (i) i.focus();
  },

  closeModal() {
    const m = document.getElementById('ai-assistant-modal');
    if (m) m.style.display = 'none';
    if (this.busy) this.stop();
  },

  resetContext() {
    this.contextLoaded = false;
    this.history = [];
    const greet = document.getElementById('ai-greeting-bubble');
    if (greet) greet.innerHTML = 'Halo! Saya <strong>AI Assistant KSP AHNRFZI</strong>. Memuat profil peran Anda\u2026';
    const chips = document.getElementById('ai-quick-prompts');
    if (chips) chips.innerHTML = '';
    const roleBadge = document.getElementById('ai-role-badge');
    if (roleBadge) { roleBadge.textContent = ''; roleBadge.style.display = 'none'; }
    const provBadge = document.getElementById('ai-provider-badge');
    if (provBadge) provBadge.textContent = 'Memuat\u2026';
  },

  async loadContext() {
    try {
      const r = await fetch('/api/v1/ai/context');
      if (r.status === 401) { window.location.href = '/login'; return; }
      if (!r.ok) {
        await this._loadStatusFallback();
        return;
      }
      const ctx = await r.json();

      // Update provider badge
      const badge = document.getElementById('ai-provider-badge');
      if (badge) badge.textContent = ctx.llm_ready ? '\u25cf AI Aktif' : '\u25cf Mode Lokal';

      // Update role badge in modal header
      const roleBadge = document.getElementById('ai-role-badge');
      if (roleBadge && ctx.active_role_name) {
        roleBadge.textContent = ctx.active_role_name;
        roleBadge.style.display = 'inline-block';
      }

      // Update greeting bubble text (server-side, role-specific)
      const greet = document.getElementById('ai-greeting-bubble');
      if (greet && ctx.greeting) {
        greet.textContent = ctx.greeting;
      }

      // Render dynamic suggested question chips per role
      const chips = document.getElementById('ai-quick-prompts');
      if (chips && ctx.suggested_questions && ctx.suggested_questions.length > 0) {
        chips.innerHTML = '';
        ctx.suggested_questions.slice(0, 6).forEach(q => {
          const btn = document.createElement('button');
          btn.type = 'button';
          btn.className = 'btn btn-secondary btn-sm';
          btn.textContent = q;
          btn.setAttribute('aria-label', 'Tanyakan: ' + q);
          btn.addEventListener('click', () => AIChat.quickAsk(q));
          chips.appendChild(btn);
        });
      }

      this.contextLoaded = true;
    } catch (e) {
      await this._loadStatusFallback();
    }
  },

  async _loadStatusFallback() {
    try {
      const r = await fetch('/api/v1/ai/status');
      if (!r.ok) return;
      const s = await r.json();
      const b = document.getElementById('ai-provider-badge');
      if (b) b.textContent = s.llm_ready ? '\u25cf AI Aktif' : '\u25cf Mode Lokal';
      const greet = document.getElementById('ai-greeting-bubble');
      if (greet) greet.innerHTML = 'Halo! Saya <strong>AI Assistant KSP AHNRFZI</strong>. Saya membantu informasi keanggotaan, simpanan, pinjaman, angsuran, dan SOP koperasi berdasarkan data resmi.';
      const chips = document.getElementById('ai-quick-prompts');
      if (chips && chips.children.length === 0) {
        ['Siapa saya dan apa jabatan saya?', 'Berapa saldo simpanan saya?', 'Berapa sisa pinjaman saya?', 'Kapan angsuran saya berikutnya?', 'Bagaimana cara mengajukan pinjaman?'].forEach(q => {
          const btn = document.createElement('button');
          btn.type = 'button';
          btn.className = 'btn btn-secondary btn-sm';
          btn.textContent = q;
          btn.addEventListener('click', () => AIChat.quickAsk(q));
          chips.appendChild(btn);
        });
      }
      this.contextLoaded = true;
    } catch (e) { /* abaikan */ }
  },

  _bubble(text, mine) {
    const container = document.getElementById('ai-chat-messages');
    const el = document.createElement('div');
    el.style.cssText = (mine
      ? 'align-self:flex-end;background:#2563eb;color:#fff;padding:.65rem 1rem;border-radius:12px 12px 0 12px;margin-bottom:.5rem;max-width:80%;font-size:.88rem;'
      : 'align-self:flex-start;background:var(--bg-subtle);color:var(--text-primary);padding:.65rem 1rem;border-radius:12px 12px 12px 0;margin-bottom:.5rem;max-width:80%;font-size:.88rem;')
      + 'white-space:pre-line;';
    el.textContent = text;
    container.appendChild(el);
    this._scroll();
    return el;
  },

  _scroll() {
    const container = document.getElementById('ai-chat-messages');
    if (container) container.scrollTop = container.scrollHeight;
  },

  quickAsk(q) {
    const i = document.getElementById('ai-chat-input');
    if (i) i.value = q;
    this.ask();
  },

  _setBusy(on) {
    this.busy = on;
    const send = document.getElementById('ai-send-btn');
    const stop = document.getElementById('ai-stop-btn');
    const input = document.getElementById('ai-chat-input');
    if (send) send.disabled = on;
    if (stop) stop.style.display = on ? 'inline-block' : 'none';
    if (input) input.disabled = on;
  },

  stop() {
    if (this.abort) { this.abort.abort(); this.abort = null; }
  },

  async ask() {
    const input = document.getElementById('ai-chat-input');
    const container = document.getElementById('ai-chat-messages');
    if (!input || !input.value.trim() || !container || this.busy) return;
    const query = input.value.trim().slice(0, 2000);
    input.value = '';
    this._bubble(query, true);
    const bot = this._bubble('Mengetik\u2026', false);
    this._setBusy(true);
    this.abort = new AbortController();
    try {
      const res = await fetch('/api/v1/ai/ask', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ question: query }),
        signal: this.abort.signal,
      });
      let data = {};
      try { data = await res.json(); } catch (e) { /* abaikan */ }
      if (res.status === 401) { window.location.href = '/login'; return; }
      if (res.status === 429) { bot.textContent = 'Terlalu banyak pertanyaan. Tunggu sebentar lalu coba lagi.'; return; }
      if (!res.ok) { bot.textContent = 'Maaf, AI Assistant sedang tidak tersedia. Silakan coba kembali.'; return; }
      bot.textContent = data.answer || 'Maaf, saya belum dapat menjawab pertanyaan tersebut.';
      if (data.source) {
        const src = document.createElement('div');
        src.style.cssText = 'align-self:flex-start;font-size:.7rem;color:var(--text-muted);margin:-.25rem 0 .5rem;max-width:80%;';
        src.textContent = 'Sumber: ' + data.source;
        container.appendChild(src);
      }
      this.history.push({ q: query, a: bot.textContent });
      if (this.history.length > 50) this.history.shift();
    } catch (e) {
      bot.textContent = (e && e.name === 'AbortError')
        ? 'Permintaan dibatalkan.'
        : 'Maaf, AI Assistant sedang tidak tersedia. Silakan coba kembali.';
    } finally {
      this._setBusy(false);
      this.abort = null;
      this._scroll();
    }
  },
};

document.addEventListener('DOMContentLoaded', () => {
  App.initTheme();
  Notif.refreshBadge();  setInterval(() => Notif.refreshBadge(), 60000);
  document.addEventListener('click', (ev) => {
    const dd = document.getElementById('notif-dropdown');
    if (dd && dd.style.display !== 'none' && !ev.target.closest('#notif-dropdown') && !ev.target.closest('[onclick^="Notif.toggle"]')) {
      dd.style.display = 'none';
    }
  });
  // AI chat: Enter kirim, Shift+Enter baris baru
  document.addEventListener('keydown', (ev) => {
    if (ev.target && ev.target.id === 'ai-chat-input' && ev.key === 'Enter' && !ev.shiftKey) {
      ev.preventDefault();
      AIChat.ask();
    }
  });
});
