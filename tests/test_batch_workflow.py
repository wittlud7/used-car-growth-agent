import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from car_agent import CarAgent
from store import Store
from workflow import Workflow, CASES, score
from test_agent import answer, calls, change


class BatchWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.temp.name) / 'workflow.db')
        self.agent = CarAgent(self.store, caller=lambda *args: answer())
        self.flow = Workflow(self.store, self.agent)

    def tearDown(self):
        self.temp.cleanup()

    def run_job(self, items=None, mode='rules', benchmark=False, parent=None):
        with patch('workflow.threading.Thread'):
            j = self.flow.start(items, mode, benchmark, parent)
        self.flow._work(j)
        return self.flow.get(j['id'])

    def test_rule_batch_routes_all_acceptance_cases_and_does_not_contact(self):
        job = self.run_job(CASES)
        self.assertEqual(job['status'], 'completed')
        for item, case in zip(job['items'], CASES):
            self.assertTrue(score(item['results']['rules'], case['expected'])['passed'], item)
        self.assertEqual(self.store.tasks(), [])
        self.assertEqual(job['summary']['groups']['rules']['input_tokens'], 0)

    def test_stop_contact_cannot_record_contact_or_start_agent(self):
        self.agent.chat = lambda *args: self.fail('Must not call model for rejected contact')
        with patch('workflow.public_config', return_value={'ready':True, 'model':'mock'}):
            job = self.run_job([CASES[2]], mode='agent')
        body = dict(job_id=job['id'], item_id=job['items'][0]['id'], owner='顾问', note='模拟记录', outcome='contacted')
        with self.assertRaises(ValueError):self.flow.feedback(body)
        body['outcome'] = 'stop'
        self.assertEqual(len(self.flow.feedback(body)['feedback']), 1)

    def test_agent_tool_results_are_routed_and_no_task_is_created(self):
        responses = iter([calls(('update_requirements', {'changes': [change('direction','buy','买车'),change('city','北京','北京'),change('budget_max',15,'15万以内'),change('preference','卡罗拉','卡罗拉')]})),calls(('search_vehicles', {})),answer('找到车辆')])
        self.agent.caller = lambda *args: next(responses)
        result = self.flow.process(CASES[0], 'agent')
        self.assertEqual(result['action'], 'match')
        self.assertEqual(result['ids'], ['V001','V002'])
        self.assertEqual(result['usage']['input_tokens'], 30)
        self.assertEqual(self.store.tasks(), [])

    def test_agent_answer_without_tool_search_cannot_become_a_match(self):
        self.agent.caller = lambda *args: answer('已找到V001，已经预约')
        result = self.flow.process(CASES[0], 'agent')
        self.assertNotEqual(result['action'], 'match')
        self.assertEqual(result['ids'], [])

    def test_direct_model_receives_same_snapshot_without_gold_and_errors_are_scored(self):
        def caller(messages):
            payload = json.loads(messages[1]['content'])
            self.assertIn('inventory', payload)
            self.assertNotIn('expected', payload)
            return answer(json.dumps({'action':'match','ids':['V015'],'reason':'推荐'}))
        self.flow.caller = caller
        result = self.flow.process(CASES[4], 'direct')
        s = score(result, CASES[4]['expected'])
        self.assertFalse(s['passed'])
        self.assertEqual(s['unsafe_ids'], ['V015'])
        self.flow.caller = lambda *args: answer('invalid JSON')
        failed = self.flow.process(CASES[0], 'direct')
        self.assertFalse(failed['ok'])
        self.assertEqual(failed['action'], 'failed')

    def test_followup_retains_original_and_previous_batch(self):
        old = self.run_job([{'name':'小张','channel':'模拟','text':'我要买车，北京，卡罗拉'}])
        self.assertEqual(old['items'][0]['results']['rules']['action'], 'clarify')
        new = self.run_job([{'name':'小张','channel':'模拟','text':'总预算15万以内'}], parent={'job_id':old['id'],'item_id':old['items'][0]['id']})
        self.assertEqual(new['items'][0]['results']['rules']['action'], 'match')
        self.assertEqual(self.flow.get(old['id'])['items'][0]['results']['rules']['action'], 'clarify')
        self.assertIn('客户补充', new['items'][0]['text'])

    def test_feedback_audit_is_persistent_and_rejects_invalid_seconds(self):
        job = self.run_job([CASES[0]])
        body = dict(job_id=job['id'], item_id=job['items'][0]['id'], owner='模拟顾问', outcome='reviewed', note='模拟核查结果', seconds=12)
        self.flow.feedback(body)
        self.assertEqual(Workflow(self.store).get(job['id'])['feedback'][0]['seconds'], 12)
        body['seconds'] = float('nan')
        with self.assertRaises(ValueError):self.flow.feedback(body)

    def test_duplicate_input_dedup_and_active_batch_lock_and_restart_recovery(self):
        with patch('workflow.threading.Thread'):
            job = self.flow.start([CASES[0], CASES[0]], 'rules')
            self.assertEqual(len(job['items']), 1)
            with self.assertRaises(ValueError):self.flow.start([CASES[1]], 'rules')
        restored = Workflow(self.store).get(job['id'])
        self.assertEqual(restored['status'], 'interrupted')
        self.assertEqual(restored['items'][0]['status'], 'interrupted')

    def test_model_failure_and_no_configuration_do_not_fall_back_to_rules(self):
        with patch('workflow.public_config', return_value={'ready':False}):
            with self.assertRaises(ValueError):self.flow.start([CASES[0]], 'agent')
        self.flow.caller = lambda *args: (_ for _ in ()).throw(RuntimeError('模型服务连接失败'))
        self.assertFalse(self.flow.process(CASES[0], 'direct')['ok'])
        with self.assertRaises(ValueError):self.flow.start([{'name':'x','channel':'x','text':'a'}], 'rules')

    def test_cancel_stops_remaining_items_without_losing_completed_result(self):
        original = self.flow.process
        def process(item, mode):
            result = original(item, mode)
            self.flow.cancel(self.flow.active)
            return result
        self.flow.process = process
        job = self.run_job(CASES[:2])
        self.assertEqual(job['status'], 'cancelled')
        self.assertEqual(job['items'][0]['status'], 'done')
        self.assertEqual(job['items'][1]['status'], 'cancelled')
        self.assertEqual(len(job['items'][0]['results']), 1)
