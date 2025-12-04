# Firebase Tree Structure for Gáta Dagsins (Riddle of the Day)

This document describes the Firebase Realtime Database structure used by the
Gáta Dagsins feature, including the data stored at each path and the
transactional update logic.

## Tree Structure Overview

```
gatadagsins/
├── {date}/                          # ISO date: YYYY-MM-DD
│   └── {locale}/                    # e.g., "is", "en", "pl", "nb", "nn"
│       ├── riddle/                  # The riddle data for this day/locale
│       │   ├── board: [str]         # 15 strings of 15 chars each
│       │   ├── rack: RackDetails    # List of [tile, score] tuples
│       │   └── max_score: int       # Maximum achievable score
│       │
│       ├── best/                    # Global best score for this riddle
│       │   ├── score: int
│       │   ├── player: str          # User ID of best scorer
│       │   ├── word: str            # The word played (may contain ?x for blanks)
│       │   ├── coord: str           # Coordinate (e.g., "A1" or "1A")
│       │   └── timestamp: str       # ISO 8601 timestamp
│       │
│       ├── count: int               # Number of players who reached max_score today
│       │
│       ├── leaders/                 # Leaderboard (top 50 entries)
│       │   └── {userId}/
│       │       ├── userId: str
│       │       ├── displayName: str
│       │       ├── score: int
│       │       └── timestamp: str
│       │
│       ├── achievements/            # Per-user achievements for this riddle
│       │   └── {userId}/
│       │       ├── score: int
│       │       ├── word: str
│       │       ├── coord: str
│       │       ├── timestamp: str
│       │       └── isTopScore: bool # True if user achieved max_score
│       │
│       └── group/                   # Group-specific data
│           └── {groupId}/
│               └── best/            # Best score within a group
│                   ├── score: int
│                   ├── player: str
│                   ├── word: str
│                   ├── coord: str
│                   └── timestamp: str
│
└── users/                           # User statistics (not date-specific)
    └── {locale}/
        └── {userId}/
            └── stats/
                ├── currentStreak: int    # Current consecutive days played
                ├── longestStreak: int    # All-time longest streak
                ├── topScoreStreak: int   # Consecutive days with top score
                ├── lastPlayedDate: str   # ISO date of last play
                ├── totalDaysPlayed: int  # Total number of days played
                └── totalTopScores: int   # Total number of top scores achieved
```

## Data Types

### RiddleContentDict
The core riddle data stored in Firebase:
```python
{
    "board": List[str],      # 15 strings of 15 characters
    "rack": RackDetails,     # List of (tile, score) tuples
    "max_score": int         # Maximum achievable score
}
```

### BestDict
Used for global best and group best scores:
```python
{
    "score": int,
    "player": str,           # User ID
    "word": str,             # May contain "?x" for blank tiles
    "coord": str,            # "A1" (horizontal) or "1A" (vertical)
    "timestamp": str         # ISO 8601 format
}
```

### LeaderboardEntry
Each entry in the leaderboard:
```python
{
    "userId": str,
    "displayName": str,
    "score": int,
    "timestamp": str
}
```

### RiddleAchievement
Per-user achievement for a specific riddle:
```python
{
    "score": int,
    "word": str,
    "coord": str,
    "timestamp": str,
    "isTopScore": bool
}
```

### UserRiddleStats
User's streak and cumulative statistics:
```python
{
    "currentStreak": int,
    "longestStreak": int,
    "topScoreStreak": int,
    "lastPlayedDate": str,   # ISO date
    "totalDaysPlayed": int,
    "totalTopScores": int
}
```

## Transactional Update Logic

All updates to shared data use Firebase transactions to ensure atomicity and
prevent race conditions when multiple users submit moves simultaneously.

### 1. Global Best Score Update
**Path:** `gatadagsins/{date}/{locale}/best`
**Function:** `update_global_best_score()`

Updates the global best score only if the new score exceeds the current best.
Also maintains an in-memory cache (`_GLOBAL_BEST_CACHE`) for quick lookups.

```python
def transaction_update(current_data: Optional[BestDict]) -> BestDict:
    if score > current_best_score:
        return new_best  # Update to new best
    return current_data  # No change
```

### 2. Group Best Score Update
**Path:** `gatadagsins/{date}/{locale}/group/{groupId}/best`
**Function:** `update_group_best_score()`

Similar to global best, but scoped to a specific group.

### 3. User Achievement Update
**Path:** `gatadagsins/{date}/{locale}/achievements/{userId}`
**Function:** `update_user_achievement()`

Updates a user's achievement for a specific riddle only if the new score is
better than their previous best. Returns a boolean indicating whether a
significant update occurred.

### 4. User Streak Stats Update
**Path:** `gatadagsins/users/{locale}/{userId}/stats`
**Function:** `update_user_streak_stats()`

Updates streak statistics when a user improves their score. Handles:
- Consecutive day detection (streak continuation vs. break)
- Longest streak tracking
- Top score streak tracking
- Total days played and total top scores counters

### 5. Top Score Count Update
**Path:** `gatadagsins/{date}/{locale}/count`
**Function:** `increment_top_score_count()`

Increments the count of players who have achieved the maximum possible score
for today's riddle. Only incremented when a user achieves the top score for
the first time (not on subsequent submissions even if they match the top score).

### 6. Leaderboard Update
**Path:** `gatadagsins/{date}/{locale}/leaders`
**Function:** `update_leaderboard_entry()`

Maintains a leaderboard of the top 50 scores. The transaction:
1. Retrieves current leaderboard as a dictionary
2. Checks if user already has an entry (updates if new score is better)
3. For new entries, adds to the list and re-sorts
4. Keeps only the top `LEADERBOARD_ENTRIES` (50) entries
5. Sorting: by score (descending), then by timestamp (ascending) for ties

## Submission Flow

When a move is submitted via `/gatadagsins/submit`:

1. **Validation**: The move is validated server-side against the actual riddle
   board and rack using `validate_riddle_move()`

2. **Score Verification**: The calculated score must match the claimed score

3. **Updates** (all transactional):
   - Global best score
   - Leaderboard entry
   - User achievement (only if improved)
   - User streak stats (only if achievement improved)
   - Top score count (only if user newly achieved max_score)
   - Group best score (if user belongs to a group)

4. **Response**: Returns whether any updates occurred and a descriptive message

## Caching

### In-Memory Caches
- `_GLOBAL_BEST_CACHE`: Dict[date, Dict[locale, BestDict]] - caches global best scores
- `@cache_if_not_none`: Decorator for caching non-None results with LRU eviction

### Cached Functions
- `riddle_max_score(date, locale)`: Max score for a riddle (maxsize=3)
- `get_or_create_riddle(date, locale, is_today)`: Riddle data (maxsize=3)
- `get_riddle_state(date, locale)`: State object for move validation (maxsize=10)

## Notes

- Dates are always in ISO format: `YYYY-MM-DD`
- Timestamps are always in ISO 8601 format
- Locales are lowercase language codes: `is`, `en`, `pl`, `nb`, `nn`
- Blank tiles in words are represented as `?x` where `x` is the letter
- Coordinates use `A1` format for horizontal moves, `1A` for vertical moves
