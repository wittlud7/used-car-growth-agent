import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import matching
from matching import match_buy, match_sell, validate_query
from store import Store


class MatchTaskTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.store=Store(Path(self.temp.name)/"tasks.db")
        self.buy_query=validate_query({"direction":"buy","city":"北京","preference":"卡罗拉","budget_max":15})
        self.run=self.store.save_matching(match_buy(self.buy_query))

    def tearDown(self):
        self.temp.cleanup()

    def create_buy(self,**changes):
        args={"run_id":self.run["id"],"candidate_id":"V001","customer":"模拟买家","owner":"模拟顾问","preferred_at":"2030-01-02T10:00","note":"测试待办，无实际预约"}
        args.update(changes)
        return self.store.create_match_task(**args)

    def test_task_create_is_pending_idempotent_and_persistent(self):
        first=self.create_buy()
        again=self.create_buy()
        self.assertEqual(first["id"],again["id"])
        self.assertEqual(first["status"],"pending")
        self.assertTrue(first["preferred_at"].endswith("+08:00"))
        restarted=Store(self.store.path)
        self.assertEqual(len(restarted.tasks()),1)
        self.assertEqual(restarted.get_matching(self.run["id"])["shortlist"],["V001"])
        self.assertEqual(len(first["events"]),1)

    def test_required_fields_and_datetime_are_validated(self):
        for changes in ({"owner":""},{"customer":""},{"preferred_at":"不是日期"},{"owner":"x"*41}):
            with self.subTest(changes=changes),self.assertRaises(ValueError):self.create_buy(**changes)
        self.assertEqual(self.store.tasks(),[])

    def test_ineligible_or_nonmatched_candidate_cannot_create(self):
        with self.assertRaises(ValueError):self.create_buy(candidate_id="V015")
        current=[dict(v,status="已售") if v["id"]=="V001" else v for v in matching.INVENTORY]
        with patch("matching.INVENTORY",current),self.assertRaises(ValueError):self.create_buy()

    def test_cannot_skip_confirmation_or_overwrite_stale_version(self):
        task=self.create_buy()
        with self.assertRaises(ValueError):self.store.update_match_task(task["id"],"completed",0,"测试")
        confirmed=self.store.update_match_task(task["id"],"confirmed",0,"模拟确认时间")
        with self.assertRaises(ValueError):self.store.update_match_task(task["id"],"cancelled",0,"旧页面")
        completed=self.store.update_match_task(task["id"],"completed",confirmed["version"],"模拟看车完成")
        self.assertEqual(completed["status"],"completed")
        with self.assertRaises(ValueError):self.store.update_match_task(task["id"],"confirmed",completed["version"],"不可重开")

    def test_cancel_pending_is_recorded_without_contact(self):
        task=self.create_buy()
        task=self.store.update_match_task(task["id"],"cancelled",0,"模拟客户取消")
        self.assertEqual(task["status"],"cancelled")
        self.assertEqual([e["status"] for e in task["events"]],["pending","cancelled"])
        self.assertEqual(self.store.metrics()["funnel"]["contacted"],0)

    def test_confirmation_rechecks_current_inventory(self):
        task=self.create_buy()
        current=[dict(v,status="已售") if v["id"]=="V001" else v for v in matching.INVENTORY]
        with patch("matching.INVENTORY",current),self.assertRaises(ValueError):
            self.store.update_match_task(task["id"],"confirmed",0,"模拟确认")
        self.assertEqual(self.store.get_task(task["id"])["version"],0)

    def create_seller_task(self):
        lead_id=self.store.add("模拟买家林","测试","北京，预算12到15万，想买卡罗拉，下周购车。")[0]
        lead=self.store.analyze(lead_id,"rules")
        query=validate_query({"direction":"sell","city":"北京","model":"卡罗拉","year":2022,"mileage":3.2,"price":12.6})
        record=self.store.save_matching(match_sell(query,self.store.list()))
        task=self.store.create_match_task(record["id"],lead_id,"错误称呼应被忽略","模拟顾问")
        return lead,task

    def test_seller_requires_review_then_completion_updates_lead_once(self):
        lead,task=self.create_seller_task()
        self.assertEqual(task["customer"],"模拟买家林")
        with self.assertRaises(ValueError):self.store.update_match_task(task["id"],"confirmed",0,"不可跳过咨询审核")
        self.store.transition(lead["id"],"approved",lead["version"],owner="模拟顾问")
        task=self.store.update_match_task(task["id"],"confirmed",0,"模拟审核通过并确认待办")
        self.assertEqual(self.store.get(lead["id"])["status"],"approved")
        task=self.store.update_match_task(task["id"],"completed",task["version"],"模拟已联系，无真实消息")
        self.assertEqual(self.store.get(lead["id"])["status"],"contacted")
        self.assertEqual(self.store.metrics()["funnel"]["contacted"],1)
        with self.assertRaises(ValueError):self.store.update_match_task(task["id"],"completed",task["version"],"重复提交")

    def test_closed_buyer_invalidates_seller_task(self):
        lead,task=self.create_seller_task()
        self.store.transition(lead["id"],"rejected",lead["version"],note="模拟不再跟进")
        with self.assertRaises(ValueError):self.store.update_match_task(task["id"],"confirmed",0,"不能继续")
        self.assertEqual(self.store.get_task(task["id"])["status"],"pending")

    def test_update_note_required_and_export_contains_task(self):
        task=self.create_buy()
        with self.assertRaises(ValueError):self.store.update_match_task(task["id"],"confirmed",0,"")
        self.assertEqual(self.store.snapshot()["tasks"][0]["id"],task["id"])


if __name__=="__main__":unittest.main()
