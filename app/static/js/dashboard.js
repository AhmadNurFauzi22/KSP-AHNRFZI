/* KSP AHNRFZI - Dashboard real-data (Prompt #9). Fetch dari /api/v1/dashboard/*. */
const Dashboard = {
  charts: {},
  fmtRp(v) {
    try {
      return 'Rp ' + Number(v || 0).toLocaleString('id-ID', { maximumFractionDigits: 0 });
    } catch (e) { return 'Rp ' + v; }
  },
  setState(id, msg) {
    const el = document.getElementById(id);
    if (!el) return;
    if (!msg) { el.style.display = 'none'; el.textContent = ''; }
    else { el.style.display = 'block'; el.textContent = msg; }
  },
  destroy(id) {
    if (this.charts[id]) { this.charts[id].destroy(); delete this.charts[id]; }
  },
  async get(url) {
    const res = await fetch(url);
    if (res.status === 401) { window.location.href = '/login'; throw new Error('Unauthorized'); }
    if (res.status === 403) throw new Error('Akses ditolak untuk peran Anda.');
    if (!res.ok) {
      let d = {};
      try { d = await res.json(); } catch (e) { /* ignore */ }
      throw new Error(d.detail || ('Gagal memuat (' + res.status + ')'));
    }
    return res.json();
  },
  async loadCashflow(days) {
    days = days || 30;
    const lbl = document.getElementById('cf-days-label');
    if (lbl) lbl.textContent = days;
    const cv = document.getElementById('cashflowChart');
    if (!cv || typeof Chart === 'undefined') return;
    this.setState('cashflow-state', 'Memuat…');
    try {
      const d = await this.get('/api/v1/dashboard/cashflow?days=' + days);
      this.setState('cashflow-state', (!d.labels || !d.labels.length) ? 'Belum ada data arus kas.' : null);
      if (!d.labels || !d.labels.length) return;
      this.destroy('cf');
      this.charts.cf = new Chart(cv, {
        type: 'line',
        data: { labels: d.labels, datasets: [
          { label: 'Kas Masuk (Rp)', data: d.kas_masuk, borderColor: '#10b981', backgroundColor: 'rgba(16,185,129,.1)', fill: true, tension: .35, borderWidth: 2 },
          { label: 'Kas Keluar (Rp)', data: d.kas_keluar, borderColor: '#ef4444', backgroundColor: 'rgba(239,68,68,.08)', fill: true, tension: .35, borderWidth: 2 },
        ]},
        options: { responsive: true, maintainAspectRatio: false, plugins: { legend: { position: 'top' }, tooltip: { callbacks: { label: (c) => ' ' + c.dataset.label + ': ' + Dashboard.fmtRp(c.parsed.y) } } }, scales: { y: { ticks: { callback: (v) => (v >= 1e6 ? (v / 1e6) + ' jt' : v) } } } },
      });
    } catch (e) { this.setState('cashflow-state', e.message); }
  },
  async loadLoanStatus() {
    const cv = document.getElementById('loanStatusChart');
    if (!cv || typeof Chart === 'undefined') return;
    this.setState('loan-state', 'Memuat…');
    try {
      const d = await this.get('/api/v1/dashboard/loans?limit=1');
      const b = d.breakdown;
      this.setState('loan-state', (!b || !b.counts.reduce((a, x) => a + x, 0)) ? 'Belum ada data pinjaman.' : null);
      if (!b) return;
      this.destroy('ls');
      this.charts.ls = new Chart(cv, {
        type: 'doughnut',
        data: { labels: b.labels, datasets: [{ data: b.counts, backgroundColor: ['#2563eb', '#8b5cf6', '#06b6d4', '#10b981', '#059669', '#16a34a', '#ef4444'] }] },
        options: { responsive: true, maintainAspectRatio: false, plugins: { legend: { position: 'bottom' } } },
      });
    } catch (e) { this.setState('loan-state', e.message); }
  },
  async loadSavings(period) {
    period = period || 'monthly';
    const cv = document.getElementById('savingsTrendChart');
    if (!cv || typeof Chart === 'undefined') return;
    this.setState('sav-state', 'Memuat…');
    try {
      const d = await this.get('/api/v1/dashboard/savings?period=' + period);
      if (d.personal) { this.setState('sav-state', 'Grafik global tidak tersedia untuk anggota.'); return; }
      this.setState('sav-state', (!d.labels || !d.labels.length) ? 'Belum ada data simpanan.' : null);
      this.destroy('sv');
      this.charts.sv = new Chart(cv, {
        type: 'bar',
        data: { labels: d.labels, datasets: [{ label: 'Setoran (Rp)', data: d.values, backgroundColor: 'rgba(37,99,235,.7)' }] },
        options: { responsive: true, maintainAspectRatio: false, plugins: { legend: { display: false }, tooltip: { callbacks: { label: (c) => ' ' + Dashboard.fmtRp(c.parsed.y) } } }, scales: { y: { ticks: { callback: (v) => (v >= 1e6 ? (v / 1e6) + ' jt' : v) } } } },
      });
    } catch (e) { this.setState('sav-state', e.message); }
  },
  async loadInstallments() {
    const cv = document.getElementById('instChart');
    if (!cv || typeof Chart === 'undefined') return;
    this.setState('inst-state', 'Memuat…');
    try {
      const d = await this.get('/api/v1/dashboard/installments');
      if (d.personal) { this.setState('inst-state', 'Ringkasan angsuran Anda tampil di kartu atas.'); return; }
      this.setState('inst-state', (!d.counts.reduce((a, x) => a + x, 0)) ? 'Belum ada data angsuran.' : null);
      this.destroy('in');
      this.charts.in = new Chart(cv, {
        type: 'pie',
        data: { labels: d.labels, datasets: [{ data: d.counts, backgroundColor: ['#94a3b8', '#f59e0b', '#ef4444', '#06b6d4', '#16a34a'] }] },
        options: { responsive: true, maintainAspectRatio: false, plugins: { legend: { position: 'bottom' } } },
      });
    } catch (e) { this.setState('inst-state', e.message); }
  },
  async loadAttention() {
    const body = document.getElementById('attention-body');
    if (!body) return;
    const st = (document.getElementById('flt-status') || {}).value || '';
    const q = (document.getElementById('flt-search') || {}).value || '';
    body.innerHTML = '<tr><td colspan="7" class="state-box">Memuat…</td></tr>';
    try {
      let url = '/api/v1/dashboard/loans?limit=50';
      if (st) url += '&status=' + encodeURIComponent(st);
      const d = await this.get(url);
      let rows = d.attention_loans || [];
      if (q) {
        const s = q.toLowerCase();
        rows = rows.filter((r) => (r.loan_no + ' ' + r.anggota).toLowerCase().includes(s));
      }
      if (!rows.length) { body.innerHTML = '<tr><td colspan="7" class="state-box">Tidak ada pinjaman yang cocok dengan filter.</td></tr>'; return; }
      body.innerHTML = rows.map((r) => '<tr><td><strong>' + r.loan_no + '</strong></td><td>' + r.anggota + '<br><small>' + r.member_no + '</small></td><td>' + (r.tanggal_pengajuan || '-').slice(0, 10) + '</td><td>' + Dashboard.fmtRp(r.jumlah) + '</td><td>' + r.tenor + ' bln</td><td><span class="badge badge-primary">' + r.status + '</span></td><td>' + Dashboard.fmtRp(r.sisa) + '</td></tr>').join('');
    } catch (e) { body.innerHTML = '<tr><td colspan="7" class="state-box">Gagal memuat: ' + e.message + '</td></tr>'; }
  },
  formatStaticRp() {
    document.querySelectorAll('[data-rp]').forEach((el) => {
      if (el.dataset.done) return;
      el.dataset.done = '1';
      el.textContent = Dashboard.fmtRp(el.dataset.rp || el.textContent);
    });
  },
  // Chat AI pindah ke AIChat global di app.js (tersedia di semua halaman).
};

document.addEventListener('DOMContentLoaded', () => {
  Dashboard.formatStaticRp();
  Dashboard.loadCashflow(30);
  Dashboard.loadLoanStatus();
  Dashboard.loadSavings('monthly');
  Dashboard.loadInstallments();
  Dashboard.loadAttention();
});
