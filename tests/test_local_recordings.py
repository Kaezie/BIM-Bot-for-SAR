"""Offline persistence, access control and durable cloud retry checks."""
from concurrent.futures import ThreadPoolExecutor
from functools import wraps
import io
from pathlib import Path
import sqlite3
import tempfile
import threading
import time
import types
import unittest
from unittest.mock import MagicMock, patch

from flask import Flask, g, jsonify, request
from werkzeug.datastructures import FileStorage

from features.local_recordings import LocalRecordings, LocalRecordingError


MP4 = (24).to_bytes(4, "big") + b"ftypisom\x00\x00\x02\x00isommp42" + (16).to_bytes(4, "big") + b"mdat12345678"


class LocalRecordingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name) / "local-data"
        self.uploader = MagicMock(return_value=None)
        self.store = LocalRecordings(self.directory, self.uploader)
        self.addCleanup(self.store.stop)
        self.app = Flask(__name__)

        def auth(fn):
            @wraps(fn)
            def wrapped(*args, **kwargs):
                owner = request.headers.get("X-Test-Owner")
                if not owner:
                    return jsonify(error="Unauthorized"), 401
                g.user = types.SimpleNamespace(id=owner)
                return fn(*args, **kwargs)
            return wrapped

        self.store.register(self.app, auth)
        self.client = self.app.test_client()
        self.headers = {"X-Test-Owner": "operator-a"}

    @staticmethod
    def video(data=MP4, name="clip.mp4", mimetype="video/mp4"):
        return FileStorage(stream=io.BytesIO(data), filename=name, content_type=mimetype)

    def save(self, owner="operator-a", filename="clip.mp4", data=MP4, source="main"):
        return self.store.save(owner, self.video(data), filename, source)

    def post(self, filename="clip.mp4", data=MP4, source="main", headers=None, mimetype="video/mp4"):
        return self.client.post("/api/local-recordings", headers=headers or self.headers,
                                data={"filename": filename, "source": source,
                                      "video": (io.BytesIO(data), "clip.mp4", mimetype)})

    def files(self):
        return list(self.store.files_dir.rglob("*.mp4")) + list(self.store.files_dir.rglob("*.part"))

    def test_offline_save_returns_only_after_local_file_and_queue_are_durable(self):
        response = self.post(source="nightvision")
        self.assertEqual(response.status_code, 201)
        recording = response.get_json()["recording"]
        self.assertEqual(recording["sync_state"], "pending")
        self.assertEqual(recording["source"], "nightvision")
        self.assertEqual(recording["size"], len(MP4))
        self.assertEqual((self.directory / "recordings" / "operator-a" / recording["name"]).read_bytes(), MP4)
        self.uploader.assert_not_called()
        restarted = LocalRecordings(self.directory, self.uploader)
        self.assertEqual(restarted.list("operator-a")["pending_count"], 1)
        self.assertEqual(restarted.list("operator-a")["recordings"][0]["id"], recording["id"])

    def test_local_download_is_owner_only_and_remains_available_after_sync(self):
        recording = self.save()
        self.assertEqual(self.client.get(recording["download_url"]).status_code, 401)
        self.assertEqual(self.client.get(recording["download_url"], headers={"X-Test-Owner": "operator-b"}).status_code, 404)
        self.assertEqual(self.store.sync_once(), 1)
        with self.client.get(recording["download_url"], headers=self.headers) as response:
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.mimetype, "video/mp4")
            self.assertIn("attachment", response.headers["Content-Disposition"])
            self.assertIn("no-store", response.headers["Cache-Control"])
            self.assertEqual(response.data, MP4)
        self.assertEqual(self.store.list("operator-a")["recordings"][0]["sync_state"], "synced")
        self.assertEqual(self.store.list("operator-a")["pending_count"], 0)
        self.assertEqual(len(self.files()), 1)

    def test_response_loss_retry_returns_same_recording_and_conflicting_bytes_fail(self):
        first = self.post().get_json()["recording"]
        second = self.post().get_json()["recording"]
        self.assertEqual(first["id"], second["id"])
        self.assertEqual(len(self.files()), 1)
        conflict = self.post(data=MP4[:-1] + b"x")
        self.assertEqual(conflict.status_code, 409)
        self.assertEqual(len(self.files()), 1)
        conflict = self.post(source="nightvision")
        self.assertEqual(conflict.status_code, 409)

    def test_same_client_filename_for_different_owners_uses_different_cloud_keys(self):
        first = self.save()
        second = self.save(owner="operator-b")
        self.assertNotEqual(first["name"], second["name"])
        self.assertEqual(len(self.store.list("operator-a")["recordings"]), 1)
        self.assertEqual(len(self.store.list("operator-b")["recordings"]), 1)
        self.assertEqual(self.store.sync_once(), 2)
        self.assertEqual({call.args[0] for call in self.uploader.call_args_list}, {"operator-a", "operator-b"})

    def test_bad_owner_name_source_type_empty_and_fake_mp4_leave_no_files(self):
        for filename in ("../clip.mp4", "folder/clip.mp4", "folder\\clip.mp4", ".hidden.mp4", "clip.webm", "bad\nname.mp4"):
            with self.subTest(filename=filename), self.assertRaises(LocalRecordingError):
                self.save(filename=filename)
        with self.assertRaises(LocalRecordingError):
            self.save(owner="../other")
        for source in ("thermal", "MAIN", ""):
            self.assertEqual(self.post(source=source).status_code, 400)
        for data in (b"", b"not a video", b"\x1aE\xdf\xa3webm", b"\x00\x00\x00\x40ftypisomxxxx"):
            self.assertEqual(self.post(data=data).status_code, 400)
        self.assertEqual(self.post(mimetype="video/webm").status_code, 415)
        self.assertEqual(self.files(), [])
        self.assertEqual(self.store.list("operator-a")["pending_count"], 0)

    def test_oversize_reads_only_bounded_chunks_and_cleans_temporary_files(self):
        small = LocalRecordings(self.directory, self.uploader, max_bytes=32)
        stream = io.BytesIO(MP4)
        with patch.object(stream, "read", wraps=stream.read) as read, self.assertRaises(LocalRecordingError) as error:
            small.save("operator-a", FileStorage(stream=stream, filename="clip.mp4", content_type="video/mp4"))
        self.assertEqual(error.exception.status, 413)
        self.assertTrue(all(call.args[0] <= 33 for call in read.call_args_list))
        self.assertEqual(self.files(), [])

    def test_metadata_failure_rolls_back_installed_file_and_exposes_no_secret(self):
        with patch.object(self.store, "_insert_record", side_effect=sqlite3.OperationalError("secret-db-path")):
            response = self.post()
        self.assertEqual(response.status_code, 500)
        self.assertNotIn("secret-db-path", response.get_data(as_text=True))
        self.assertEqual(self.files(), [])
        self.assertEqual(self.store.list("operator-a")["pending_count"], 0)

    def test_failed_then_healthy_cloud_upload_reuses_exact_path_and_keeps_local_copy(self):
        recording = self.save()
        self.uploader.side_effect = [ConnectionError("http://secret-token@cloud/?key=private"), None]
        with patch("features.local_recordings.time.time", return_value=100):
            self.assertEqual(self.store.sync_once(), 1)
        pending = self.store.list("operator-a")["recordings"][0]
        self.assertEqual(pending["sync_state"], "pending")
        self.assertNotIn("secret-token", str(pending))
        with patch("features.local_recordings.time.time", return_value=101):
            self.assertEqual(self.store.sync_once(), 0)
        with patch("features.local_recordings.time.time", return_value=131):
            self.assertEqual(self.store.sync_once(), 1)
        self.assertEqual(self.uploader.call_args_list[0].args, self.uploader.call_args_list[1].args)
        owner, filename, file_path = self.uploader.call_args.args
        self.assertEqual((owner, filename), ("operator-a", recording["name"]))
        self.assertIsInstance(file_path, Path)
        self.assertEqual(file_path.read_bytes(), MP4)
        self.assertEqual(self.store.list("operator-a")["pending_count"], 0)

    def test_sync_batch_is_at_most_three_and_does_not_repeat_synced_clips(self):
        for number in range(4):
            self.save(filename=f"clip-{number}.mp4")
        self.assertEqual(self.store.sync_once(), 3)
        self.assertEqual(self.store.list("operator-a")["pending_count"], 1)
        self.assertEqual(self.store.sync_once(), 1)
        self.assertEqual(self.store.sync_once(), 0)
        self.assertEqual(len({call.args[1] for call in self.uploader.call_args_list}), 4)

    def test_concurrent_workers_cannot_upload_the_same_clip(self):
        recording = self.save()
        entered, release = threading.Event(), threading.Event()
        def upload(*args):
            entered.set()
            release.wait(2)
        self.uploader.side_effect = upload
        other = LocalRecordings(self.directory, self.uploader)
        with ThreadPoolExecutor(max_workers=2) as pool:
            first = pool.submit(self.store.sync_once)
            self.assertTrue(entered.wait(1))
            self.assertEqual(other.sync_once(), 0)
            self.assertEqual(self.store.sync_once(), 0)
            release.set()
            self.assertEqual(first.result(timeout=2), 1)
        self.uploader.assert_called_once()
        self.assertEqual(self.store.get("operator-a", recording["id"])["sync_state"], "synced")

    def test_concurrent_identical_local_retries_commit_one_clip_and_no_orphan(self):
        other = LocalRecordings(self.directory, self.uploader)
        with ThreadPoolExecutor(max_workers=2) as pool:
            first = pool.submit(self.save)
            second = pool.submit(other.save, "operator-a", self.video(), "clip.mp4", "main")
            results = [first.result(timeout=3), second.result(timeout=3)]
        self.assertEqual(results[0]["id"], results[1]["id"])
        self.assertEqual(len(self.files()), 1)
        self.assertEqual(self.store.list("operator-a")["pending_count"], 1)

    def test_expired_or_dead_process_lease_recovers_after_restart(self):
        recording = self.save()
        with self.store._database() as db:
            db.execute("UPDATE recordings SET sync_state='syncing', lease_until=?, lease_pid=?, lease_token='stale' WHERE id=?",
                       (time.time() + 1000, 2147483646, recording["id"]))
        restarted = LocalRecordings(self.directory, self.uploader)
        self.assertEqual(restarted.get("operator-a", recording["id"])["sync_state"], "pending")
        self.assertEqual(restarted.sync_once(), 1)

    def test_worker_starts_once_and_sync_request_returns_without_waiting_for_upload(self):
        self.save()
        entered, release = threading.Event(), threading.Event()
        def upload(*args):
            entered.set()
            release.wait(2)
        self.uploader.side_effect = upload
        self.assertTrue(self.store.start())
        self.assertTrue(entered.wait(1))
        self.assertFalse(self.store.start())
        started = time.monotonic()
        response = self.client.post("/api/local-recordings/sync", headers=self.headers)
        self.assertEqual(response.status_code, 202)
        self.assertLess(time.monotonic() - started, .5)
        release.set()
        self.store.stop(timeout=2)
        self.uploader.assert_called_once()

    def test_auth_owner_list_offset_and_missing_local_file(self):
        for method, route in [("get", "/api/local-recordings"), ("post", "/api/local-recordings"), ("post", "/api/local-recordings/sync")]:
            self.assertEqual(getattr(self.client, method)(route).status_code, 401)
        recording = self.save()
        self.assertEqual(self.client.get("/api/local-recordings", headers={"X-Test-Owner": "operator-b"}).get_json()["recordings"], [])
        for offset in ("-1", "text", "1000000001"):
            self.assertEqual(self.client.get("/api/local-recordings?offset=" + offset, headers=self.headers).status_code, 400)
        self.assertEqual(self.client.get("/api/local-recordings", headers={"X-Test-Owner": "../invalid"}).status_code, 401)
        self.files()[0].unlink()
        self.assertEqual(self.client.get(recording["download_url"], headers=self.headers).status_code, 404)

    def test_no_uploader_leaves_queue_pending_and_no_token_is_persisted(self):
        recording = self.save()
        no_cloud = LocalRecordings(self.directory, None)
        self.assertEqual(no_cloud.sync_once(), 0)
        row = dict(no_cloud.get("operator-a", recording["id"]))
        self.assertEqual(row["sync_state"], "pending")
        self.assertEqual(row["attempts"], 0)
        self.assertNotIn("token", row)
        self.assertNotIn("Authorization", str(row))


if __name__ == "__main__":
    unittest.main()
