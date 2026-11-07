#!/usr/bin/env python3
# ============================================================
#  liked_dedupe.py — clean up your Spotify Liked Songs
#
#  Finds every song in your Liked Songs that already exists in
#  one of your playlists, and removes it from Liked Songs
#  (playlists are never touched).
#
#  Usage:
#    python liked_dedupe.py /path/to/spotify/export --dry-run   # just look
#    python liked_dedupe.py /path/to/spotify/export             # look + remove
#    python liked_dedupe.py /path/to/spotify/export --report    # also write markdown reports
#
#  Requires: Python 3.8+, no third-party packages.
# ============================================================

import argparse
import base64
import hashlib
import http.server
import json
import secrets
import socketserver
import string
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
from collections import defaultdict
from pathlib import Path

CLIENT_ID = "PASTE_YOUR_CLIENT_ID_HERE"   # from developer.spotify.com/dashboard
REDIRECT_URI = "http://127.0.0.1:8888/callback"
SCOPES = "user-library-read user-library-modify"
TOKEN_FILE = Path("spotify_token.json")
BATCH_SIZE = 40   # DELETE /me/library accepts max 40 URIs per call


# ------------------------------------------------------------
# Export parsing
# ------------------------------------------------------------

def load_export(export_dir):
    export_dir = Path(export_dir)
    if not export_dir.is_dir():
        sys.exit(f"ERROR: '{export_dir}' is not a folder.")

    lib_file = export_dir / "YourLibrary.json"
    if not lib_file.exists():
        sys.exit("ERROR: YourLibrary.json not found in that folder. "
                 "It's part of the Spotify privacy export — see the README.")

    lib = json.loads(lib_file.read_text(encoding="utf-8"))
    liked = lib.get("tracks", [])
    print(f"  Found {len(liked)} liked songs in YourLibrary.json")

    # Playlist files: Playlist1.json, Playlist2.json, ... (per export)
    playlists = []
    for f in sorted(export_dir.glob("Playlist*.json")):
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            playlists.extend(data.get("playlists", []))
        except (json.JSONDecodeError, KeyError):
            pass
    print(f"  Found {len(playlists)} playlists across Playlist*.json files")
    return liked, playlists


def find_duplicates(liked, playlists):
    """Return {track_uri: {'name':..., 'playlists': set(names)}} for liked tracks in playlists."""
    uri_to_playlists = defaultdict(set)
    for pl in playlists:
        for item in pl.get("items", []):
            track = item.get("track") or {}
            uri = track.get("trackUri")
            if uri:
                uri_to_playlists[uri].add(pl.get("name", "(unnamed)"))

    dupes = {}
    for t in liked:
        uri = t.get("uri")
        if uri in uri_to_playlists:
            dupes[uri] = {
                "name": f"{t.get('artist', '?')} — {t.get('track', '?')}",
                "playlists": sorted(uri_to_playlists[uri]),
            }
    return dupes


def write_reports(dupes, liked, keep):
    with open("duplicates_report.md", "w", encoding="utf-8") as f:
        f.write(f"# Liked Songs already in playlists — {len(dupes)} tracks\n\n")
        f.write(f"(from {len(liked)} liked songs; safe to remove from Liked Songs)\n\n")
        for uri in sorted(dupes, key=lambda u: dupes[u]["name"].lower()):
            d = dupes[uri]
            f.write(f"- {d['name']}  [{' | '.join(d['playlists'])}]\n")
    print(f"  Wrote duplicates_report.md ({len(dupes)} tracks)")

    with open("keep_report.md", "w", encoding="utf-8") as f:
        f.write(f"# Liked Songs NOT in any playlist — {len(keep)} tracks\n\n")
        for name in sorted(keep, key=str.lower):
            f.write(f"- {name}\n")
    print(f"  Wrote keep_report.md ({len(keep)} tracks)")


# ------------------------------------------------------------
# OAuth (PKCE — no client secret needed)
# ------------------------------------------------------------

