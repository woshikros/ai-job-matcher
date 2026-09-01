import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from jinja2 import Environment, FileSystemLoader, select_autoescape

import job_matcher.storage as storage
from job_matcher.conversation_center import sync_liepin_history, sync_liepin_overview


class ConversationTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(); self.old_dir,self.old_db=storage.DATA_DIR,storage.DB_PATH
        storage.DATA_DIR=Path(self.temp.name); storage.DB_PATH=storage.DATA_DIR/"matcher.db"; storage.initialize()

    def tearDown(self):
        storage.DATA_DIR,storage.DB_PATH=self.old_dir,self.old_db; self.temp.cleanup()

    @patch("job_matcher.conversation_center.fetch_liepin_chat_overview")
    def test_overview_is_saved_and_system_notice_is_not_pending(self,fetch):
        fetch.return_value={"threads":[{"thread_id":"imid-1","recruiter_name":"李女士","company":"示例科技","last_message":"该职位竞争力PK报告已生成","last_sender":"recruiter","last_message_at":"10:30"}]}
        self.assertEqual(sync_liepin_overview()["thread_count"],1)
        self.assertEqual(storage.get_conversation("liepin","imid-1")["last_sender"],"system")
        self.assertEqual(storage.get_conversation_statistics()["needs_reply"],0)

    @patch("job_matcher.conversation_center.fetch_liepin_chat_history")
    def test_history_is_saved_without_duplicate_fallback(self,fetch):
        storage.upsert_conversation_threads("liepin",[{"thread_id":"imid-1","recruiter_name":"李女士"}])
        fetch.return_value={"messages":[{"message_id":"m1","sender":"recruiter","content":"方便发一下简历吗","sent_at":"2026-08-11T02:59:45.000Z"}],"thread":{"thread_id":"imid-1","last_message":"方便发一下简历吗","last_sender":"recruiter"}}
        sync_liepin_history("imid-1")
        storage.upsert_conversation_messages("liepin","imid-1",[{"message_id":"fallback-1","sender":"recruiter","content":"方便发一下简历吗","sent_at":"8月11日 10:59"}])
        self.assertEqual(len(storage.list_conversation_messages("liepin","imid-1")),1)

    def test_insights_separate_template_and_specific_feedback(self):
        storage.upsert_conversation_threads("liepin",[{"thread_id":"imid-1","recruiter_name":"李女士","company":"示例科技"}])
        storage.upsert_conversation_messages("liepin","imid-1",[
            {"message_id":"m1","sender":"recruiter","content":"我会认真看一下您的简历，合适的话联系您"},
            {"message_id":"m2","sender":"recruiter","content":"目前更需要生产开发经验，编码深度不太匹配"},
        ])
        result=storage.get_conversation_insights()
        self.assertEqual(result["generic_replies"],1)
        self.assertEqual(result["explicit_feedback"],1)
        self.assertEqual(result["themes"][0]["reason"],"技术栈或开发深度")

    def test_template_is_read_only_and_escapes_messages(self):
        env=Environment(loader=FileSystemLoader(Path(__file__).parents[1]/"templates"),autoescape=select_autoescape(["html"]))
        rendered=env.get_template("conversations.html").render(
            records=[],statistics={"threads":0,"needs_reply":0,"messages":1,"recruiter_contacted":1},
            sources=[{"status":"ok","error":""}],source_logos={},q="",needs_reply_filter="all",
            selected={"thread_id":"imid-1","recruiter_name":"HR","company":"示例"},
            messages=[{"sender":"recruiter","content":"<script>alert(1)</script>","sent_at":""}],
            needs_reply_records=[],application_candidates=[],linked_application=None,
            feedback_outcomes=storage.FEEDBACK_OUTCOMES,rejection_reasons=storage.REJECTION_REASONS,
            conversation_insights={"recruiter_messages":1,"generic_replies":0,"explicit_feedback":0},
        )
        self.assertIn("不发送消息、简历或联系方式",rendered)
        self.assertNotIn("<script>alert(1)</script>",rendered)
        self.assertNotIn("发送回复",rendered)


if __name__=="__main__": unittest.main()
