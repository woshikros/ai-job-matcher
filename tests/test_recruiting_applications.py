import sqlite3, tempfile, unittest
from contextlib import closing
from datetime import date
from pathlib import Path
import job_matcher.storage as storage
from job_matcher.job_safety import evaluate_eligibility
from job_matcher.recruiting import classify_recruiter, detect_outsourcing

class RecruitingTests(unittest.TestCase):
    def test_outsourcing_and_recruiter_are_separate(self):
        job={"jobName":"FDE","company":"某大型公司"}
        self.assertEqual(classify_recruiter(job,"").recruiter_type,"headhunter")
        self.assertFalse(detect_outsourcing(job,"猎头代招"))
        self.assertEqual(evaluate_eligibility("本科 AI交付",job,"劳务派遣用工","active").verdict,"fail")
        self.assertEqual(evaluate_eligibility("本科 AI交付",{"jobName":"FDE","company":"示例"},"客户现场交付","active").verdict,"pass")

class ApplicationTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(); self.old=(storage.DATA_DIR,storage.DB_PATH); storage.DATA_DIR=Path(self.temp.name); storage.DB_PATH=storage.DATA_DIR/"matcher.db"; storage.initialize()
    def tearDown(self): storage.DATA_DIR,storage.DB_PATH=self.old; self.temp.cleanup()
    def add(self,n):
        job_id=f"liepin:{n}"; fp=f"fp-{n}"; storage.save_daily_report("2026-06-30","r.html",[{"job_id":job_id,"source":"liepin","fingerprint":fp,"company":f"公司{n}","name":"AI产品经理","score":80,"greeting":f"话术{n}","is_supplemental":False}]); storage.set_job_status(job_id,fp,"applied","liepin")
        with closing(sqlite3.connect(storage.DB_PATH)) as c,c: c.execute("UPDATE application_records SET applied_at='2026-07-01T09:00:00' WHERE job_id=?",(job_id,))
        return job_id
    def test_snapshot_search_feedback_and_review(self):
        first=""
        for n in range(50):
            job_id=self.add(n); first=first or job_id
            if n<10: storage.update_application_record(job_id,feedback_outcome="communicating")
        self.assertEqual(storage.search_application_records("公司0")[0]["greeting_text"],"话术0")
        review=storage.get_application_review(as_of=date(2026,7,10)); self.assertTrue(review["available"]); self.assertEqual(review["overall"]["progress_rate"],100)
        storage.set_job_status(first,"fp-0","pending","liepin"); self.assertEqual(len(storage.search_application_records()),49)
    def test_detailed_feedback_and_pending_queue(self):
        job_id=self.add(1)
        with self.assertRaisesRegex(ValueError,"至少选择一个原因"): storage.update_application_record(job_id,feedback_outcome="rejected")
        storage.update_application_record(job_id,feedback_outcome="rejected",rejection_reasons=["行业经验"],feedback_note="行业背景不匹配")
        row=storage.search_application_records(rejection_reason="行业经验")[0]
        self.assertEqual(row["feedback_note"],"行业背景不匹配")
        self.assertEqual(storage.get_pending_feedback(as_of=date(2026,7,10))["total"],0)

if __name__=="__main__": unittest.main()
