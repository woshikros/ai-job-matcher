import unittest
from job_matcher import liepin_bridge_daemon as bridge

class BridgeRoutingTests(unittest.IsolatedAsyncioTestCase):
    async def test_missing_tab_can_fall_back_without_parallel_reads(self):
        visited = []
        async def dispatch(target, payload):
            visited.append(target)
            if target == 'empty': return {'ok':False, 'error':'Liepin chat tab required'}
            return {'ok':True, 'data':{'description':'full job ' * 20}}
        result = await bridge.choose_liepin_connection(['empty','ready','unused'], {'action':'extract_liepin_detail'}, dispatch)
        self.assertEqual(visited, ['empty','ready'])
        self.assertTrue(result['ok'])

    async def test_risk_and_timeout_never_visit_another_profile(self):
        for failure in [{'ok':True,'data':{'security_check':True}}, {'ok':True,'data':{'login_required':True}}, {'ok':False,'error':'Extension command failed: TimeoutError'}]:
            visited=[]
            async def dispatch(target,payload):
                visited.append(target)
                return failure
            self.assertEqual(await bridge.choose_liepin_connection(['one','two'],{'action':'extract_liepin_detail'},dispatch),failure)
            self.assertEqual(visited,['one'])

    async def test_success_never_dispatches_a_second_chat_read(self):
        visited=[]
        async def dispatch(target,payload):
            visited.append(target)
            return {'ok':True,'data':{'threads':[{'thread_id':'example'}]}}
        await bridge.choose_liepin_connection(['one','two'],{'action':'extract_liepin_chat_overview'},dispatch)
        self.assertEqual(visited,['one'])
