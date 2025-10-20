# Elo Rating System Migration Analysis

## Background

The Netskrafl/Explo codebase supports two different products:

1. **Netskrafl** - An Icelandic-only web-based crossword game (netskrafl.is)
2. **Explo** - A multilingual mobile crossword app (supports Icelandic, English, Polish, Norwegian)

Both products share the same backend codebase but run on separate Google App Engine projects with different approaches to Elo rating calculations.

## Elo Rating System Overview

### What is Elo?

The Elo rating system (named after Arpad Elo) calculates relative skill levels of players. After each game:
- Winners gain points, losers lose points
- The amount depends on the rating difference between players
- A player with 400 points higher rating has ~91% expected win probability

### Three Types of Elo Ratings

The system tracks three separate Elo ratings per player:

1. **elo** - All games (human vs human, human vs robot)
2. **human_elo** - Only human vs human games
3. **manual_elo** - Only "Pro Mode" games (manual word validation)

## Current Architecture

### Core Calculation Flow

Both Netskrafl and Explo use the same calculation logic when games complete:

```python
# In skraflgame.py when a game ends:
compute_elo_for_game(gm, u0, u1)         # Updates UserModel (old-style)
compute_locale_elo_for_game(gm, u0, u1)  # Updates EloModel (new-style)
```

### Data Storage Models

**Old-Style (UserModel embedded fields):**
- Stored directly in UserModel entity
- Fields: `elo`, `human_elo`, `manual_elo`
- Single rating set per user (no locale support)
- Used by Netskrafl

**New-Style (EloModel/RobotModel entities):**
- Separate EloModel entity per user/locale combination
- Separate RobotModel entity per robot level/locale combination (tracks robot performance)
- Parent-child relationship: UserModel → EloModel
- Supports locale-specific ratings for both humans and robots
- Used by Explo

## Key Differences Between Products

### Netskrafl (Icelandic-only)

- **Storage:** Uses UserModel's embedded Elo fields
- **Updates:** Real-time updates are "provisional"
- **Authority:** Nightly batch recalculation at 03:00 UTC
- **Cron Jobs:**
  - `/stats/run` - Recalculates all Elo ratings from games
  - `/stats/ratings` - Updates leaderboards
- **Code Path:** `User.elo_for_locale()` returns UserModel data (see lines 533-542 in `src/skrafluser.py`)
- **Locale:** Always `is_IS` (DEFAULT_LOCALE)

### Explo (Multilingual)

- **Storage:** Uses EloModel entities (humans) and RobotModel entities (robots)
- **Updates:** Real-time calculation after each game (authoritative)
- **Authority:** No batch processing - immediate updates are final
- **Cron Jobs:** None for Elo calculations
- **Code Path:** `User.elo_for_locale()` returns locale-specific EloModel data
- **Robot Tracking:** Robot Elo ratings tracked per locale and level in RobotModel
- **Locales:** `en_US`, `is_IS`, `pl_PL`, `nb_NO`, `nn_NO`

## Migration Path: Netskrafl → Explo Model

### Benefits of Migration

1. **Consistency** - Single Elo system across both products
2. **Performance** - No nightly batch processing delays
3. **Scalability** - Ready for future locale expansion
4. **Simplicity** - Remove conditional `if NETSKRAFL` logic
5. **Real-time** - Immediate, authoritative rating updates

### Required Changes

#### 1. Data Migration (One-time)
```python
# Pseudo-code for migration script
for user in UserModel.query():
    if user.elo or user.human_elo or user.manual_elo:
        EloModel.create(
            locale="is_IS",
            uid=user.id(),
            ratings=EloDict(
                elo=user.elo,
                human_elo=user.human_elo,
                manual_elo=user.manual_elo
            )
        )
```

#### 2. Code Changes

**Remove NETSKRAFL conditional in `src/skrafluser.py`:**
```python
# Current (lines 533-549)
def elo_for_locale(self, locale: Optional[str] = None) -> EloDict:
    if NETSKRAFL:
        # Always returns UserModel data
        return self.elo_dict()
    # ... Explo logic

# After migration
def elo_for_locale(self, locale: Optional[str] = None) -> EloDict:
    # Unified logic using EloModel for both products
    locale = locale or self.locale or DEFAULT_LOCALE
    # ... rest of Explo logic
```

#### 3. Disable Batch Processing

Remove from `cron.yaml` for Netskrafl deployment:
```yaml
# Remove these entries
- description: "Skrafl stats"
  url: /stats/run
  schedule: every day 03:00

- description: "Skrafl ratings"
  url: /stats/ratings
  schedule: every day 03:45
```

#### 4. Update Leaderboard Queries

Modify any queries that directly access UserModel Elo fields to use EloModel instead.

### Migration Effort Estimate

- **Data Migration Script:** 1 day
- **Code Changes:** 0.5 days
- **Testing:** 1 day
- **Deployment & Monitoring:** 0.5 days

**Total: 3 days**

### Risk Assessment

**Low Risk:**
- Clear separation between products via PROJECT_ID
- Existing Explo model is proven in production
- Rollback possible via code revert

**Medium Risk:**
- Data migration must be complete and accurate
- Brief inconsistency during migration window

## Current Deployment Safety

✅ **The codebase is safe to deploy as-is to both products**

The conditional logic based on `PROJECT_ID` ensures:
- Netskrafl continues with batch processing (UserModel)
- Explo continues with real-time updates (EloModel)
- No data corruption risk due to separate storage mechanisms
- Backward compatibility is maintained