def make_pkce():
    verifier = "".join(secrets.choice(string.ascii_letters + string.digits + "-._~")
                       for _ in range(64))
    challenge = base64.urlsafe_b64encode(
        hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    return verifier, challenge


def authorize():
    verifier, challenge = make_pkce()
    params = urllib.parse.urlencode({
        "client_id": CLIENT_ID,
        "response_type": "code",
        "redirect_uri": REDIRECT_URI,
        "code_challenge_method": "S256",
        "code_challenge": challenge,
        "scope": SCOPES,
        "state": secrets.token_urlsafe(16),
    })
    print("\n  A browser window will open. Log in with Spotify and click 'Agree'.")
    print("  If nothing happens, open this URL manually:\n")
    print("  https://accounts.spotify.com/authorize?" + params + "\n")
    webbrowser.open("https://accounts.spotify.com/authorize?" + params)

    code_holder = {}

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            qs = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            if "code" in qs:
                code_holder["code"] = qs["code"][0]
                self.send_response(200)
                self.send_header("Content-Type", "text/html")
                self.end_headers()
                self.wfile.write(b"<h2>Success! Close this tab and go back to the terminal.</h2>")
            else:
                self.send_response(400)
                self.end_headers()
                self.wfile.write(b"<h2>Authorization failed. Close this tab and try again.</h2>")

        def log_message(self, *a):
            pass

    with socketserver.TCPServer(("127.0.0.1", 8888), Handler) as httpd:
        httpd.handle_request()

    if "code" not in code_holder:
        sys.exit("  ERROR: no authorization code received.")

    req = urllib.request.Request(
        "https://accounts.spotify.com/api/token",
        data=urllib.parse.urlencode({
            "grant_type": "authorization_code",
            "code": code_holder["code"],
            "redirect_uri": REDIRECT_URI,
            "client_id": CLIENT_ID,
            "code_verifier": verifier,
        }).encode(),
        headers={"Content-Type": "application/x-www-form-urlencoded"})
    with urllib.request.urlopen(req) as resp:
        tokens = json.load(resp)
    tokens["obtained_at"] = time.time()
    TOKEN_FILE.write_text(json.dumps(tokens))
    return tokens


def load_tokens():
    if TOKEN_FILE.exists():
        return json.loads(TOKEN_FILE.read_text())
    return authorize()


def refresh(tokens):
    if time.time() - tokens["obtained_at"] < tokens.get("expires_in", 3600) - 60:
        return tokens
    req = urllib.request.Request(
        "https://accounts.spotify.com/api/token",
        data=urllib.parse.urlencode({
            "grant_type": "refresh_token",
            "refresh_token": tokens.get("refresh_token", ""),
            "client_id": CLIENT_ID,
        }).encode(),
        headers={"Content-Type": "application/x-www-form-urlencoded"})
    with urllib.request.urlopen(req) as resp:
        tokens.update(json.load(resp))
    tokens["obtained_at"] = time.time()
    TOKEN_FILE.write_text(json.dumps(tokens))
    return tokens


def api(method, url, token, payload=None):
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(url, data=data, method=method, headers={
        "Authorization": "Bearer " + token,
        "Content-Type": "application/json",
    })
    try:
        with urllib.request.urlopen(req) as resp:
            return resp.status, None
    except urllib.error.HTTPError as e:
        try:
            body = e.read().decode("utf-8", "replace")[:500]
        except Exception:
            body = ""
        return e.code, body


def fetch_liked_uris(access):
    liked_now, url = set(), "https://api.spotify.com/v1/me/tracks?limit=50"
    while url:
        req = urllib.request.Request(url, headers={"Authorization": "Bearer " + access})
        with urllib.request.urlopen(req) as resp:
            page = json.load(resp)
        liked_now.update(item["track"]["uri"] for item in page["items"])
        url = page["next"]
    return liked_now


# ------------------------------------------------------------
# main
# ------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Remove liked songs that are already in one of your playlists.")
    parser.add_argument("export_dir", help="folder with your Spotify privacy export "
                        "(containing YourLibrary.json and Playlist*.json)")
    parser.add_argument("--dry-run", action="store_true",
                        help="only show duplicates, don't remove anything")
    parser.add_argument("--report", action="store_true",
                        help="write duplicates_report.md and keep_report.md")
    parser.add_argument("--yes", action="store_true",
                        help="skip the confirmation prompt (careful!)")
    args = parser.parse_args()

    print(r"""
   ____             _         _____       _     _  __
  / ___| _ __   ___| |__     |___ /___  _| |__ | |/ /___ _ __
  \___ \| '_ \ / __| '_ \     |_ \ / \  | '_ \| ' // _ \ '__|
   ___) | | | | (__| | | |   ___) | (_) | |_) | . \  __/ |
  |____/|_| |_|\___|_| |_|  |____/ \___/|_.__/|_|\_\___|_|
        liked songs dedupe — playlists are never touched
""".strip("\n"))

    liked, playlists = load_export(args.export_dir)
    dupes = find_duplicates(liked, playlists)
    keep = [f"{t.get('artist', '?')} — {t.get('track', '?')}"
            for t in liked if t.get("uri") not in dupes]

    print(f"\n  RESULT: {len(dupes)} of {len(liked)} liked songs "
          f"are already in a playlist.")
    print(f"  {len(keep)} liked songs are not in any playlist (untouched).")

    if args.report:
        write_reports(dupes, liked, keep)
    if args.dry_run:
        print("\n  --dry-run: nothing removed. "
              "Re-run without --dry-run when you're ready.")
        return
    if not dupes:
        print("\n  No duplicates found. Nothing to do. Bye!")
        return

    print("\n  Preview (first 10):")
    for uri in list(dupes)[:10]:
        d = dupes[uri]
        print(f"    - {d['name']}  [{' | '.join(d['playlists'])}]")
    if len(dupes) > 10:
        print(f"    ... and {len(dupes) - 10} more\n")

    if CLIENT_ID == "PASTE_YOUR_CLIENT_ID_HERE":
        sys.exit("\n  To remove tracks, set CLIENT_ID in this file "
                 "(free, ~5 min — see README step 3).")

    tokens = refresh(load_tokens())
    access = tokens["access_token"]
    print("  Token scopes:", tokens.get("scope", "(none!)"))
    if "user-library-modify" not in tokens.get("scope", ""):
        sys.exit("  ERROR: token missing 'user-library-modify'. "
                 "Delete spotify_token.json and re-run.")

    print("\n  Checking which tracks are STILL in Liked Songs right now ...")
    liked_now = fetch_liked_uris(access)
    todo = {u: d for u, d in dupes.items() if u in liked_now}
    print(f"  {len(todo)} of {len(dupes)} duplicates are still in Liked Songs.")

    if not todo:
        print("  Nothing left to do. Bye!")
        return

    if not args.yes:
        answer = input(f"\n  Remove {len(todo)} songs from LIKED SONGS? "
                       "Playlists are NOT touched. Type YES to confirm: ")
        if answer.strip().upper() != "YES":
            print("  Cancelled. Nothing was changed.")
            return

    ok = fail = 0
    items = list(todo.keys())
    error_shown = False
    for i in range(0, len(items), BATCH_SIZE):
        batch = items[i:i + BATCH_SIZE]
        uris_param = urllib.parse.quote(",".join(batch))
        status, err_body = api("DELETE",
                               "https://api.spotify.com/v1/me/library?uris=" + uris_param,
                               access)
        if status == 200:
            ok += len(batch)
        else:
            fail += len(batch)
            if not error_shown:
                print(f"    Spotify error details: {err_body}")
                error_shown = True
        print(f"    batch {i // BATCH_SIZE + 1}: "
              f"{'OK' if status == 200 else 'FAILED (code ' + str(status) + ')'}")
        if status == 403 and i == 0:
            print("    Stopping early — no point retrying the same error.")
            break
        time.sleep(0.5)

    print(f"\n  Done! Removed {ok} tracks from Liked Songs."
          + (f"  {fail} failed — re-run to retry them." if fail else ""))
    print("  All your playlists are untouched.")


if __name__ == "__main__":
    main()
