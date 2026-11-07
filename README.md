# Spotify Liked Songs Dedupe 🎧

![Python 3.8+](https://img.shields.io/badge/python-3.8%2B-blue)
![No dependencies](https://img.shields.io/badge/dependencies-none-success)
![License: MIT](https://img.shields.io/badge/license-MIT-green)
![CI](https://github.com/Niko-Jensen/liked-songs-dedupe/actions/workflows/ci.yml/badge.svg)

Tired of a Liked Songs list full of tracks that already live in your playlists? This tool finds every liked song that's already in one of your playlists and removes it from Liked Songs - **your playlists are never touched**.

Built after Spotify's February 2026 API migration: it uses the new `DELETE /me/library` endpoint (the old `DELETE /me/tracks` returns `403 Forbidden` for development-mode apps).

## What it does

1. Reads your official Spotify privacy export (liked songs + all playlists)
2. Matches every liked track against every playlist by exact Spotify track ID
3. Shows you exactly which liked songs are duplicates (and in which playlists)
4. With your confirmation, removes those tracks from Liked Songs via the Spotify Web API

```
  RESULT: 288 of 738 liked songs are already in a playlist.
  450 liked songs are not in any playlist (untouched).

  Preview (first 10):
    - Kero Kero Bonito - Flamingo  [MEME | coolio]
    - Queens of the Stone Age - Go With The Flow  [GUIMS | My Shazam Tracks]
    ...
```

## Quick start

**Requirements:** Python 3.8+ (no third-party packages needed) and a Spotify account. A Premium subscription is required by Spotify for development-mode apps (see step 3).

### Step 1 - Request your Spotify data export

1. Go to [spotify.com/account/privacy](https://www.spotify.com/account/privacy/)
2. Under **Account data**, click **Request my Data** (the basic export is enough)
3. Spotify emails you a download link (usually within a few days)
4. Unzip it - you need the folder containing `YourLibrary.json` and `Playlist1.json` (possibly more `Playlist*.json` files)

### Step 2 - Run a dry run (no account needed yet)

```bash
python liked_dedupe.py /path/to/your/export --dry-run --report
```

This just reads your export and prints the summary. `--report` also writes `duplicates_report.md` and `keep_report.md` so you have the full lists on disk.

### Step 3 - Create a free Spotify developer app (one-time, ~5 min)

1. Go to [developer.spotify.com/dashboard](https://developer.spotify.com/dashboard) and log in
2. Click **Create app**, fill in anything for name/description
3. **Redirect URI:** add exactly `http://127.0.0.1:8888/callback`
4. Select **Web API**, save, then copy your **Client ID** from Settings
5. Paste it into `CLIENT_ID` at the top of `liked_dedupe.py`

> Note: Spotify requires development-mode app owners to have an active Premium subscription, and development apps can only be used by up to 5 users (you + anyone you add in User Management).

### Step 4 - Remove the duplicates

```bash
python liked_dedupe.py /path/to/your/export
```

A browser opens -> log in -> **Agree** -> back in the terminal, review the preview, type `YES`. Removal happens in batches of 40 and takes under a minute for a few hundred tracks.

Run it again any time - it only removes duplicates that are still liked, so it's safe to re-run after your next export.

## Options

| Flag | What it does |
| --- | --- |
| `--dry-run` | Only analyze, never touch your account |
| `--report` | Write `duplicates_report.md` and `keep_report.md` |
| `--yes` | Skip the confirmation prompt (use carefully) |

## Safety

- **Playlists are never modified** - the script only removes items from your Liked Songs
- Nothing happens until you type `YES` (or pass `--yes`)
- It re-checks your live Liked Songs before deleting, so already-unliked tracks are skipped
- Your token is stored locally in `spotify_token.json` - don't share it; delete it when done
- A 403 on the first batch stops the run early instead of hammering through errors

## FAQ

**Why does removal need a developer app at all?** Spotify has no bulk "unlike" feature, and the API is the only scriptable way. Creating the app is free and takes a few minutes.

**I get 403 Forbidden.** If you're using an older script that calls `DELETE /me/tracks`, that endpoint was removed in February 2026 for development-mode apps - this repo already uses the new `DELETE /me/library`. Other causes: token missing `user-library-modify` (delete `spotify_token.json`, re-run), or your Premium lapsed.

**Tracks in "My Shazam Tracks" worry me.** That playlist is auto-synced from Shazam. If a track's only home is that list and you ever disconnect Shazam, it would be gone from Spotify entirely. Move those tracks into a normal playlist first if you care about them.

**Does this delete anything from my playlists?** No. Removing a like only affects Liked Songs. Playlists are completely independent.

## Contributing

Found a bug or want a feature (e.g. keeping tracks that are only in auto-synced playlists)? Open an issue or a pull request - all contributions welcome.

## License

MIT - see [LICENSE](LICENSE).
