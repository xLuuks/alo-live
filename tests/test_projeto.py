import json
from pathlib import Path
from tempfile import TemporaryDirectory
import threading
import unittest
from unittest.mock import Mock, patch

import Teleprompter as server
from youtube_chat import YouTubeChats, YouTubeError, video_id


def comment(ident="m1", author="Maria", text="Um abraço!", time="2026-10-30T12:00:00Z"):
    return {"id": ident, "snippet": {"displayMessage": text, "publishedAt": time},
            "authorDetails": {"displayName": author}}


def slot(number=1, vid="abcdefghijk"):
    return {"slot": number, "video_id": vid, "channel": "Canal de teste", "title": "Live",
            "stop": threading.Event(), "state": "conectando", "detail": "", "interval": 30}


class YouTubeTests(unittest.TestCase):
    def test_links(self):
        for link in ("abcdefghijk", "https://youtu.be/abcdefghijk?t=1",
                     "https://www.youtube.com/watch?v=abcdefghijk&x=1",
                     "https://youtube.com/live/abcdefghijk?si=xyz"):
            self.assertEqual(video_id(link), "abcdefghijk")
        for link in ("https://evil.example/watch?v=abcdefghijk", "https://youtube.com/@canal/live", "abc"):
            with self.assertRaises(ValueError):
                video_id(link)

    def test_invalid_configuration_preserves_collection(self):
        chats = YouTubeChats()
        old = slot()
        chats.slots[1] = old
        with self.assertRaises(ValueError):
            chats.connect(["abcdefghijk", "abcdefghijk"], "key")
        self.assertIs(chats.slots[1], old)
        self.assertFalse(old["stop"].is_set())

    def test_two_independent_workers_and_disconnect(self):
        chats = YouTubeChats()
        with patch("youtube_chat.threading.Thread") as thread:
            chats.connect(["abcdefghijk", "12345678901"], "secret", 15)
        self.assertEqual(thread.call_count, 2)
        self.assertEqual(len(chats.snapshot()["sources"]), 2)
        self.assertNotIn("secret", json.dumps(chats.snapshot()))
        chats.disconnect()
        self.assertTrue(all(s["stop"].is_set() for s in chats.slots.values()))
        self.assertTrue(all(s["state"] == "desconectado" for s in chats.slots.values()))

    def test_ingestion_deduplication_and_stale_workers(self):
        chats = YouTubeChats()
        current = slot()
        chats.slots[1] = current
        chats._ingest(current, [comment(), comment()])
        self.assertEqual(len(chats.snapshot()["comments"]), 1)
        other = slot(2, "12345678901")
        chats.slots[2] = other
        chats._ingest(other, [comment()])
        self.assertEqual(len(chats.snapshot()["comments"]), 2)
        chats._ingest(slot(), [comment("stale")])
        current["stop"].set()
        chats._ingest(current, [comment("late")])
        self.assertEqual(len(chats.snapshot()["comments"]), 2)

    def test_buffer_is_bounded_and_evicted_comments_are_deduplicated(self):
        chats = YouTubeChats()
        current = slot()
        chats.slots[1] = current
        chats._ingest(current, [comment(str(i)) for i in range(1100)])
        self.assertEqual(len(chats.comments), 1000)
        chats._ingest(current, [comment("0")])
        self.assertNotIn("abcdefghijk:0", chats.comments)

    def test_worker_reads_video_and_chat(self):
        chats = YouTubeChats()
        current = slot()
        chats.slots[1] = current
        responses = [
            {"items": [{"snippet": {"channelTitle": "Canal real", "title": "Ao vivo"},
                        "liveStreamingDetails": {"activeLiveChatId": "chat-1"}}]},
            {"items": [comment()], "offlineAt": "2026-10-30T13:00:00Z"},
        ]
        with patch.object(chats, "_get", side_effect=responses) as get:
            chats._worker(current, "key")
        self.assertEqual(get.call_args_list[1].kwargs["liveChatId"], "chat-1")
        self.assertEqual(chats.snapshot()["comments"][0]["channel"], "Canal real")
        self.assertEqual(current["state"], "encerrado")

    def test_pagination_interval_and_retry(self):
        chats = YouTubeChats()
        current = slot()
        current["stop"] = Mock()
        current["stop"].is_set.return_value = False
        chats.slots[1] = current
        responses = [
            {"items": [{"snippet": {}, "liveStreamingDetails": {"activeLiveChatId": "chat"}}]},
            {"items": [comment()], "nextPageToken": "page-2", "pollingIntervalMillis": 45000},
            YouTubeError("Cota esgotada"),
        ]
        with patch.object(chats, "_get", side_effect=responses) as get:
            chats._worker(current, "key")
        current["stop"].wait.assert_called_once_with(45)
        self.assertEqual(get.call_args_list[2].kwargs["pageToken"], "page-2")
        self.assertEqual(current["state"], "erro")

    def test_transient_error_retries(self):
        chats = YouTubeChats()
        current = slot()
        chats.slots[1] = current
        current["stop"].wait = Mock(side_effect=lambda seconds: current["stop"].set())
        with patch.object(chats, "_get", side_effect=YouTubeError("Sem conexão", retry=True)):
            chats._worker(current, "key")
        self.assertEqual(current["state"], "reconectando")
        current["stop"].wait.assert_called_once_with(30)

    def test_api_error_does_not_expose_key(self):
        chats = YouTubeChats()
        response = Mock(ok=False, status_code=403)
        response.json.return_value = {"error": {"message": "URL com segredo", "errors": [{"reason": "quotaExceeded"}]}}
        with patch("youtube_chat.requests.get", return_value=response) as get:
            with self.assertRaises(YouTubeError) as caught:
                chats._get("videos", "super-secret", id="abcdefghijk")
        self.assertFalse(caught.exception.retry)
        self.assertNotIn("super-secret", str(caught.exception))
        self.assertNotIn("key", get.call_args.kwargs["params"])

    def test_reconnect_one_source_preserves_other_source_and_cursor(self):
        chats = YouTubeChats()
        with patch("youtube_chat.threading.Thread"):
            chats.connect(["abcdefghijk", "12345678901"], "secret")
        first, second = chats.slots[1], chats.slots[2]
        first["_token"] = "cursor"
        first["_chat_id"] = "chat"
        chats._ingest(first, [comment()])
        chats.comments["abcdefghijk:m1"]["sent"] = True
        with patch("youtube_chat.threading.Thread"):
            chats.reconnect(1)
        self.assertIs(chats.slots[2], second)
        self.assertFalse(second["stop"].is_set())
        self.assertTrue(first["stop"].is_set())
        self.assertEqual(chats.slots[1]["_token"], "cursor")
        self.assertTrue(chats.snapshot()["comments"][0]["sent"])
        self.assertNotIn("secret", json.dumps(chats.snapshot()))
        self.assertNotIn("cursor", json.dumps(chats.snapshot()))
        chats.disconnect(1)
        self.assertFalse(second["stop"].is_set())

    def test_replacing_video_only_clears_that_sources_comments(self):
        chats = YouTubeChats()
        with patch("youtube_chat.threading.Thread"):
            chats.connect(["abcdefghijk", "12345678901"], "key")
            chats._ingest(chats.slots[1], [comment()])
            chats._ingest(chats.slots[2], [comment()])
            chats.reconnect(1, "newvideo123")
        self.assertEqual([c["slot"] for c in chats.snapshot()["comments"]], [2])


if __name__ == "__main__":
    unittest.main()
