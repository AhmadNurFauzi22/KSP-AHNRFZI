"""Pemetaan sinonim role dan jabatan untuk AI Assistant.

AI harus memahami bahwa istilah berbeda-beda bisa merujuk pada role yang sama
atau kategori yang similar. Pemetaan ini fleksibel dan didasarkan pada database
yang sebenarnya, bukan hardcode tanpa basis.

Struktur:
- key: istilah yang mungkin digunakan pengguna (lowercase)
- value: daftar role code yang sesuai di database
"""

# Sinonim role sistem berdasarkan database KSP AHNRFZI
# Role sistem: ADMIN_KOPERASI, KETUA_UMUM, MANAGER, HRD, PENGAWAS_PEMBINA, STAF, IT_PUSAT, KASIR, ANGGOTA

ROLE_SYNONYMS = {
    # Admin variants
    "admin": ["ADMIN_KOPERASI"],
    "administrator": ["ADMIN_KOPERASI"],
    "superadmin": ["ADMIN_KOPERASI"],
    "super admin": ["ADMIN_KOPERASI"],
    "administrator koperasi": ["ADMIN_KOPERASI"],
    
    # Manager variants
    "manager": ["MANAGER"],
    "manajer": ["MANAGER"],
    "general manager": ["MANAGER"],
    "ketua manager": ["MANAGER"],
    
    # Ketua variants
    "ketua": ["KETUA_UMUM"],
    "ketua umum": ["KETUA_UMUM"],
    "ketua koperasi": ["KETUA_UMUM"],
    "pimpinan": ["KETUA_UMUM"],
    "head of": ["KETUA_UMUM"],
    
    # HRD variants
    "hrd": ["HRD"],
    "human resource": ["HRD"],
    "human resources": ["HRD"],
    "kesejahteraan": ["HRD"],
    "pegawai hrd": ["HRD"],
    
    # Pengawas variants
    "pengawas": ["PENGAWAS_PEMBINA"],
    "pembina": ["PENGAWAS_PEMBINA"],
    "pengawas pembina": ["PENGAWAS_PEMBINA"],
    "auditor": ["PENGAWAS_PEMBINA"],
    
    # Staf variants
    "staf": ["STAF"],
    "staff": ["STAF"],
    "staf operasional": ["STAF"],
    
    # IT variants
    "it": ["IT_PUSAT"],
    "it pusat": ["IT_PUSAT"],
    "teknis": ["IT_PUSAT"],
    "teknologi informasi": ["IT_PUSAT"],
    
    # Kasir variants
    "kasir": ["KASIR"],
    "kashier": ["KASIR"],
    "kasir loket": ["KASIR"],
    
    # Anggota variants
    "anggota": ["ANGGOTA"],
    "anggota koperasi": ["ANGGOTA"],
    "member": ["ANGGOTA"],
}

# Jabatan organisasi berdasarkan employees table
# Posisi yang ditemukan: Head of IT Systems, Ketua KSP, General Manager, HR Specialist, Ketua Pengawas

POSITION_SYNONYMS = {
    # Ketua KSP
    "ketua koperasi": ["Ketua KSP"],
    "ketua": ["Ketua KSP"],
    "wakil ketua": ["Ketua KSP"],
    "pimpinan koperasi": ["Ketua KSP"],
    
    # General Manager / Manager
    "general manager": ["General Manager"],
    "manager koperasi": ["General Manager"],
    "manager": ["General Manager"],
    "direksi": ["General Manager"],
    
    # Head of IT
    "head of it": ["Head of IT Systems"],
    "head of it systems": ["Head of IT Systems"],
    "head of systems": ["Head of IT Systems"],
    "direktur it": ["Head of IT Systems"],
    
    # HR Specialist
    "hr specialist": ["HR Specialist"],
    "hrd": ["HR Specialist"],
    "human resources": ["HR Specialist"],
    "human resource specialist": ["HR Specialist"],
    
    # Ketua Pengawas
    "ketua pengawas": ["Ketua Pengawas"],
    "pengawas kepala": ["Ketua Pengawas"],
    "ketua pengawas pembina": ["Ketua Pengawas"],
}


def resolve_role_synonym(role_term: str) -> list:
    """Resolve istilah role ke daftar role code database.
    
    Args:
        role_term: Term dari pengguna (misal: 'admin', 'manager', 'ketua')
    
    Returns:
        List of role codes that match the term
    """
    term_lower = role_term.lower().strip()
    
    # Cek direktamente di dictionary sinonim
    if term_lower in ROLE_SYNONYMS:
        return ROLE_SYNONYMS[term_lower]
    
    # Cek parsial match - substring
    matches = []
    for key, values in ROLE_SYNONYMS.items():
        if key in term_lower or term_lower in key:
            matches.extend(values)
    
    # Jika tidak ditemukan, kembalikan term asli untuk dicek ke database
    if not matches:
        return [role_term.upper()]
    
    # Remove duplicates
    return list(set(matches))


def resolve_position_synonym(position_term: str) -> list:
    """Resolve istilah jabatan ke daftar posisi database.
    
    Args:
        position_term: Term dari pengguna (misal: 'ketua', 'manager', 'hrd')
    
    Returns:
        List of position titles that match the term
    """
    term_lower = position_term.lower().strip()
    
    # Cek langsung di dictionary sinonim
    if term_lower in POSITION_SYNONYMS:
        return POSITION_SYNONYMS[term_lower]
    
    # Cek parsial match
    matches = []
    for key, values in POSITION_SYNONYMS.items():
        if key in term_lower or term_lower in key:
            matches.extend(values)
    
    # Jika tidak ditemukan, kembalikan term asli
    if not matches:
        return [position_term]
    
    return list(set(matches))


def is_system_role(role_code: str) -> bool:
    """Cek apakah role adalah role sistem.
    
    Args:
        role_code: Kode role
    
    Returns:
        True jika role adalah sistem role
    """
    from app.core.database import SessionLocal
    from app.db.models.roles import Roles
    
    db = SessionLocal()
    try:
        role = db.query(Roles).filter(Roles.code == role_code.upper()).first()
        if role:
            return role.is_system_role
        return False
    finally:
        db.close()