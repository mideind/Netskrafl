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

**New-Style (EloModel entities):**
- Separate EloModel entity per user/locale combination
- Parent-child relationship: UserModel → EloModel
- Supports locale-specific ratings
- Used by Explo

## Key Differences Between Products

### Netskrafl (Icelandic-only)

- **Storage:** Uses UserModel's embedded Elo fields
- **Updates:** Real-time updates are "provisional"
- **Authority:** Nightly batch recalculation at 03:00 UTC
- **Cron Jobs:**
  - `/stats/run` - Recalculates all Elo ratings from games
  - `/stats/ratings` - Updates leaderboards
- **Code Path:** `User.elo_for_locale()` returns UserModel data (see lines 524-530 in `src/skrafluser.py`)
- **Locale:** Always `is_IS` (DEFAULT_LOCALE)

### Explo (Multilingual)

- **Storage:** Uses EloModel entities
- **Updates:** Real-time calculation after each game (authoritative)
- **Authority:** No batch processing - immediate updates are final
- **Cron Jobs:** None for Elo calculations
- **Code Path:** `User.elo_for_locale()` returns locale-specific EloModel data
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
# Current (lines 524-530)
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
- **Game Completion:** `src/skraflgame.py` (lines 564-568)
- **User Model:** `src/skrafluser.py` (lines 521-539)
- **Database Models:** `src/skrafldb.py` (lines 999-1050)
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
    ├── elo: int          # Old-style ratings
    ├── human_elo: int    # (Netskrafl only)
    └── manual_elo: int

EloModel (child of UserModel)
    ├── locale: str       # Locale identifier
    ├── elo: int          # New-style ratings
    ├── human_elo: int    # (Explo only)
    └── manual_elo: int
```

## Conclusion

The unified codebase successfully supports both Elo calculation models through configuration-based behavior. While migration to a single model would simplify the system, the current dual-model approach is stable and production-ready.