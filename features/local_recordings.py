"""Durable laptop MP4 copies and an owner-scoped cloud retry queue.

The uploader callback receives (verified_owner_id, immutable_name, Path) and must
use that same cloud key with upsert on every retry. It must bound network time.
No credentials or user access tokens are stored in this module's database.
"""
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import os
from pathlib import Path
import re
import sqlite3
import tempfile
import threading
import time
from uuid import uuid4

from flask import g, jsonify, request, send_file
from werkzeug.utils import secure_filename


OWNER = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,127}\Z")
RECORDING_ID = re.compile(r"[a-f0-9]{32}\Z")
PENDING_MESSAGE = "Saved on this laptop. Waiting to upload to Supabase."
RETRY_MESSAGE = "Saved on this laptop. Cloud upload will retry when a connection is available."
SYNCED_MESSAGE = "Saved on this laptop and uploaded to Supabase."


class LocalRecordingError(Exception):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


class LocalRecordings:
    PAGE_SIZE = 50
    LEASE_SECONDS = 180

    def __init__(self, data_dir, uploader, max_bytes=512 * 1024 * 1024):
        if not isinstance(max_bytes, int) or isinstance(max_bytes, bool) or max_bytes <= 0:
            raise ValueError("max_bytes must be a positive integer.")
        self.data_dir = Path(data_dir).expanduser().resolve()
        self.data_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
        self.files_dir = self.data_dir / "recordings"
        self.files_dir.mkdir(mode=0o700, exist_ok=True)
        if self.files_dir.resolve().parent != self.data_dir:
            raise ValueError("Recording files must remain in their configured data folder.")
        self.db_path = self.data_dir / "recordings.sqlite3"
        self.uploader = uploader
        self.max_bytes = max_bytes
        self._sync_lock = threading.Lock()
        self._start_lock = threading.Lock()
        self._wake = threading.Event()
        self._stop = threading.Event()
        self._thread = None
        with self._database() as db:
            db.execute("PRAGMA journal_mode=WAL")
            db.execute("""CREATE TABLE IF NOT EXISTS recordings (
                id TEXT PRIMARY KEY, owner TEXT NOT NULL, name TEXT NOT NULL,
                source TEXT NOT NULL, size INTEGER NOT NULL, created_at REAL NOT NULL,
                sync_state TEXT NOT NULL DEFAULT 'pending', attempts INTEGER NOT NULL DEFAULT 0,
                next_attempt_at REAL NOT NULL DEFAULT 0, last_attempt_at REAL,
                lease_until REAL, lease_token TEXT, lease_pid INTEGER,
                message TEXT NOT NULL, synced_at REAL, client_filename TEXT, sha256 TEXT,
                UNIQUE(owner, name))""")
            columns = {row[1] for row in db.execute("PRAGMA table_info(recordings)")}
            for column in ("client_filename", "sha256"):
                if column not in columns:
                    db.execute("ALTER TABLE recordings ADD COLUMN " + column + " TEXT")
            db.execute("CREATE UNIQUE INDEX IF NOT EXISTS recordings_client ON recordings(owner, client_filename)")
            db.execute("CREATE INDEX IF NOT EXISTS recordings_queue ON recordings(sync_state, next_attempt_at)")
            db.execute("CREATE INDEX IF NOT EXISTS recordings_owner ON recordings(owner, created_at)")
            self._recover_leases(db, time.time())
        # The local metadata contains no credentials, but its owner list is private.
        if self.db_path.exists():
            os.chmod(self.db_path, 0o600)

    @contextmanager
    def _database(self):
        db = sqlite3.connect(str(self.db_path), timeout=5)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA busy_timeout=5000")
        try:
            with db:
                yield db
        finally:
            db.close()

    @staticmethod
    def _owner(owner):
        if not isinstance(owner, str) or not OWNER.fullmatch(owner):
            raise LocalRecordingError("A valid signed-in user is required.", 401)
        return owner

    @staticmethod
    def _filename(name):
        if (not isinstance(name, str) or not 1 <= len(name) <= 180 or
                any(char in name for char in ("/", "\\", "\x00", "\r", "\n")) or
                name.startswith(".") or not name.lower().endswith(".mp4")):
            raise LocalRecordingError("Enter a plain MP4 filename without folders.")
        clean = secure_filename(name)
        if not clean.lower().endswith(".mp4") or clean.lower() == ".mp4":
            raise LocalRecordingError("Enter a valid MP4 filename.")
        return clean[:-4] + ".mp4"

    def _file_path(self, owner, name):
        self._owner(owner)
        if self._filename(name) != name:
            raise LocalRecordingError("Recording not found.", 404)
        owner_dir = (self.files_dir / owner).resolve()
        if owner_dir.parent != self.files_dir.resolve():
            raise LocalRecordingError("Recording folder is unavailable.", 500)
        path = owner_dir / name
        if path.resolve().parent != owner_dir:
            raise LocalRecordingError("Recording not found.", 404)
        return path

    @staticmethod
    def _validate_mp4(header, size):
        # Browser MP4 output begins with an ISO base media ftyp box. This confirms
        # the container signature, not playback quality or codec compatibility.
        if len(header) < 16 or header[4:8] != b"ftyp":
            raise LocalRecordingError("The recording must contain an MP4 container, not another video format.")
        box_size = int.from_bytes(header[:4], "big")
        if box_size == 1:
            if len(header) < 24:
                raise LocalRecordingError("The MP4 container header is incomplete.")
            box_size = int.from_bytes(header[8:16], "big")
            major_brand = bytes(header[16:20])
            minimum_size = 24
        else:
            major_brand = bytes(header[8:12])
            minimum_size = 16
        if box_size < minimum_size or box_size > size:
            raise LocalRecordingError("The MP4 container header is incomplete.")
        if major_brand in {b"avif", b"avis", b"heic", b"heix", b"mif1", b"msf1", b"M4A "}:
            raise LocalRecordingError("The uploaded file is not an MP4 video recording.")

    def _insert_record(self, row):
        with self._database() as db:
            db.execute("""INSERT INTO recordings
                (id, owner, name, source, size, created_at, sync_state, message, client_filename, sha256)
                VALUES (:id, :owner, :name, :source, :size, :created_at, 'pending', :message, :client_filename, :sha256)""", row)

    def _duplicate(self, owner, filename, source, size, digest):
        with self._database() as db:
            row = db.execute("SELECT * FROM recordings WHERE owner=? AND client_filename=?", (owner, filename)).fetchone()
        if row is None:
            return None
        if row["sha256"] != digest or row["size"] != size or row["source"] != source:
            raise LocalRecordingError("That recording filename already belongs to different video data. Choose a new filename.", 409)
        path = self._file_path(owner, row["name"])
        if not path.is_file() or path.stat().st_size != size:
            raise LocalRecordingError("The existing local copy is unavailable. Choose a new recording filename.", 409)
        return dict(row)

    @staticmethod
    def _sync_directory(directory):
        if os.name == "posix":
            descriptor = os.open(directory, os.O_RDONLY)
            try:
                os.fsync(descriptor)
            finally:
                os.close(descriptor)

    def save(self, owner, video, filename=None, source="main"):
        """Stream to disk first; acknowledge only after a durable metadata commit."""
        owner = self._owner(owner)
        if source not in {"main", "nightvision"}:
            raise LocalRecordingError("Recording source must be main or nightvision.")
        if video is None or not getattr(video, "stream", None):
            raise LocalRecordingError("A nonempty MP4 video is required.")
        original = self._filename(filename or video.filename)
        # Validate the multipart filename too, even when a display name is provided.
        self._filename(video.filename)
        if video.mimetype not in {"video/mp4", "application/mp4"}:
            raise LocalRecordingError("Upload an MP4 video with its video/mp4 content type.", 415)
        recording_id = uuid4().hex
        name = recording_id + "_" + original
        # The generated prefix can exceed the input's 180-character limit.
        if len(name) > 180:
            name = recording_id + "_" + original[:140] + ".mp4"
        final_path = self._file_path(owner, name)
        final_path.parent.mkdir(mode=0o700, exist_ok=True)
        pending_path = None
        installed = False
        try:
            with tempfile.NamedTemporaryFile(mode="wb", prefix=".upload-", suffix=".part", dir=final_path.parent, delete=False) as handle:
                pending_path = Path(handle.name)
                size, header, digest = 0, bytearray(), hashlib.sha256()
                while True:
                    chunk = video.stream.read(min(64 * 1024, self.max_bytes - size + 1))
                    if not chunk:
                        break
                    size += len(chunk)
                    if size > self.max_bytes:
                        raise LocalRecordingError("The recording exceeds the local file size limit.", 413)
                    if len(header) < 64:
                        header.extend(chunk[:64 - len(header)])
                    if len(header) >= 8 and header[4:8] != b"ftyp":
                        raise LocalRecordingError("The recording must contain an MP4 container, not another video format.")
                    digest.update(chunk)
                    handle.write(chunk)
                if not size:
                    raise LocalRecordingError("A nonempty MP4 video is required.")
                self._validate_mp4(header, size)
                handle.flush()
                os.fsync(handle.fileno())
            checksum = digest.hexdigest()
            existing = self._duplicate(owner, original, source, size, checksum)
            if existing is not None:
                pending_path.unlink()
                self._wake.set()
                return self._public(existing)
            os.replace(pending_path, final_path)
            installed = True
            self._sync_directory(final_path.parent)
            row = {"id": recording_id, "owner": owner, "name": name, "source": source,
                   "size": size, "created_at": time.time(), "message": PENDING_MESSAGE,
                   "sync_state": "pending", "client_filename": original, "sha256": checksum}
            try:
                self._insert_record(row)
            except sqlite3.IntegrityError:
                # A concurrent response-loss retry may have committed first.
                existing = self._duplicate(owner, original, source, size, checksum)
                if existing is None:
                    raise
                final_path.unlink()
                installed = False
                row = existing
        except Exception:
            if pending_path is not None:
                pending_path.unlink(missing_ok=True)
            if installed:
                final_path.unlink(missing_ok=True)
            raise
        self._wake.set()
        return self._public(row)

    @staticmethod
    def _public(row):
        return {"id": row["id"], "name": row["name"], "source": row["source"], "size": row["size"],
                "created_at": datetime.fromtimestamp(row["created_at"], timezone.utc).isoformat().replace("+00:00", "Z"),
                "sync_state": "synced" if row["sync_state"] == "synced" else "pending",
                "message": row["message"], "download_url": "/api/local-recordings/" + row["id"] + "/file"}

    def list(self, owner, offset=0):
        owner = self._owner(owner)
        if not isinstance(offset, int) or isinstance(offset, bool) or not 0 <= offset <= 1_000_000_000:
            raise LocalRecordingError("Recording offset must be a nonnegative integer.")
        with self._database() as db:
            rows = db.execute("SELECT * FROM recordings WHERE owner=? ORDER BY created_at DESC, id DESC LIMIT ? OFFSET ?",
                              (owner, self.PAGE_SIZE + 1, offset)).fetchall()
            pending = db.execute("SELECT COUNT(*) FROM recordings WHERE owner=? AND sync_state!='synced'", (owner,)).fetchone()[0]
        return {"recordings": [self._public(row) for row in rows[:self.PAGE_SIZE]],
                "has_more": len(rows) > self.PAGE_SIZE, "pending_count": pending}

    def get(self, owner, recording_id):
        owner = self._owner(owner)
        if not isinstance(recording_id, str) or not RECORDING_ID.fullmatch(recording_id):
            raise LocalRecordingError("Recording not found.", 404)
        with self._database() as db:
            row = db.execute("SELECT * FROM recordings WHERE id=? AND owner=?", (recording_id, owner)).fetchone()
        if row is None:
            raise LocalRecordingError("Recording not found.", 404)
        return row

    @staticmethod
    def _process_alive(pid):
        if not isinstance(pid, int) or pid <= 0:
            return False
        try:
            os.kill(pid, 0)
            return True
        except ProcessLookupError:
            return False
        except PermissionError:
            return True

    def _recover_leases(self, db, now):
        for row in db.execute("SELECT id, lease_until, lease_pid, lease_token FROM recordings WHERE sync_state='syncing'").fetchall():
            if not row["lease_until"] or row["lease_until"] <= now or not self._process_alive(row["lease_pid"]):
                db.execute("""UPDATE recordings SET sync_state='pending', lease_until=NULL,
                    lease_token=NULL, lease_pid=NULL, next_attempt_at=0, message=?
                    WHERE id=? AND sync_state='syncing' AND lease_token IS ?""",
                           (RETRY_MESSAGE, row["id"], row["lease_token"]))

    def _claim(self):
        now = time.time()
        with self._database() as db:
            db.execute("BEGIN IMMEDIATE")
            self._recover_leases(db, now)
            row = db.execute("""SELECT * FROM recordings WHERE sync_state='pending' AND next_attempt_at<=?
                ORDER BY next_attempt_at, created_at, id LIMIT 1""", (now,)).fetchone()
            if row is None:
                return None
            token = uuid4().hex
            db.execute("""UPDATE recordings SET sync_state='syncing', attempts=attempts+1,
                last_attempt_at=?, lease_until=?, lease_token=?, lease_pid=? WHERE id=?""",
                       (now, now + self.LEASE_SECONDS, token, os.getpid(), row["id"]))
            return {**dict(row), "lease_token": token, "attempts": row["attempts"] + 1}

    def sync_once(self):
        """Attempt at most three due clips; a second worker cannot claim a lease."""
        if self.uploader is None or not self._sync_lock.acquire(blocking=False):
            return 0
        attempted = 0
        try:
            for _ in range(3):
                row = self._claim()
                if row is None:
                    break
                attempted += 1
                try:
                    path = self._file_path(row["owner"], row["name"])
                    if not path.is_file() or path.stat().st_size != row["size"]:
                        raise OSError("Local recording unavailable")
                    if self.uploader(row["owner"], row["name"], path) is False:
                        raise RuntimeError("Upload did not succeed")
                except Exception:
                    # Never persist an exception string: HTTP exceptions may contain tokens.
                    delay = min(300, 30 * (2 ** min(row["attempts"] - 1, 4)))
                    with self._database() as db:
                        db.execute("""UPDATE recordings SET sync_state='pending', next_attempt_at=?,
                            lease_until=NULL, lease_token=NULL, lease_pid=NULL, message=?
                            WHERE id=? AND lease_token=?""",
                                   (time.time() + delay, RETRY_MESSAGE, row["id"], row["lease_token"]))
                else:
                    with self._database() as db:
                        db.execute("""UPDATE recordings SET sync_state='synced', synced_at=?,
                            lease_until=NULL, lease_token=NULL, lease_pid=NULL, message=?
                            WHERE id=? AND lease_token=?""",
                                   (time.time(), SYNCED_MESSAGE, row["id"], row["lease_token"]))
        finally:
            self._sync_lock.release()
        return attempted

    def request_sync(self, owner=None):
        if owner is not None:
            owner = self._owner(owner)
            # Manual retry may shorten exponential backoff, with a five-second
            # floor so repeated clicks cannot turn offline failure into a loop.
            with self._database() as db:
                db.execute("""UPDATE recordings SET next_attempt_at=0 WHERE owner=? AND sync_state='pending'
                    AND (last_attempt_at IS NULL OR last_attempt_at<=?)""", (owner, time.time() - 5))
        self._wake.set()

    def _run(self, interval):
        while not self._stop.is_set():
            self._wake.clear()
            try:
                self.sync_once()
            except Exception:
                # Disk/SQLite failures must not silently kill future retries.
                pass
            self._wake.wait(interval)

    def start(self, interval=30):
        if not isinstance(interval, (int, float)) or not 0 < interval <= 3600:
            raise ValueError("Worker interval must be above zero and at most one hour.")
        with self._start_lock:
            if self._thread is not None and self._thread.is_alive():
                return False
            self._stop.clear()
            self._thread = threading.Thread(target=self._run, args=(interval,), name="local-recording-sync", daemon=True)
            self._thread.start()
            return True

    def stop(self, timeout=1):
        self._stop.set()
        self._wake.set()
        if self._thread is not None and self._thread is not threading.current_thread():
            self._thread.join(timeout=timeout)

    def register(self, app, require_auth):
        @app.errorhandler(LocalRecordingError)
        def local_recording_error(error):
            return jsonify({"error": str(error)}), error.status

        def owner():
            return self._owner(getattr(g.get("user"), "id", None))

        @app.post("/api/local-recordings")
        @require_auth
        def save_local_recording():
            user_id = owner()
            try:
                recording = self.save(user_id, request.files.get("video"), request.form.get("filename"), request.form.get("source", "main"))
            except (OSError, sqlite3.Error):
                return jsonify({"error": "Could not save the recording on this laptop. Please retry."}), 500
            return jsonify({"success": True, "recording": recording}), 201

        @app.get("/api/local-recordings")
        @require_auth
        def list_local_recordings():
            try:
                offset = int(request.args.get("offset", "0"))
            except ValueError:
                raise LocalRecordingError("Recording offset must be a nonnegative integer.") from None
            return jsonify(self.list(owner(), offset))

        @app.get("/api/local-recordings/<recording_id>/file")
        @require_auth
        def download_local_recording(recording_id):
            row = self.get(owner(), recording_id)
            path = self._file_path(row["owner"], row["name"])
            if not path.is_file():
                raise LocalRecordingError("The local recording file is unavailable.", 404)
            response = send_file(path, mimetype="video/mp4", as_attachment=True, download_name=row["name"], conditional=True, max_age=0)
            response.headers["Cache-Control"] = "private, no-store"
            response.vary.add("Cookie")
            return response

        @app.post("/api/local-recordings/sync")
        @require_auth
        def sync_local_recordings():
            user_id = owner()
            self.request_sync(user_id)
            return jsonify({"success": True, "message": "Cloud sync requested. Local copies remain on this laptop.",
                            "pending_count": self.list(user_id)["pending_count"]}), 202
