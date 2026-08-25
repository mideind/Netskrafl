"""

    Replay-fixture sampler for Netskrafl

    Copyright © 2026 Miðeind ehf.

    READ-ONLY utility. Samples recently completed human-vs-human games
    from the Google Cloud NDB Datastore and exports them as JSON fixtures
    for the replay test harness, which re-plays each game through the
    /initgame + /submitmove API path against the new (PostgreSQL) backend
    and verifies identical engine behavior.

    Sampling criteria:
      * Game is over, between two human players (no robot)
      * Untimed (no duration preference)
      * Completed within the recent time window (default 365 days), to
        minimize vocabulary drift when re-validating moves
      * Full rack history available (irack0/irack1 and a rack recorded
        for every move), so the harness can force bag draws to match
      * No degenerate/erroneous move records
      * Quotas: by default 75 regular games plus 25 manual-wordcheck
        ("pro mode") games containing at least one challenge move, so
        that challenge validation/rejection code paths are covered,
        plus 5 games that end with a resignation (RSGN), to cover
        forfeited-score accounting and win/loss attribution

    The fixtures contain no user identifiers or nicknames - only the game
    id, timestamps, preferences, racks and the move sequence. Player moves
    are attributed positionally (player 0 moves first, then alternation,
    which is also how the game loader in skraflgame.py assigns them).

    NOTE: This reads the *production* Datastore directly. It does not
    write anything, and it bypasses the Redis global cache entirely, so
    the local-cache incoherency gotcha does not apply.

    Usage (run from the repository root):

        PROJECT_ID=netskrafl \
        GOOGLE_APPLICATION_CREDENTIALS="credentials/netskrafl/service-account.json" \
        GOOGLE_CLOUD_PROJECT=netskrafl \
        RUNNING_LOCAL=true \
        venv/bin/python utils/sample_replay_games.py [options]

    Options:
        --days N          Time window in days (default 365)
        --total N         Number of regular+manual fixtures (default 100)
        --manual N        Quota of manual games with challenges (default 25)
        --rsgn N          Additional quota of games ending in resignation
                          (default 5)
        --max-scan N      Max games to scan before giving up (default 20000)
        --out DIR         Output directory (default test/replay_fixtures)

"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

import argparse
import json
import os
import sys
from datetime import UTC, datetime, timedelta

os.environ["GRPC_DNS_RESOLVER"] = "native"

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from google.cloud import ndb  # noqa: E402

from skrafldb_ndb import GameModel, MoveModel  # noqa: E402


def move_player(index: int) -> int:
    """Player 0 always makes the first move; strict alternation after that,
    including challenge (CHALL) and response (RESP) moves"""
    return index % 2


def classify_move(mm: MoveModel) -> str:
    """Classify a stored move record"""
    if mm.coord:
        return "tile"
    t = mm.tiles or ""
    if t.startswith("EXCH"):
        return "exch"
    if t == "PASS":
        return "pass"
    if t == "RSGN":
        return "rsgn"
    if t == "CHALL":
        return "chall"
    if t == "RESP":
        return "resp"
    return "invalid"


def check_game(gm: GameModel, stats: Dict[str, int]) -> Optional[Dict[str, Any]]:
    """Check whether a game qualifies as a replay fixture; if so, return
    the fixture dict, otherwise bump the relevant exclusion counter"""

    def excluded(reason: str) -> None:
        stats[reason] = stats.get(reason, 0) + 1

    if gm.player0 is None or gm.player1 is None:
        excluded("excl_robot_game")
        return None
    prefs: Dict[str, Any] = dict(gm.prefs) if gm.prefs else {}
    try:
        duration = int(prefs.get("duration", 0) or 0)
    except (TypeError, ValueError):
        duration = 0
    if duration > 0:
        excluded("excl_timed")
        return None
    if not gm.irack0 or not gm.irack1:
        excluded("excl_no_initial_racks")
        return None
    moves: List[MoveModel] = gm.moves or []
    if len(moves) < 10:
        excluded("excl_too_few_moves")
        return None
    kinds = [classify_move(mm) for mm in moves]
    if "invalid" in kinds:
        excluded("excl_degenerate_move")
        return None
    if any(mm.rack is None for mm in moves):
        excluded("excl_missing_move_racks")
        return None

    manual = bool(prefs.get("manual", False))
    n_chall = kinds.count("chall")
    resp_scores = [mm.score for mm, k in zip(moves, kinds) if k == "resp"]
    fixture: Dict[str, Any] = {
        "game_id": gm.key.id(),
        "ts_last_move": (
            gm.ts_last_move.isoformat() if gm.ts_last_move else None
        ),
        "locale": gm.locale or "is_IS",
        "prefs": prefs,
        "manual": manual,
        "irack0": gm.irack0,
        "irack1": gm.irack1,
        "moves": [
            {
                "player": move_player(ix),
                "coord": mm.coord or "",
                "tiles": mm.tiles or "",
                "score": mm.score,
                "rack": mm.rack,
            }
            for ix, mm in enumerate(moves)
        ],
        "score0": gm.score0,
        "score1": gm.score1,
        "rack0_final": gm.rack0,
        "rack1_final": gm.rack1,
        "num_moves": len(moves),
        "num_challenges": n_chall,
        # Successful challenge: the challenged move is retracted (score < 0);
        # failed challenge: the challenger's opponent gets a +10 bonus
        "num_challenges_upheld": sum(1 for s in resp_scores if s < 0),
        "num_challenges_rejected": sum(1 for s in resp_scores if s > 0),
        "ends_with_resignation": kinds[-1] == "rsgn" if kinds else False,
    }
    return fixture


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Sample completed games as replay test fixtures"
    )
    parser.add_argument("--days", type=int, default=365)
    parser.add_argument("--total", type=int, default=100)
    parser.add_argument("--manual", type=int, default=25)
    parser.add_argument("--rsgn", type=int, default=5)
    parser.add_argument("--max-scan", type=int, default=20000)
    parser.add_argument("--out", type=str, default="test/replay_fixtures")
    args = parser.parse_args()

    regular_quota = args.total - args.manual
    if regular_quota < 0:
        print("--manual must not exceed --total")
        return 1

    os.makedirs(args.out, exist_ok=True)
    cutoff = datetime.now(UTC) - timedelta(days=args.days)

    regular: List[Dict[str, Any]] = []
    manual: List[Dict[str, Any]] = []
    rsgn: List[Dict[str, Any]] = []
    stats: Dict[str, int] = {}
    scanned = 0

    client = ndb.Client()
    # Explicitly bypass any global (Redis) cache: plain context, read-only
    with client.context():
        # Uses the existing composite index (over, ts_last_move asc).
        # At the class level, ts_last_move is the (always present) NDB
        # property object; narrow away its Optional declaration so that
        # the filter comparison type-checks
        ts_last_move = GameModel.ts_last_move
        assert ts_last_move is not None
        q = GameModel.query(
            GameModel.over == True,  # noqa: E712
            ts_last_move > cutoff,
        ).order(ts_last_move)
        for gm in q.iter():
            scanned += 1
            if scanned > args.max_scan:
                print(f"Scan cap of {args.max_scan} games reached, stopping")
                break
            fixture = check_game(gm, stats)
            if fixture is None:
                continue
            if fixture["ends_with_resignation"]:
                if len(rsgn) < args.rsgn:
                    rsgn.append(fixture)
                else:
                    stats["skipped_rsgn_quota_full"] = (
                        stats.get("skipped_rsgn_quota_full", 0) + 1
                    )
            elif fixture["manual"]:
                if fixture["num_challenges"] == 0:
                    stats["excl_manual_without_challenge"] = (
                        stats.get("excl_manual_without_challenge", 0) + 1
                    )
                elif len(manual) < args.manual:
                    manual.append(fixture)
                else:
                    stats["skipped_manual_quota_full"] = (
                        stats.get("skipped_manual_quota_full", 0) + 1
                    )
            elif len(regular) < regular_quota:
                regular.append(fixture)
            else:
                stats["skipped_regular_quota_full"] = (
                    stats.get("skipped_regular_quota_full", 0) + 1
                )
            if (
                len(regular) >= regular_quota
                and len(manual) >= args.manual
                and len(rsgn) >= args.rsgn
            ):
                break
            if scanned % 1000 == 0:
                print(
                    f"...scanned {scanned}: "
                    f"{len(regular)}/{regular_quota} regular, "
                    f"{len(manual)}/{args.manual} manual, "
                    f"{len(rsgn)}/{args.rsgn} rsgn"
                )

    selected = regular + manual + rsgn
    for fixture in selected:
        fname = os.path.join(args.out, f"game_{fixture['game_id']}.json")
        with open(fname, "w", encoding="utf-8") as f:
            json.dump(fixture, f, ensure_ascii=False, indent=2)

    manifest = {
        "generated": datetime.now(UTC).isoformat(),
        "cutoff": cutoff.isoformat(),
        "scanned": scanned,
        "num_regular": len(regular),
        "num_manual": len(manual),
        "num_rsgn": len(rsgn),
        "total_challenges": sum(f["num_challenges"] for f in selected),
        "challenges_upheld": sum(f["num_challenges_upheld"] for f in selected),
        "challenges_rejected": sum(
            f["num_challenges_rejected"] for f in selected
        ),
        "resignations": sum(
            1 for f in selected if f["ends_with_resignation"]
        ),
        "stats": stats,
        "games": sorted(f["game_id"] for f in selected),
    }
    with open(
        os.path.join(args.out, "manifest.json"), "w", encoding="utf-8"
    ) as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)

    print(f"\nScanned {scanned} finished games since {cutoff.date()}")
    print(
        f"Selected {len(regular)} regular + {len(manual)} manual "
        f"+ {len(rsgn)} resignation fixtures"
    )
    print(
        f"Challenges in sample: {manifest['total_challenges']} "
        f"({manifest['challenges_upheld']} upheld, "
        f"{manifest['challenges_rejected']} rejected)"
    )
    print(f"Resignation endings: {manifest['resignations']}")
    print("Exclusion/skip statistics:")
    for k in sorted(stats):
        print(f"  {k}: {stats[k]}")
    print(f"Fixtures written to {args.out}/")
    if (
        len(regular) < regular_quota
        or len(manual) < args.manual
        or len(rsgn) < args.rsgn
    ):
        print("WARNING: quota not filled - consider a longer --days window")
    return 0


if __name__ == "__main__":
    sys.exit(main())

