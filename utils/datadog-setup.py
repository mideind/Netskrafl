"""

    Datadog setup for the Netskrafl and Explo backend logs

    Copyright © 2026 Miðeind ehf.

    The Creative Commons Attribution-NonCommercial 4.0
    International Public License (CC-BY-NC 4.0) applies to this software.
    For further information, see https://github.com/mideind/Netskrafl

    Creates, or updates, the log-based metrics and the monitors that are
    built on the backend's log entries (see doc/logging.md): request rate
    and latency, failed requests, errors, scheduled jobs that fail or do not
    report, a rating table that is not what it should be, a subscriber who
    is refused at the paywall, and restarting workers.

    Nothing here is specific to one deployment: the service name selects
    the log entries (it is the PROJECT_ID of the deployment), and the keys
    and the notification handle are given when the program is run.

    Usage, from the repository root:
        venv/bin/python utils/datadog-setup.py --service SERVICE --notify HANDLE
            [--site datadoghq.eu] [--jobs stats,ratings,cleanup]
            [--no-monitors] [--validate | --apply]
        venv/bin/python utils/datadog-setup.py --service SERVICE --mute-starts MINUTES
        venv/bin/python utils/datadog-setup.py --service SERVICE --mute-nightly HOURS

    Without --apply, the program only prints what it would send. With
    --validate, it asks the service to check each monitor definition,
    without creating anything. --validate and --apply read the API key and
    the application key of the Datadog organization from the environment
    variables DD_API_KEY and DD_APP_KEY.

    The program can be run again after a change: metrics are found by their
    name and monitors by their title, and are updated in place. Monitors that
    an earlier version of the program created and this one no longer defines
    (RETIRED_MONITORS) are deleted.

    The monitors are for conditions that someone has to act on, and nothing
    else: what they report goes to a channel that people are expected to
    read. Normal operation must not set them off. A deploy is normal
    operation, and the one monitor that a deploy would set off (a start of
    the server) is muted for its duration with --mute-starts, which the
    /deploy skill runs before it starts a production deploy.

"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

import argparse
import json
import os
import sys
from datetime import UTC, datetime, timedelta

import requests


# Tag key of the monitors that watch for a nightly job's daily report
NIGHTLY_TAG = "nightly-job"
# The tag (with the service as its value) of the monitor on starts of the
# server, which a deploy mutes for its duration (see --mute-starts)
START_TAG = "server-start"
# Monitors that this program created earlier and no longer defines: they are
# deleted when the definitions are applied
RETIRED_MONITORS = [
    # Counted worker starts: set off by a deploy shortly after another, and by
    # log entries that the platform delivered more than once
    "Workers are restarting",
    # Now part of "A worker died or timed out"
    "A worker timed out",
]


def metric_prefix(service: str) -> str:
    """Metric names may hold letters, digits, underscores and periods"""
    return "".join(c if c.isalnum() else "_" for c in service)


def metrics(service: str) -> List[Dict[str, Any]]:
    """The log-based metrics: they keep aggregates of the request entries
    for longer than the entries themselves are kept"""
    prefix = metric_prefix(service)
    requests_query = f"service:{service} @event:request"
    return [
        {
            "id": f"{prefix}.requests",
            "attributes": {
                "compute": {"aggregation_type": "count"},
                "filter": {"query": requests_query},
                "group_by": [
                    {"path": "@http.status_code", "tag_name": "status_code"},
                ],
            },
        },
        {
            # Served requests only: the paths of failed requests are whatever
            # was asked for, and would make an unbounded number of tag values
            "id": f"{prefix}.request.duration",
            "attributes": {
                "compute": {
                    "aggregation_type": "distribution",
                    "path": "@duration",
                    "include_percentiles": True,
                },
                "filter": {"query": f"{requests_query} @http.status_code:<400"},
                "group_by": [
                    {"path": "@http.url_details.path", "tag_name": "path"},
                ],
            },
        },
        {
            "id": f"{prefix}.refusals",
            "attributes": {
                "compute": {"aggregation_type": "count"},
                "filter": {"query": f"service:{service} @event:paywall"},
                "group_by": [{"path": "@reason", "tag_name": "reason"}],
            },
        },
    ]


def log_monitor(
    service: str,
    notify: str,
    title: str,
    query: str,
    window: str,
    comparison: str,
    threshold: int,
    text: str,
) -> Dict[str, Any]:
    """A monitor on the number of log entries that match a query"""
    # A quoted phrase inside the search query must have its quotes escaped
    search = f"service:{service} {query}".replace('"', '\\"')
    return {
        "name": f"[{service}] {title}",
        "type": "log alert",
        "query": (
            f'logs("{search}").index("*")'
            f'.rollup("count").last("{window}") {comparison} {threshold}'
        ),
        "message": f"{text}\n\n{notify}",
        "tags": [f"service:{service}", "managed-by:datadog-setup"],
        "options": {
            "thresholds": {"critical": threshold},
            "notify_no_data": False,
            "renotify_interval": 0,
            "include_tags": False,
        },
    }


def monitors(service: str, notify: str, jobs: List[str]) -> List[Dict[str, Any]]:
    """The monitors. The thresholds are starting points: adjust them in
    this file, not in the Datadog UI, and run the program again."""
    prefix = metric_prefix(service)

    def m(
        title: str, query: str, window: str, comparison: str, threshold: int, text: str
    ) -> Dict[str, Any]:
        return log_monitor(
            service, notify, title, query, window, comparison, threshold, text
        )

    result = [
        m(
            "Errors in the log",
            "status:(error OR critical)",
            "5m", ">", 5,
            "The backend is logging errors. Look at the entries with status "
            "error; each has the request id and the user id if it was logged "
            "during a request.",
        ),
        m(
            "Requests answered with 5xx",
            "@event:request @http.status_code:>=500",
            "5m", ">", 5,
            "Requests are failing with a server error. After a release, "
            "consider a rollback (see the /deploy skill).",
        ),
        m(
            "A scheduled job failed",
            "@event:job @ok:false",
            "15m", ">", 0,
            "A scheduled job reported a failure: see the entry "
            "'Job <name>: FAILED ...' for the reason.",
        ),
        m(
            "A rating table is not full or may be incomplete",
            "@event:ratings_table status:warn",
            "1d", ">", 0,
            "The nightly ratings job wrote a table that has fewer rows than "
            "it should, or whose candidates did not reach below its cutoff. "
            "See the entry 'Ratings table ...' for the figures.",
        ),
        m(
            "A subscriber was refused at the paywall",
            "@event:paywall @inconsistent:true",
            "1h", ">", 0,
            "A user whose plan says subscriber was refused as unpaid: the "
            "subscription state in the database is inconsistent (as after "
            "the login bug of November 2026). The entry names the user.",
        ),
        # What gunicorn reports as an error is a worker that ended abnormally:
        # one that it killed for not answering in time, one that was killed
        # from outside (out of memory), one that exited with an error or did
        # not start. A deploy stops and starts workers without any of these
        # (its entries are informational), so it does not set this off.
        m(
            "A worker died or timed out",
            "@logger.name:gunicorn status:(error OR critical)",
            "15m", ">", 0,
            "gunicorn reported that a worker process ended abnormally: it "
            "did not answer in time and was killed (WORKER TIMEOUT), it was "
            "killed from outside (SIGKILL: probably out of memory), or it "
            "exited with an error. The requests it was handling failed. See "
            "the gunicorn entries, and the app's memory graph.",
        ),
        # A start of the server is a deploy, or the platform restarting the
        # container. The second kind is not recorded anywhere else, and while
        # the container is away its requests fail without reaching the log.
        # A deploy is normal operation and must not alert: whoever deploys
        # mutes this monitor for the duration (--mute-starts; the /deploy
        # skill does), so that what it reports is a start that nobody ordered.
        m(
            "The server was started",
            '@logger.name:gunicorn "Starting gunicorn"',
            "5m", ">", 0,
            "The web server started in a new container, and not as part of "
            "a deploy made with the usual procedure (which mutes this "
            "monitor). If nobody deployed or changed the app's settings, the "
            "platform restarted the container: requests were not served for "
            "about half a minute. Look at what was logged just before, and "
            "at the app's memory graph.",
        ),
        # The scheduler in the container makes a request every two minutes,
        # so silence means that the container, or the forwarding of its
        # log, is down
        m(
            "No requests are being logged",
            "@event:request",
            "5m", "<", 1,
            "No request has been logged for five minutes, not even the "
            "scheduler's own every two minutes: the container is not "
            "running, or its log is not reaching the log service.",
        ),
        m(
            "The database cannot be reached",
            "@event:db_connect @outcome:(down OR retrying)",
            "5m", ">", 0,
            "The backend could not open a database connection. 'retrying' "
            "entries followed by 'recovered' are a short interruption that "
            "requests waited out; 'down' means that requests are failing.",
        ),
    ]
    for monitor in result:
        if monitor["name"].endswith("The server was started"):
            monitor["tags"].append(f"{START_TAG}:{service}")
    # Each nightly job must report success once a day. These monitors alert
    # from the moment they are created until the job has run once: they have
    # a tag of their own (NIGHTLY_TAG), so that they can be muted until then
    # with a downtime on that tag (see doc/logging.md).
    # The window is longer than the day between two runs: with exactly 24
    # hours, the previous night's entry leaves the window at the moment the
    # next one is due, and a run that finishes a few seconds later than the
    # night before would set off an alert and a recovery.
    for job in jobs:
        monitor = m(
            f"The nightly {job} job did not report success",
            f"@event:job @job:{job} @ok:true",
            "26h", "<", 1,
            f"No successful run of the {job} job was logged in the last "
            "26 hours: it is at least two hours overdue. Check that the "
            "scheduler in the container is running and what the job logged.",
        )
        monitor["tags"].append(f"{NIGHTLY_TAG}:{service}")
        result.append(monitor)
    # Latency, from the log-based distribution metric (in nanoseconds)
    result.append(
        {
            "name": f"[{service}] Requests are slow (p95 over 1 s)",
            "type": "metric alert",
            "query": (
                f"percentile(last_10m):p95:{prefix}.request.duration{{*}} > 1000000000"
            ),
            "message": (
                "The slowest 5% of requests took more than a second over ten "
                f"minutes. Normal is around 0.1 s.\n\n{notify}"
            ),
            "tags": [f"service:{service}", "managed-by:datadog-setup"],
            "options": {
                "thresholds": {"critical": 1000000000},
                "notify_no_data": False,
            },
        }
    )
    return result


class Api:
    """The few calls of the Datadog API that are needed"""

    def __init__(self, site: str, api_key: str, app_key: str) -> None:
        self._base = f"https://api.{site}"
        self._headers = {
            "DD-API-KEY": api_key,
            "DD-APPLICATION-KEY": app_key,
            "Content-Type": "application/json",
        }

    def call(
        self, method: str, path: str, body: Optional[Dict[str, Any]] = None,
        params: Optional[Dict[str, str]] = None, ok_missing: bool = False,
    ) -> Optional[Any]:
        r = requests.request(
            method, self._base + path, headers=self._headers,
            json=body, params=params, timeout=30,
        )
        if ok_missing and r.status_code == 404:
            return None
        if r.status_code >= 300:
            raise RuntimeError(f"{method} {path}: HTTP {r.status_code}: {r.text[:500]}")
        return r.json() if r.content else {}

    def put_metric(self, metric: Dict[str, Any]) -> str:
        path = "/api/v2/logs/config/metrics"
        name = metric["id"]
        if self.call("GET", f"{path}/{name}", ok_missing=True) is None:
            data = {"type": "logs_metrics", "id": name, "attributes": metric["attributes"]}
            self.call("POST", path, {"data": data})
            return "created"
        # Only the filter, the grouping and the percentiles can be changed
        attrs = metric["attributes"]
        update: Dict[str, Any] = {"filter": attrs["filter"], "group_by": attrs["group_by"]}
        if "include_percentiles" in attrs["compute"]:
            update["compute"] = {
                "include_percentiles": attrs["compute"]["include_percentiles"]
            }
        self.call("PATCH", f"{path}/{name}", {"data": {"type": "logs_metrics", "attributes": update}})
        return "updated"

    def validate_monitor(self, monitor: Dict[str, Any]) -> str:
        """Have the service check a monitor definition; nothing is created"""
        try:
            self.call("POST", "/api/v1/monitor/validate", monitor)
        except RuntimeError as e:
            return f"INVALID: {e}"
        return "valid"

    def find_monitors(self, name: str) -> List[Dict[str, Any]]:
        """The monitors with exactly this name"""
        found: Any = self.call("GET", "/api/v1/monitor", params={"name": name})
        return [f for f in found or [] if f.get("name") == name]

    def put_monitor(self, monitor: Dict[str, Any]) -> str:
        same = self.find_monitors(monitor["name"])
        if same:
            self.call("PUT", f"/api/v1/monitor/{same[0]['id']}", monitor)
            return "updated"
        self.call("POST", "/api/v1/monitor", monitor)
        return "created"

    def delete_monitor(self, name: str) -> str:
        same = self.find_monitors(name)
        for f in same:
            self.call("DELETE", f"/api/v1/monitor/{f['id']}")
        return "deleted" if same else "not there"

    def mute(self, tag: str, minutes: int, message: str) -> str:
        """Hold back the alerts of the monitors with a tag, from now on
        and for a number of minutes; returns the time when that ends"""
        end = datetime.now(UTC) + timedelta(minutes=minutes)
        attributes = {
            "message": message,
            "monitor_identifier": {"monitor_tags": [tag]},
            "scope": "*",
            "schedule": {"end": end.isoformat(timespec="seconds")},
            # By default a downtime holds back the alert but lets the first
            # recovery through: a "recovered" message for an alert that
            # nobody was shown. Hold that back too. A monitor that is still
            # alerting when the downtime ends notifies then, as it should.
            "mute_first_recovery_notification": True,
        }
        self.call(
            "POST", "/api/v2/downtime",
            {"data": {"type": "downtime", "attributes": attributes}},
        )
        return end.strftime("%Y-%m-%d %H:%M UTC")


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Create or update the Datadog log metrics and monitors of a backend"
    )
    parser.add_argument(
        "--service", required=True,
        help="Service name of the log entries: the deployment's PROJECT_ID",
    )
    parser.add_argument(
        "--notify", default="",
        help="Whom the monitors notify, as written in a Datadog message (e.g. @team-handle)",
    )
    parser.add_argument(
        "--mute-starts", type=int, metavar="MINUTES", default=0,
        help="Before a deploy: hold back the alert on a start of the server for "
        "this many minutes, from now on. Nothing else is done",
    )
    parser.add_argument(
        "--mute-nightly", type=int, metavar="HOURS", default=0,
        help="Before creating the monitors of a backend whose nightly jobs have "
        "not run yet: hold back the alerts on a missing report of a nightly job "
        "for this many hours, from now on. Nothing else is done",
    )
    parser.add_argument("--site", default="datadoghq.eu", help="Datadog site")
    parser.add_argument(
        "--jobs", default="stats,ratings,cleanup",
        help="The nightly jobs that must report success every day. The ratings job "
        "only runs for Netskrafl: give 'stats,cleanup' for an Explo backend",
    )
    parser.add_argument(
        "--no-monitors", action="store_true",
        help="Only the metrics: for a backend whose alerts nobody should be woken by",
    )
    parser.add_argument(
        "--validate", action="store_true",
        help="Have the service check the monitor definitions; nothing is created",
    )
    parser.add_argument(
        "--apply", action="store_true", help="Send the definitions (default: only print them)"
    )
    args = parser.parse_args(argv)

    if args.mute_starts > 0 or args.mute_nightly > 0:
        api_key = os.environ.get("DD_API_KEY", "")
        app_key = os.environ.get("DD_APP_KEY", "")
        if not api_key or not app_key:
            print("DD_API_KEY and DD_APP_KEY must be set in the environment", file=sys.stderr)
            return 2
        api = Api(args.site, api_key, app_key)
        if args.mute_starts > 0:
            until = api.mute(
                f"{START_TAG}:{args.service}",
                args.mute_starts,
                f"{args.service}: a deploy is under way",
            )
            print(f"Starts of the {args.service} server will not alert until {until}")
        if args.mute_nightly > 0:
            until = api.mute(
                f"{NIGHTLY_TAG}:{args.service}",
                args.mute_nightly * 60,
                f"{args.service}: the nightly jobs have not run yet",
            )
            print(
                f"Missing reports of the nightly jobs of {args.service} will not "
                f"alert for {args.mute_nightly} hours (until {until})"
            )
        return 0
    if not args.notify and not args.no_monitors:
        parser.error("--notify is required")

    all_metrics = metrics(args.service)
    jobs = [j.strip() for j in args.jobs.split(",") if j.strip()]
    all_monitors = [] if args.no_monitors else monitors(args.service, args.notify, jobs)
    if not args.apply and not args.validate:
        print(json.dumps({"metrics": all_metrics, "monitors": all_monitors}, indent=2))
        print(
            f"\nDry run: {len(all_metrics)} metrics and {len(all_monitors)} monitors "
            "printed, nothing sent. Use --apply to create or update them.",
            file=sys.stderr,
        )
        return 0

    api_key = os.environ.get("DD_API_KEY", "")
    app_key = os.environ.get("DD_APP_KEY", "")
    if not api_key or not app_key:
        print("DD_API_KEY and DD_APP_KEY must be set in the environment", file=sys.stderr)
        return 2
    api = Api(args.site, api_key, app_key)
    if args.validate:
        results = [(m["name"], api.validate_monitor(m)) for m in all_monitors]
        for name, verdict in results:
            print(f"monitor {name}: {verdict}")
        return 0 if all(v == "valid" for _, v in results) else 1
    for metric in all_metrics:
        print(f"metric {metric['id']}: {api.put_metric(metric)}")
    for monitor in all_monitors:
        print(f"monitor {monitor['name']}: {api.put_monitor(monitor)}")
    if all_monitors:
        for title in RETIRED_MONITORS:
            name = f"[{args.service}] {title}"
            print(f"retired monitor {name}: {api.delete_monitor(name)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

