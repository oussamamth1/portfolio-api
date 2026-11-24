"""Push notifications through Firebase Cloud Messaging (HTTP v1 API).

Configured with the FIREBASE_SERVICE_ACCOUNT_JSON environment variable (the full
service-account key file from Firebase > Project settings > Service accounts).
Without it, push is disabled and send() reports every token as not sent.
"""
import json
import logging
import os
import threading

log = logging.getLogger("face-check.push")

_SCOPE = "https://www.googleapis.com/auth/firebase.messaging"
_lock = threading.Lock()
_creds = None
_project_id: str | None = None
_loaded = False


def _load():
    global _creds, _project_id, _loaded
    if _loaded:
        return
    _loaded = True
    raw = os.environ.get("FIREBASE_SERVICE_ACCOUNT_JSON", "").strip()
    if not raw:
        log.warning("FIREBASE_SERVICE_ACCOUNT_JSON not set: push notifications are disabled")
        return
    try:
        from google.oauth2 import service_account

        info = json.loads(raw)
        _creds = service_account.Credentials.from_service_account_info(info, scopes=[_SCOPE])
        _project_id = info["project_id"]
    except Exception:  # bad JSON or key: keep the server running, just without push
        log.exception("FIREBASE_SERVICE_ACCOUNT_JSON is invalid: push notifications are disabled")


def enabled() -> bool:
    with _lock:
        _load()
        return _creds is not None


def _access_token() -> str:
    import google.auth.transport.requests

    with _lock:
        if not _creds.valid:
            _creds.refresh(google.auth.transport.requests.Request())
        return _creds.token


def send(tokens: list[str], title: str, body: str, data: dict[str, str],
         image_url: str | None = None) -> list[str]:
    """Send one notification to each token. Returns tokens that are no longer valid
    (app uninstalled / signed out) so the caller can forget them."""
    if not tokens or not enabled():
        return []
    import requests

    url = f"https://fcm.googleapis.com/v1/projects/{_project_id}/messages:send"
    dead: list[str] = []
    try:
        headers = {"Authorization": f"Bearer {_access_token()}"}
    except Exception:
        log.exception("Could not get a Firebase access token")
        return []
    for token in tokens:
        notification = {"title": title, "body": body}
        if image_url:
            notification["image"] = image_url
        message = {
            "message": {
                "token": token,
                "notification": notification,
                "data": data,
                "android": {
                    "priority": "high",
                    "notification": {"channel_id": "alerts", "sound": "default"},
                },
                "apns": {"payload": {"aps": {"sound": "default"}}},
            }
        }
        try:
            r = requests.post(url, json=message, headers=headers, timeout=10)
        except Exception:
            log.exception("FCM request failed")
            continue
        if r.status_code in (400, 404) and ("UNREGISTERED" in r.text or "INVALID_ARGUMENT" in r.text):
            dead.append(token)
        elif r.status_code != 200:
            log.warning("FCM error %s: %s", r.status_code, r.text[:300])
    return dead
