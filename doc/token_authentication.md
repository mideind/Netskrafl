# Token-Based Authentication for Málstaður Cross-Origin API Calls

## Problem Statement

Málstaður (running on DigitalOcean at `*.ondigitalocean.app`) needs to call Netskrafl APIs (on `netskrafl.is`), but session cookies don't work for cross-origin fetch requests due to `SameSite=Lax` policy.

**Root cause (browser-side):**
1. Málstaður JavaScript calls `/login_malstadur` → Server sets session cookie → Browser stores it
2. Málstaður JavaScript calls `/gatadagsins/riddle` → **Browser refuses to attach the cookie**
3. The browser blocks the cookie because `SameSite=Lax` only allows cookies on same-site requests and top-level navigations (link clicks), NOT on cross-site `fetch()` / XHR subrequests

The server and browser are both behaving correctly per spec. The issue is that `SameSite=Lax` (the secure default) intentionally blocks cookies on cross-origin programmatic requests to prevent CSRF attacks.

**Constraints:**
- Cannot change to `SameSite=None` because it would break the OAuth2 flow used by the legacy Netskrafl web UI (must be supported until 2026)
- Need to support both legacy OAuth2 flow AND cross-origin Málstaður API calls

## Proposed Solution

Use **Bearer token authentication** as an alternative to session cookies for cross-origin requests. The infrastructure for this already exists (Explo tokens) - we just need to:

1. Generate and return an Explo-style token from `/login_malstadur`
2. Modify `session_user()` to accept Bearer tokens in the Authorization header

### Architecture Overview

```
Current Flow (broken for cross-origin):
  Málstaður → POST /login_malstadur → Sets session cookie → Cookie NOT sent on subsequent requests

Proposed Flow:
  Málstaður → POST /login_malstadur → Returns auth token in response body
  Málstaður → GET /gatadagsins/riddle (Authorization: Bearer <token>) → Token verified, user loaded
```

## Implementation Steps

### Step 1: Modify `User.login_by_email()` in `src/skrafluser.py`

Currently passes `previous_token="*"` which skips token generation. Remove this to generate an Explo-style JWT token.

**File:** `src/skrafluser.py` (lines 1343-1355 and 1363-1373)

**Change:** Remove `previous_token="*"` parameter from both `make_login_dict()` calls in `login_by_email()`.

### Step 2: Modify `session_user()` in `src/basics.py`

Add Bearer token checking as a fallback when no session cookie is present.

**File:** `src/basics.py` (lines 258-269)

**Change:** After checking for session cookie, check for `Authorization: Bearer <token>` header. If found, verify using `verify_explo_token()` and load user.

**New logic:**
```python
def session_user() -> Optional[User]:
    """Return the user who is authenticated in the current session, if any."""
    userid = ""
    sess = cast(Mapping[str, Any], session)

    # First, try session cookie (existing logic)
    if (s := cast(Optional[SessionDict], sess.get("s"))) is not None:
        userid = s.get("userid", "")
    elif (u := sess.get("userid")) is not None:
        userid = u.get("id", "")

    # If no session cookie, try Bearer token from Authorization header
    if not userid:
        auth_header = request.headers.get("Authorization", "")
        if auth_header.startswith("Bearer "):
            token = auth_header[7:]  # Remove "Bearer " prefix
            claims = verify_explo_token(token)
            if claims:
                userid = claims.get("sub", "")

    return User.load_if_exists(userid)
```

### Step 3: Add import for `verify_explo_token` in `src/basics.py`

**File:** `src/basics.py`

**Change:** Add import: `from skrafluser import User, verify_explo_token`

## Files to Modify

| File | Changes |
|------|---------|
| `src/skrafluser.py` | Remove `previous_token="*"` from `login_by_email()` |
| `src/basics.py` | Add Bearer token checking in `session_user()`, add import |

## Security Considerations

1. **Token Security:** Explo tokens are signed with `EXPLO_CLIENT_SECRET` using HS256 algorithm - same security as existing Explo mobile app authentication
2. **Token Lifetime:** Default 30 days (same as Explo tokens)
3. **Token Scope:** The token grants the same access as a session cookie - no privilege escalation

## Client-Side Changes Required (Málstaður)

Málstaður will need to:
1. Store the `token` returned from `/login_malstadur` response
2. Include `Authorization: Bearer <token>` header on subsequent API calls
3. Handle token expiration (re-login when 401 is returned)

## Testing Plan

1. Call `/login_malstadur` and verify `token` field is returned in response
2. Call `/gatadagsins/riddle` with `Authorization: Bearer <token>` header
3. Verify user is correctly identified and riddle data is returned
4. Verify existing session-based authentication still works (legacy UI)

## Rollback Plan

If issues arise, the changes are isolated:
- Remove Bearer token logic from `session_user()`
- Re-add `previous_token="*"` to `login_by_email()`

Session-based authentication remains untouched and continues to work.