## Recommendations

1. **Short term:** Deploy unified codebase as-is (safe)
2. **Medium term:** Run migration script to create EloModel entities for Netskrafl users
3. **Long term:** Remove conditional logic and unify on EloModel approach

## Technical Details

### File Locations

- **Elo Calculation:** `src/skraflelo.py`
- **Game Completion:** `src/skraflgame.py` (lines 568, 572)
- **User Model:** `src/skrafluser.py` (lines 533-549)
- **Database Models:** `src/skrafldb.py` (lines 1012-1050 for EloModel, 1220-1260 for RobotModel)
- **Autoplayer Config:** `src/autoplayers.py` (NETSKRAFL-aware robot selection)
- **Batch Processing:** `src/skraflstats.py`
- **Configuration:** `src/config.py` (PROJECT_ID detection)
- **Cron Jobs:** `cron.yaml`

### Environment Variables

- `PROJECT_ID`: Determines product behavior
  - `"netskrafl"` → Netskrafl mode
  - `"explo-dev"` or `"explo-live"` → Explo mode

### Database Schema

```
UserModel (parent)
    ├── elo: int          # Old-style ratings (Netskrafl)
    ├── human_elo: int    # Netskrafl only
    └── manual_elo: int   # Netskrafl only

EloModel (child of UserModel)
    ├── locale: str       # Locale identifier
    ├── elo: int          # New-style ratings (Explo)
    ├── human_elo: int    # Explo only
    └── manual_elo: int   # Explo only

RobotModel (standalone)
    ├── id: str           # Format: "robot-{level}:{locale}"
    └── elo: int          # Robot performance rating (Explo only)
```

## Additional Considerations

### Online User Tracking (Shared Infrastructure)

**Both Netskrafl and Explo share the same online user tracking mechanism**, which is independent of the Elo system:

#### How It Works

1. **Firebase Real-time Presence:**
   - Clients report connection status to Firebase in real-time
   - Netskrafl path: `/connection/{user_id}`
   - Explo path: `/connection/{locale}/{user_id}`

2. **Redis Cache Sync (Cron Job):**
   - Endpoint: `/connect/update` (see `src/firebase.py:420-446`)
   - Schedule: Every 2 minutes (configured in `cron.yaml`)
   - Purpose: Fetches connected users from Firebase and stores in Redis
   - Redis keys: `live:{locale}` (e.g., `live:is_IS`, `live:en_US`)
   - Cache expiry: 2 minutes (constant `_CONNECTED_EXPIRY`)

3. **Query Path:**
   - Code calls `online_status(locale)` to get an `OnlineStatus` instance
   - `OnlineStatus.user_online(uid)` queries the Redis cache
   - Fast lookup without hitting Firebase on every request

#### Important Notes

- **Already enabled for Netskrafl:** The `/connect/update` cron job is already in `cron.yaml` and runs for both products
- **Not affected by Elo migration:** This mechanism is completely independent of Elo calculations
- **Must remain enabled:** Do not disable this cron job during or after Elo migration
- **Locale-aware:** The system automatically handles the correct Firebase paths based on `NETSKRAFL` flag

### Robot Elo Tracking

The new system (Explo) tracks robot performance in RobotModel entities:
- Each robot level has a separate Elo rating per locale
- Robot ratings evolve based on game outcomes (human vs robot)
- This provides more accurate challenge levels across locales
- Old system (Netskrafl) does not track robot Elo separately

### Autoplayer Configuration

The codebase now includes environment-aware autoplayer configuration:
- `AUTOPLAYERS_IS_CLASSIC`: Matches old Netskrafl behavior (3 robots, simpler strategies)
- `AUTOPLAYERS_IS`: New implementation (4 robots, adaptive strategies)
- Selection controlled by `NETSKRAFL` flag in `src/autoplayers.py:360`
- Ensures backward compatibility while allowing improved robot AI in Explo

### Migration Testing Strategy

Before enabling real-time Elo in production:

1. **Parallel Run (1 week)**
   - Keep batch processing enabled
   - Run migration script to create EloModel entities
   - Compare batch-calculated vs real-time-calculated ratings daily
   - Investigate any discrepancies > 5 points

2. **Soft Launch (1 week)**
   - Disable batch recalculation
   - Monitor Elo rating changes in real-time
   - Keep backup of UserModel Elo fields
   - Easy rollback available if issues detected

3. **Full Migration**
   - Once confident in real-time system
   - Remove NETSKRAFL conditionals
   - Clean up deprecated batch processing code

### Risk Mitigation

**Minimal Risk Factors:**
- Both calculation paths use identical `compute_elo()` logic (src/skraflelo.py:36)
- Real-time system already proven in Explo production
- Rollback requires only config change (re-enable cron jobs)

**Potential Issues:**
- Timing: Real-time updates happen immediately vs nightly batch
  - Impact: Players see Elo changes faster (could be positive)
- Robot games: Old system doesn't track robot Elo separately
  - Impact: Robot difficulty may vary more in new system (feature, not bug)

## Conclusion

The unified codebase successfully supports both Elo calculation models through configuration-based behavior. The migration path to real-time Elo is low-risk due to:
1. Identical core calculation logic
2. Proven track record in Explo
3. Easy rollback mechanism
4. Parallel run testing strategy

**Recommendation:** Proceed with migration using the parallel run strategy outlined above to minimize risk while enabling real-time Elo updates for Netskrafl.