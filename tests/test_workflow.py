import json
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from unittest.mock import patch
from http.server import ThreadingHTTPServer

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from engine import ModelFailure, parse_budget, run_model, run_rules, validate_model_profile
from evaluate import evaluate
from server import create_handler
from store import Store


TEXT = "我在北京，预算12到15万，想看卡罗拉，这周能看车吗？"
PROFILE = {"city":{"value":"北京","quote":"北京"},"budget":{"value":[12,15],"quote":"12到15万"},"timeline":{"value":"7d","quote":"这周"},"vehicle":{"value":"卡罗拉","quote":"卡罗拉"}}


class ExtractionTests(unittest.TestCase):
    def test_downpayment_and_mileage_are_not_total_budget(self):
        self.assertIsNone(parse_budget("首付3-5万，月供2000")[1])
        self.assertIsNone(parse_budget("跑了3万公里，首付2万")[1])
        self.assertEqual(parse_budget("预算8万，车跑了3万公里")[1],8)

    def test_conflicts_and_negation_do_not_become_high_priority(self):
        for text in ["不是北京，预算15万，下周买车", "北京或天津，预算15万，下周买车", "北京预算15万，不是这周买车", "北京预算10万，后来改15万，下周买车"]:
            with self.subTest(text=text):
                self.assertEqual(run_rules(text)["decision"]["priority"], "B")

    def test_opt_out_overrides_purchase_urgency(self):
        self.assertEqual(run_rules(TEXT+"不要联系我")["decision"]["priority"],"D")

    def test_unknown_fields_remain_unknown_and_no_hallucinated_inventory(self):
        result=run_rules("想看看二手车，能介绍一下吗？")
        self.assertIsNone(result["profile"]["budget_max"])
        self.assertIsNone(result["profile"]["city"])
        self.assertEqual(result["profile"]["timeline"],"unknown")
        self.assertNotIn("有现车", result["draft"])

    def test_model_evidence_rejects_invented_or_mismatched_values(self):
        for field,value,quote in [("city","上海","上海"),("budget",[1,2],"12到15万"),("timeline","30d","这周")]:
            payload=json.loads(json.dumps(PROFILE))
            payload[field]={"value":value,"quote":quote}
            with self.subTest(field=field),self.assertRaises(ValueError):
                validate_model_profile(payload,TEXT)

    def test_synthetic_evaluation_checks_independent_expected_fields(self):
        report=evaluate()
        self.assertEqual(report["sample_count"],12)
        self.assertEqual(report["passed_cases"],12)
        self.assertEqual(report["correct_fields"],48)
        self.assertEqual(report["supported_evidence"],report["total_evidence"])


class AgentTests(unittest.TestCase):
    def test_model_calls_real_dispatcher_in_sequence(self):
        requests=[]
        calls=[("read_consultation",{}),("read_policy",{}),("submit_profile",PROFILE),("create_followup_draft",{})]
        def fake(body):
            requests.append(body)
            name,args=calls[len(requests)-1]
            return {"output":[{"type":"function_call","call_id":f"c{len(requests)}","name":name,"arguments":json.dumps(args)}],"usage":{"input_tokens":10,"output_tokens":5}}
        result=run_model(TEXT,caller=fake)
        self.assertEqual(result["mode"],"llm")
        self.assertEqual(result["decision"]["priority"],"A")
        self.assertEqual(result["usage"],{"input_tokens":40,"output_tokens":20})
        self.assertTrue(any(x.get("type")=="function_call_output" for x in requests[-1]["input"]))

    def test_no_tool_response_never_claims_success(self):
        with self.assertRaises(ModelFailure):
            run_model(TEXT,caller=lambda _: {"output":[{"type":"message","content":[{"type":"output_text","text":"已处理"}]}]})

    def test_unknown_tools_and_iteration_limit(self):
        n=0
        def fake(_):
            nonlocal n
            n+=1
            return {"output":[{"type":"function_call","call_id":str(n),"name":"send_message","arguments":"{}"}]}
        with self.assertRaises(ModelFailure) as caught:
            run_model(TEXT,caller=fake)
        self.assertEqual(n,8)
        self.assertTrue(all(t["status"]=="error" for t in caught.exception.trace))

    def test_cannot_create_draft_before_reading_and_extracting(self):
        def fake(_):
            return {"output":[{"type":"function_call","call_id":"x","name":"create_followup_draft","arguments":"{}"}]}
        with self.assertRaises(ModelFailure) as caught:
            run_model(TEXT,caller=fake)
        self.assertIn("先成功提交画像",caught.exception.trace[0]["detail"])


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.store=Store(Path(self.temp.name)/"test.db")
        self.id=self.store.add("合成客户","测试",TEXT)[0]

    def tearDown(self):
        self.temp.cleanup()

    def test_dedup_and_persistence(self):
        self.assertFalse(self.store.add("合成客户","测试",TEXT)[1])
        self.assertEqual(len(Store(self.store.path).list()),1)

    def test_cannot_skip_review_or_outcome_stages(self):
        for status in ("approved","contacted","appointment","won"):
            with self.subTest(status=status),self.assertRaises(ValueError):
                self.store.transition(self.id,status,0,owner="测试",note="模拟")

    def test_full_flow_persists_review_and_cumulative_metrics(self):
        lead=self.store.analyze(self.id,"rules")
        self.assertEqual(self.store.metrics()["funnel"]["won"],0)
        lead=self.store.transition(self.id,"approved",lead["version"],"模拟顾问",draft="人工修改的话术")
        for status in ("contacted","appointment","won"):
            lead=self.store.transition(self.id,status,lead["version"],note="合成演示结果")
        self.assertEqual(lead["draft"],"人工修改的话术")
        self.assertEqual(self.store.metrics()["funnel"],dict.fromkeys(["total","analyzed","approved","contacted","appointment","won"],1))
        self.assertEqual(len(lead["events"]),6)
        with self.assertRaises(ValueError):
            self.store.analyze(self.id,"rules")

    def test_refused_contact_cannot_be_approved(self):
        lead_id=self.store.add("拒绝客户","测试",TEXT+"不要联系")[0]
        lead=self.store.analyze(lead_id,"rules")
        with self.assertRaises(ValueError):
            self.store.transition(lead_id,"approved",lead["version"],"测试顾问")

    def test_stale_updates_and_missing_owner_are_rejected(self):
        lead=self.store.analyze(self.id,"rules")
        with self.assertRaises(ValueError):
            self.store.transition(self.id,"approved",lead["version"])
        self.store.transition(self.id,"approved",lead["version"],"测试顾问")
        with self.assertRaises(ValueError):
            self.store.transition(self.id,"rejected",lead["version"],note="旧页面")

    def test_model_failure_is_logged_without_rule_fallback(self):
        with patch("store.run_model",side_effect=ModelFailure("模拟超时",[{"tool":"read_consultation","status":"error","detail":"timeout"}],{})):
            lead=self.store.analyze(self.id,"llm")
        self.assertEqual(lead["status"],"failed")
        self.assertEqual(lead["draft"],"")
        self.assertEqual(lead["runs"][0]["ok"],0)
        self.assertEqual(self.store.metrics()["funnel"]["analyzed"],0)


class HttpTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.store=Store(Path(self.temp.name)/"api.db")
        self.server=ThreadingHTTPServer(("127.0.0.1",0),create_handler(self.store))
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True)
        self.thread.start()
        self.base=f"http://127.0.0.1:{self.server.server_port}"

    def tearDown(self):
        self.server.shutdown();self.server.server_close();self.thread.join();self.temp.cleanup()

    def request(self,path,data=None,origin=None):
        headers={"Content-Type":"application/json"}
        if origin: headers["Origin"]=origin
        req=urllib.request.Request(self.base+path,data=None if data is None else json.dumps(data).encode(),headers=headers)
        with urllib.request.urlopen(req,timeout=5) as response:
            return json.load(response)

    def test_http_import_analyze_review_export(self):
        imported=self.request("/api/import",{"items":[{"name":"模拟","channel":"测试","text":TEXT}]})
        id=imported["ids"][0]
        analyzed=self.request("/api/analyze",{"ids":[id],"mode":"rules"})
        self.assertEqual(analyzed["results"][0]["status"],"pending")
        lead=self.request(f"/api/leads/{id}")
        self.request("/api/transition",{"id":id,"status":"approved","version":lead["version"],"owner":"模拟顾问"})
        self.assertEqual(self.request("/api/export")["leads"][0]["status"],"approved")

    def test_batch_validation_does_not_partially_import(self):
        with self.assertRaises(urllib.error.HTTPError) as caught:
            self.request("/api/import",{"items":[{"name":"模拟","channel":"测试","text":TEXT},{"name":"","channel":"测试","text":"错误"}]})
        self.assertEqual(caught.exception.code,400)
        self.assertEqual(self.store.list(),[])

    def test_cross_origin_write_and_private_files_are_blocked(self):
        with self.assertRaises(urllib.error.HTTPError) as caught:
            self.request("/api/seed",{},origin="https://unrelated.example")
        self.assertEqual(caught.exception.code,403)
        with self.assertRaises(urllib.error.HTTPError) as caught:
            self.request("/../server.py")
        self.assertEqual(caught.exception.code,404)

    def test_matching_endpoints_and_saved_candidates(self):
        parsed=self.request("/api/matching/parse",{"direction":"buy","text":"北京，预算15万以内，想买卡罗拉"})
        self.assertEqual(parsed["budget_max"],15)
        record=self.request("/api/matching/run",{"direction":"buy","city":"北京","preference":"卡罗拉","budget_max":15})
        self.assertEqual(len(record["result"]["matches"]),2)
        saved=self.request("/api/matching/shortlist",{"id":record["id"],"candidate_id":"V001"})
        self.assertEqual(saved["shortlist"],["V001"])
        self.assertEqual(self.request("/api/matching")["history"][0]["id"],record["id"])

    def test_match_task_create_update_and_state(self):
        record=self.request("/api/matching/run",{"direction":"buy","city":"北京","preference":"卡罗拉","budget_max":15})
        task=self.request("/api/tasks/create",{"run_id":record["id"],"candidate_id":"V001","customer":"模拟客户","owner":"模拟顾问"})
        self.assertEqual(task["status"],"pending")
        updated=self.request("/api/tasks/update",{"id":task["id"],"status":"confirmed","version":0,"note":"模拟确认"})
        self.assertEqual(updated["status"],"confirmed")
        self.assertEqual(self.request("/api/state")["tasks"][0]["id"],task["id"])

    def test_agent_session_routes_and_confirmation_requires_proposal(self):
        session=self.request('/api/agent/new',{})
        self.assertEqual(self.request('/api/agent/session/'+session['id'])['turns'],[])
        self.assertEqual(self.request('/api/agent')['sessions'][0]['id'],session['id'])
        with self.assertRaises(urllib.error.HTTPError) as caught:
            self.request('/api/agent/confirm',{'session_id':session['id'],'token':'fabricated'})
        self.assertEqual(caught.exception.code,400)


if __name__ == "__main__":
    unittest.main()
