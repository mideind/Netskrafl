# Plan: Align Netskrafl Paywall with Explo Model

## Context

Netskrafl is transitioning to match Explo's subscription model:
1. **4 robots** instead of 3 (adopt Explo's Icelandic robot set)
2. **Premium robots**: the 2 harder robots (Fullsterkur, Miðlungur) require subscription; the 2 easier ones (Hálfdrættingur, Amlóði) are free
3. **3-game limit** for free users (down from 8), enforced server-side
4. **Paywall** shown when free users hit limits or try premium robots

The legacy web frontend (static/src/) is NOT being updated since all users are redirected to Málstaður. Server-side enforcement is sufficient. The **netskrafl-react** frontend will get full UI changes.

## Changes

### 1. Backend: `src/autoplayers.py`
- Add `premium: bool = False` field to `AutoPlayerTuple` NamedTuple
- Remove `AUTOPLAYERS_IS_NETSKRAFL` (the 3-robot legacy list)
- Change line 361 to always use `AUTOPLAYERS_IS` for Icelandic (drop `NETSKRAFL` conditional)
- Mark `premium=True` on level 0 (Fullsterkur) and level 8 (Miðlungur) across **all** locale lists
- Mark `premium=False` on level 15 and level 20 robots
- Add helper: `autoplayer_is_premium(locale: str, level: int) -> bool`

### 2. Backend: `src/logic.py`
- Add `premium: bool` to `UserListDict` TypedDict (line 197)
- In `userlist()` (line 776), include `premium=r.premium` in robot entries
- For non-robot entries, set `premium=False`

### 3. Backend: `src/api.py` — Server-side enforcement in `/initgame`
- After extracting `robot_level` (line 1464), check premium access:
  ```python
  apl = autoplayer_for_level(user.locale, robot_level)
  if apl and apl.premium and not user.has_paid():
      return jsonify(ok=False, err="premium_required")
  ```
- Add game count enforcement for **all game types** (robot and human-vs-human):
  ```python
  if not user.has_paid():
      games = gamelist(uid, include_zombies=False)
      if len(games) >= MAX_FREE_GAMES:
          return jsonify(ok=False, err="game_limit_reached")
  ```
  Place this check early in `/initgame`, before the robot/human branching.

### 4. Backend: `src/config.py`
- Add constants near line 267:
  ```python
  MAX_FREE_GAMES: int = 3
  MAX_GAMES: int = 50
  ```

### 5. Frontend: `netskrafl-react/src/mithril/types.ts`
- Add `premium?: boolean` to `UserListItem` interface (line 88)

### 6. Frontend: `netskrafl-react/src/mithril/model.ts`
- Change `MAX_FREE_NETSKRAFL` from `8` to `3` (line 59)

### 7. Frontend: `netskrafl-react/src/mithril/userlist.ts`
- After `isRobot` check (line 39), compute:
  ```typescript
  const isLocked = isRobot && item.premium === true && !view.model.state?.hasPaid;
  ```
- In `startRobotGame()` (line 119): if `isLocked`, show paywall via `view.showFriendPromo()` and return
- In `userLink()` (line 126): add lock glyph next to robot name when `isLocked`

### 8. Frontend: `netskrafl-react/src/mithril/friend.ts`
- Update `FriendPromoteDialog` benefit list to mention premium robots (all 4 robots available)
- Update the game limit text (now references 3 instead of 8)

### 9. Frontend: `netskrafl-react/src/mithril/actions.ts`
- In `startNewGame()` (line 530): handle `err` field in server response:
  - `"premium_required"` → `view.showFriendPromo()`
  - `"game_limit_reached"` → `view.showFriendPromo()`

## Existing Games

No migration needed. Premium/limit checks only apply when **starting new games**. Existing in-progress games against premium robots will finish normally.

## Deployment Order

1. **Backend first** — `premium` field is additive (old frontends ignore it); server-side enforcement immediately effective
2. **netskrafl-react second** — lock UI and updated limits
3. Legacy frontend skipped (users redirected to Málstaður)

## Verification

1. **Unit test**: Verify `autoplayer_for_locale("is")` returns 4 robots with correct `premium` flags
2. **API test**: Call `/userlist` with `query=robots` and verify `premium` field in response
3. **API test**: As free user, POST `/initgame` with `opp=robot-0` → expect `ok=false, err=premium_required`
4. **API test**: As free user with 3+ games, POST `/initgame` → expect `ok=false, err=game_limit_reached`
5. **API test**: As paid user, both above should succeed
6. **Manual test**: In netskrafl-react UI, verify lock icons on premium robots for free users
7. **Manual test**: Click locked robot → paywall dialog appears
8. **Manual test**: Verify free user can still play Amlóði and Hálfdrættingur
