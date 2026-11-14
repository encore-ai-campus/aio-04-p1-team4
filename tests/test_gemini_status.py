"""키 노출이나 채팅 생성 없이 연결 확인과 캐시를 검증합니다."""
import unittest
from unittest.mock import AsyncMock, patch
import httpx
from fastapi.testclient import TestClient
from app.main import app
from app.config import Settings
from app.clients.gemini import GeminiClient


class GeminiStatusClientTests(unittest.IsolatedAsyncioTestCase):
    async def test_auth_model_and_network_states(self):
        # 외부 응답은 모의 처리하며 상태와 안전한 안내만 반환해야 합니다.
        cases=[(200,{'data':[{'id':'test-model','active':True}]},'connected'),
               (200,{'data':[]},'disconnected'),(401,{},'disconnected'),(403,{},'disconnected'),
               (429,{},'unknown'),(500,{},'unknown'),(200,{'data':'wrong'},'unknown')]
        settings=Settings(map_api_key='fake-map',gemini_api_key='fake-private-key',gemini_model='test-model')
        for status,data,expected in cases:
            def handler(request):
                self.assertEqual(request.method,'GET')
                self.assertEqual(request.url.path,'/v1beta/openai/models')
                return httpx.Response(status,json=data)
            result=await GeminiClient(settings,transport=httpx.MockTransport(handler)).check_connection()
            self.assertEqual(result['status'],expected)
            self.assertNotIn('fake-private-key',str(result))
        def timeout(request):
            raise httpx.ReadTimeout('private',request=request)
        result=await GeminiClient(settings,transport=httpx.MockTransport(timeout)).check_connection()
        self.assertEqual(result['code'],'gemini_timeout')

    async def test_missing_key_skips_network(self):
        def handler(request):
            self.fail('키 누락 시 네트워크 호출 금지')
        result=await GeminiClient(Settings(map_api_key='fake'),transport=httpx.MockTransport(handler)).check_connection()
        self.assertEqual(result['code'],'gemini_config')


class GeminiStatusApiTests(unittest.TestCase):
    def test_cached_probe_keeps_timestamp_and_hides_settings(self):
        # 여러 화면 렌더와 빠른 수동 재확인이 외부 호출을 중복시키지 않아야 합니다.
        old=getattr(app.state,'gemini_status_cache',None)
        if hasattr(app.state,'gemini_status_cache'):del app.state.gemini_status_cache
        try:
            with TestClient(app) as client, patch('app.clients.gemini.GeminiClient.check_connection',AsyncMock(return_value={'status':'connected','code':'ok','message':'확인됨'})) as probe:
                first=client.get('/api/gemini/status')
                second=client.get('/api/gemini/status?refresh=true')
                self.assertEqual(first.status_code,200)
                self.assertEqual(first.json()['checked_at'],second.json()['checked_at'])
                self.assertTrue(second.json()['cached'])
                self.assertEqual(first.headers['cache-control'],'no-store')
                self.assertNotIn('gemini_api_key',first.text)
                probe.assert_awaited_once()
        finally:
            if old is not None:app.state.gemini_status_cache=old
            elif hasattr(app.state,'gemini_status_cache'):del app.state.gemini_status_cache
