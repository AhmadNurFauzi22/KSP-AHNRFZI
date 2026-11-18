## FIX SUMMARY: HTTP 500 Internal Server Error on AHNRFZI Login Page

### Root Cause
Missing `cookie_secure` attribute in the Settings class (`app/core/config.py`). 
The login endpoint at `app/api/v1/auth.py:112` tries to access `_settings.cookie_secure` when setting the HTTP-only cookie after successful authentication, but this attribute didn't exist, causing an `AttributeError` resulting in HTTP 500.

### Affected Flow
- Successful login → `AuthService.authenticate_user()` succeeds → attempts `response.set_cookie(secure=_settings.cookie_secure)` → **AttributeError → HTTP 500**
- Failed login (wrong password) → `authenticate_user()` raises HTTP 401 *before* reaching cookie code → HTTP 401 (correct)

### Fix Applied
**File**: `app/core/config.py` (line 132-133)
```python
# Cookie security flag: True di produksi dengan HTTPS, False di development
cookie_secure: bool = False
```

### Why `cookie_secure: bool = False`
- Development environment uses HTTP, not HTTPS
- The `secure` flag should only be `True` in production with HTTPS
- Setting `secure=True` on HTTP prevents cookies from being sent

### Attributes Verified in auth.py
All `_settings.xxx` accesses in `app/api/v1/auth.py` are now properly defined:
- `CAPTCHA_ENABLED` ✓ (line 130)
- `cookie_secure` ✓ (just added)
- `APP_SECRET_KEY` ✓ (line 56)
- `CAPTCHA_EXPIRY_SECONDS` ✓ (line 131)

### Testing Results
- ✅ `settings.cookie_secure` accessible, returns `False`
- ✅ Wrong passwords → HTTP 401 (unchanged)
- ✅ Valid credentials → no longer causes HTTP 500
- ✅ CAPTCHA validation working correctly
- ✅ Database queries working correctly
- ✅ RBAC/role functionality preserved
- ✅ No user data deleted or modified