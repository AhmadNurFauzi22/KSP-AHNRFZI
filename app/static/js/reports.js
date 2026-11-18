/* KSP AHNRFZI - Modul Laporan (Prompt #9). Filter di database, pagination, export mengikuti filter, print-friendly. */
const Reports = {
  tab: 'members',
  page: 1,
  totalPages: 1,
  STATUS_OPTS: {
    members: ['', 'AKTIF', 'CALON', 'NONAKTIF', 'KELUAR'],
    savings: ['', 'ACTIVE', 'DORMANT', 'BLOCKED', 'CLOSED'],
    loans: ['', 'DIAJUKAN', 'VERIFIKASI', 'DISETUJUI', 'DITOLAK', 'DICAIRKAN', 'BERJALAN', 'LUNAS'],
    installments: ['', 'BELUM_JATUH_TEMPO', 'JATUH_TEMPO', 'TERLAMBAT', 'DIBAYAR', 'LUNAS'],
    cash: ['', 'CASH_IN', 'CASH_OUT'],
    overdue: [],
  },
  TITLES: { members: '📊 Laporan Keanggotaan', savings: '💰 Laporan Simpanan', loans: '🏦 Laporan Pinjaman', installments: '📅 Laporan Angsuran', cash: '🧾 Laporan Buku Kas', overdue: '⚠️ Laporan Tunggakan' },
  fmtRp(v) { const n = Number(v || 0); return 'Rp ' + n.toLocaleString('id-ID', { maximumFractionDigits: 0 }); },
  switchTab(t) {
    this.tab = t; this.page = 1;
    document.querySelectorAll('.tab-btn').forEach((b) => b.classList.toggle('active', b.dataset.report === t));
    const st = document.getElementById('f-status');
    st.innerHTML = (this.STATUS_OPTS[t] || ['']).map((s) => '<option value="' + s + '">' + (s || 'Semua Status') + '</option>').join('');
    const ex = document.getElementById('f-extra');
    ex.style.display = 'none'; ex.innerHTML = '';
    document.getElementById('report-title').textContent = this.TITLES[t];
    this.load(1);
  },
  params(page, forExport) {
    const p = new URLSearchParams();
    const s = document.getElementById('f-search').value.trim();
    const a = document.getElementById('f-start').value;
    const b = document.getElementById('f-end').value;
    const st = document.getElementById('f-status').value;
    const lim = document.getElementById('f-limit').value;
    if (s) p.set('search', s);
    if (a) p.set('start_date', a);
    if (b) p.set('end_date', b);
    if (st) p.set(this.tab === 'cash' ? 'direction' : 'status', st);
    if (forExport) p.set('export', forExport);
    else { p.set('page', page || this.page); p.set('limit', lim); }
    return p.toString();
  },
  async load(page) {
    if (page) this.page = page;
    const body = document.getElementById('report-body');
    body.innerHTML = '<tr><td colspan="12" class="state-box">Memuat data…</td></tr>';
    try {
      const res = await fetch('/api/v1/reports/' + this.tab + '?' + this.params(this.page, null));
      if (res.status === 401) { window.location.href = '/login'; return; }
      if (!res.ok) {
        let d = {}; try { d = await res.json(); } catch (e) { /* */ }
        body.innerHTML = '<tr><td colspan="12" class="state-box">Gagal: ' + (d.detail || res.status) + '</td></tr>';
        if (res.status === 403) App.showToast(d.detail || 'Akses ditolak', 'error');
        return;
      }
      const j = await res.json();
      this.totalPages = (j.metadata && j.metadata.total_pages) || 1;
      document.getElementById('page-info').textContent = 'Hal ' + j.metadata.current_page + ' / ' + this.totalPages;
      document.getElementById('report-count').textContent = j.metadata.total_records + ' data';
      document.getElementById('report-summary').textContent = Object.entries(j.summary || {}).map(([k, v]) => k + ': ' + (typeof v === 'number' && Math.abs(v) >= 1000 ? v.toLocaleString('id-ID') : v)).join(' · ');
      this.render(j.data || []);
    } catch (e) { body.innerHTML = '<tr><td colspan="12" class="state-box">Gagal menghubungi server.</td></tr>'; }
  },
  render(rows) {
    const head = document.getElementById('report-head');
    const body = document.getElementById('report-body');
    if (!rows.length) { head.innerHTML = ''; body.innerHTML = '<tr><td colspan="12" class="state-box">Tidak ada data untuk filter ini.</td></tr>'; return; }
    const keys = Object.keys(rows[0]);
    head.innerHTML = '<tr>' + keys.map((k) => '<th>' + k.replace(/_/g, ' ').toUpperCase() + '</th>').join('') + '</tr>';
    body.innerHTML = rows.map((r) => '<tr>' + keys.map((k) => {
      let v = r[k];
      if (typeof v === 'number' && /saldo|plafon|pokok|bunga|tagihan|dibayar|nominal|tunggakan|denda|kewajiban|sisa|simpanan|pinjaman|kas|amount/i.test(k)) v = this.fmtRp(v);
      return '<td>' + (v === null || v === undefined ? '-' : v) + '</td>';
    }).join('') + '</tr>').join('');
  },
  reset() {
    document.getElementById('f-search').value = '';
    document.getElementById('f-start').value = '';
    document.getElementById('f-end').value = '';
    document.getElementById('f-status').value = '';
    this.load(1);
  },
  export(fmt) {
    const url = '/api/v1/reports/' + this.tab + '?' + this.params(null, fmt);
    App.showToast('Menyiapkan file ' + fmt.toUpperCase() + '…', 'info');
    window.location.href = url;
  },
  print() {
    const a = document.getElementById('f-start').value || '-';
    const b = document.getElementById('f-end').value || '-';
    document.getElementById('print-title').textContent = this.TITLES[this.tab];
    document.getElementById('print-period').textContent = 'Periode: ' + a + ' s/d ' + b;
    document.getElementById('print-date').textContent = new Date().toLocaleString('id-ID');
    window.print();
  },
  prev() { if (this.page > 1) this.load(this.page - 1); },
  next() { if (this.page < this.totalPages) this.load(this.page + 1); },
};
document.addEventListener('DOMContentLoaded', () => Reports.switchTab('members'));
