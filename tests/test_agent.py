import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from car_agent import CarAgent, valid_value
from model_gateway import public_config, responses_adapter
from store import Store


def answer(text='请补充城市和预算。'):
    return {'choices':[{'finish_reason':'stop','message':{'role':'assistant','content':text}}],'usage':{'prompt_tokens':10,'completion_tokens':5}}


def calls(*items):
    return {'choices':[{'finish_reason':'tool_calls','message':{'role':'assistant','content':None,'tool_calls':[{'id':str(i),'type':'function','function':{'name':name,'arguments':json.dumps(args,ensure_ascii=False)}} for i,(name,args) in enumerate(items)]}}],'usage':{'prompt_tokens':10,'completion_tokens':5}}


def change(field,value,evidence):return {'field':field,'value':value,'evidence':evidence}


class AgentTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.store=Store(Path(self.tmp.name)/'agent.db')
        self.agent=CarAgent(self.store,caller=lambda *a:answer())
        self.session=self.agent.create()

    def tearDown(self):self.tmp.cleanup()

    def data(self,text):
        data=self.agent.load(self.session['id'])
        data['messages'].append({'role':'user','content':text})
        return data

    def populate(self):
        text='我要买车，北京，预算十五万以内，卡罗拉。'
        data=self.data(text)
        self.agent.execute('update_requirements',{'changes':[change('direction','buy','买车'),change('city','北京','北京'),change('budget_max',15,'十五万以内'),change('preference','卡罗拉','卡罗拉')]},data,text)
        self.agent.execute('search_vehicles',{},data,text)
        return data,text

    def test_clarification_does_not_search_or_mutate(self):
        result=self.agent.chat(self.session['id'],'我想买车')
        self.assertTrue(result['turns'][-1]['ok'])
        self.assertIsNone(result['matching'])
        self.assertEqual(self.store.tasks(),[])

    def test_real_dispatch_loop_records_search_and_uses_model_selected_tools(self):
        responses=iter([calls(('update_requirements',{'changes':[change('direction','buy','买车'),change('city','北京','北京'),change('budget_max',15,'十五万以内'),change('preference','卡罗拉','卡罗拉')]})),calls(('search_vehicles',{})),answer('找到V001和V002。')])
        self.agent.caller=lambda *a:next(responses)
        result=self.agent.chat(self.session['id'],'买车，北京，十五万以内，卡罗拉')
        self.assertTrue(result['turns'][-1]['ok'])
        self.assertEqual([m['id'] for m in result['matching']['result']['matches']],['V001','V002'])
        self.assertEqual(result['turns'][-1]['usage'],{'input_tokens':30,'output_tokens':15})

    def test_missing_fields_return_clarification_not_default_conditions(self):
        data=self.data('买车')
        result=self.agent.execute('search_vehicles',{},data,'买车')
        self.assertIn('城市',result['needs_clarification'])
        self.assertIsNone(data['state']['last_record_id'])

    def test_first_capture_can_reference_previous_message_but_changes_cannot(self):
        data=self.data('买车，北京，预算10万。')
        data['messages'].append({'role':'user','content':'想看卡罗拉，之前也考虑过15万。'})
        self.agent.execute('update_requirements',{'changes':[change('city','北京','北京'),change('budget_max',10,'10万')]},data,'想看卡罗拉，之前也考虑过15万。')
        data['messages'].append({'role':'user','content':'有结果吗？'})
        with self.assertRaises(ValueError):self.agent.execute('update_requirements',{'changes':[change('budget_max',15,'15万')]},data,'有结果吗？')
        self.assertEqual(data['state']['requirements']['budget_max'],10)

    def test_forged_quotes_and_downpayment_do_not_set_budget(self):
        data=self.data('我在北京，首付3万。')
        for c in [change('city','上海','上海'),change('budget_max',3,'首付3万')]:
            with self.assertRaises(ValueError):self.agent.execute('update_requirements',{'changes':[c]},data,'我在北京，首付3万。')
        self.assertEqual(data['state']['requirements'],{})

    def test_explicit_numeric_and_chinese_evidence(self):
        self.assertEqual(valid_value('budget_max',15,'十五万'),15)
        self.assertEqual(valid_value('budget_max',15,'150000元'),15)
        self.assertEqual(valid_value('mileage_max',5,'五万公里以内'),5)
        with self.assertRaises(ValueError):valid_value('budget_max',20,'十五万')
        with self.assertRaises(ValueError):valid_value('nationwide',True,'不接受异地')

    def test_unknown_tool_is_blocked_and_comparison_needs_observed_ids(self):
        data,text=self.populate()
        with self.assertRaises(ValueError):self.agent.execute('send_message',{},data,text)
        with self.assertRaises(ValueError):self.agent.execute('compare_vehicles',{'ids':['V001','V015']},data,text)
        result=self.agent.execute('compare_vehicles',{'ids':['V001','V002']},data,text)
        self.assertEqual(len(result['vehicles']),2)

    def test_proposal_is_not_execution_and_confirmation_is_idempotent(self):
        data,text=self.populate()
        args={'candidate_id':'V001','customer':'模拟客户','owner':'模拟顾问','preferred_at':'','note':'模拟'}
        self.agent.execute('propose_task',args,data,text)
        self.agent.save(data)
        self.assertEqual(self.store.tasks(),[])
        token=data['state']['proposal']['token']
        with self.assertRaises(ValueError):self.agent.confirm(data['id'],'bad-token',args)
        first=self.agent.confirm(data['id'],token,args)
        second=self.agent.confirm(data['id'],token,args)
        self.assertEqual(first['task']['id'],second['task']['id'])
        self.assertEqual(len(self.store.tasks()),1)

    def test_changed_requirements_invalidate_pending_proposal(self):
        data,text=self.populate()
        self.agent.execute('propose_task',dict(candidate_id='V001',customer='',owner='',preferred_at='',note=''),data,text)
        token=data['state']['proposal']['token']
        data['messages'].append({'role':'user','content':'预算改成10万。'})
        self.agent.execute('update_requirements',{'changes':[change('budget_max',10,'10万')]},data,'预算改成10万。')
        self.agent.save(data)
        with self.assertRaises(ValueError):self.agent.confirm(data['id'],token,dict(customer='客户',owner='顾问'))

    def test_no_match_does_not_relax_budget(self):
        data=self.data('买车，北京，预算5万。')
        self.agent.execute('update_requirements',{'changes':[change('direction','买车','买车'),change('city','北京','北京'),change('budget_max',5,'5万')]},data,'买车，北京，预算5万。')
        result=self.agent.execute('search_vehicles',{},data,'买车，北京，预算5万。')
        self.assertEqual(result['matches'],[])
        self.assertEqual(data['state']['requirements']['budget_max'],5)

    def test_provider_failure_does_not_fallback_to_rules(self):
        def fail(*a):raise RuntimeError('模拟API不可用')
        self.agent.caller=fail
        result=self.agent.chat(self.session['id'],'帮我买车')
        self.assertFalse(result['turns'][-1]['ok'])
        self.assertIn('API不可用',result['turns'][-1]['reply'])
        self.assertIsNone(result['matching'])

    def test_public_session_never_returns_credentials_or_internal_api_history(self):
        with patch.dict(os.environ,{'AGENT_API_KEY':'fake-secret-for-test','AGENT_MODEL':'test-model','AGENT_API_BASE':'https://api.deepseek.com'}):
            result=self.agent.chat(self.session['id'],'我想买车')
        encoded=json.dumps(result)
        self.assertNotIn('fake-secret-for-test',encoded)
        self.assertNotIn('messages',result)
        restarted=CarAgent(Store(self.store.path),caller=lambda *a:answer())
        self.assertEqual(len(restarted.public(self.session['id'])['turns']),1)

    def test_gateway_reads_only_named_settings_fields(self):
        path=Path(self.tmp.name)/'settings.json'
        path.write_text(json.dumps({'env':{'ANTHROPIC_AUTH_TOKEN':'test-private-key','ANTHROPIC_BASE_URL':'https://api.deepseek.com/anthropic','ANTHROPIC_MODEL':'deepseek-v4-flash'},'permissions':{'defaultMode':'ignore-this'}}),encoding='utf-8')
        with patch.dict(os.environ,{'AGENT_API_KEY':'','AGENT_MODEL':'','AGENT_API_BASE':'','AGENT_SETTINGS_FILE':str(path)}):
            cfg=public_config()
        self.assertTrue(cfg['ready'])
        self.assertEqual(cfg['base'],'https://api.deepseek.com')
        self.assertNotIn('test-private-key',json.dumps(cfg))

    def test_legacy_adapter_groups_parallel_function_calls(self):
        body={'input':[{'role':'user','content':'test'},{'type':'function_call','call_id':'a','name':'x','arguments':'{}'},{'type':'function_call','call_id':'b','name':'y','arguments':'{}'},{'type':'function_call_output','call_id':'a','output':'{}'},{'type':'function_call_output','call_id':'b','output':'{}'}],'tools':[]}
        with patch('model_gateway.call_chat',return_value=answer('done')) as mocked:responses_adapter(body)
        messages=mocked.call_args.args[0]
        self.assertEqual(len(messages[1]['tool_calls']),2)
        self.assertEqual(messages[2]['role'],'tool')


if __name__=='__main__':unittest.main()
