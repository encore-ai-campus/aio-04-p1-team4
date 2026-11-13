"""게임·채팅이 같은 검색을 사용하는지 외부 호출 없이 API 경계에서 검증합니다."""
import json
import unittest
from datetime import time
from tempfile import TemporaryDirectory
from unittest.mock import AsyncMock, patch
from fastapi.testclient import TestClient
from app.main import app
from app.clients.kakao import KakaoError
from app.clients.groq import GroqError
from app.chat_policy import QuestionInterpretation
from app.database import BusinessHours, Database, Menu, Restaurant

# 테스트용 공개 예시 좌표와 가짜 응답만 사용합니다.
LOCATION = {"lat": 37.48, "lng": 126.88, "name": "예시 위치", "source": "place"}
BODY = {"location": LOCATION, "radius_m": 500, "menu_id": "noodle"}
ITEM = {"id": "test-place", "name": "테스트 식당", "lat": 37.48, "lng": 126.88, "source": "kakao", "price": None, "rating": None, "image": None, "walk_minutes": None, "total_minutes": None, "menu_verified": False}


class RecommendationTests(unittest.TestCase):
    def setUp(self):
        # 서비스 경계에서 모의 처리하여 실제 키와 사용량을 소모하지 않습니다.
        self.groq_patcher = patch("app.clients.groq.GroqClient.interpret", new_callable=AsyncMock)
        # 5단계 추가 호출도 모의 처리하여 기존 회귀 테스트가 실제 Groq를 호출하지 않는다.
        self.narration_patcher = patch('app.clients.groq.GroqClient.compose_answer',new_callable=AsyncMock)
        self.narrate = self.narration_patcher.start()
        self.narrate.side_effect = GroqError('groq_response','테스트 서버 답변 대체')
        self.interpret = self.groq_patcher.start()
        self.interpret.return_value = QuestionInterpretation(intent="search_restaurants")
        # 추천 요청의 DB 저장도 프로젝트 실제 DB를 오염시키지 않고 검증합니다.
        self.original_database = app.state.database
        self.temp_directory = TemporaryDirectory()
        self.test_database = Database(
            f"sqlite:///{self.temp_directory.name.replace(chr(92), '/')}/recommendations.db"
        )
        self.test_database.init_schema()
        app.state.database = self.test_database
        self.client = TestClient(app)
        self.patcher = patch("app.clients.kakao.KakaoClient.search_restaurants", new_callable=AsyncMock)
        self.search = self.patcher.start()
        self.search.return_value = {"items": [ITEM], "has_more": True}
        # 조회 전에 테스트 DB에 확정 식당·상품·영업시간을 적재한다.
        from app.database import PlaceDetailStatus
        with self.test_database.session_factory.begin() as session:
            row = Restaurant(id="test-place", name="테스트 식당", latitude=37.48, longitude=126.88,
                cuisine="중식", category_name="음식점 > 중식", address="서울 테스트로 1",
                detail_status=PlaceDetailStatus(menu_status="success", hours_status="success"))
            row.menus.append(Menu(name="짜장면", normalized_name="짜장면", menu_catalog_id="noodle",
                price=8000, price_status="known"))
            row.business_hours = [BusinessHours(day_of_week=d, holiday=False, start_time=time(0),
                end_time=time(0), ends_next_day=True) for d in range(7)]
            session.add(row)
        self.collection_patcher = patch("app.detail_collection.collect_restaurant_details_batch", new_callable=AsyncMock)
        self.collect_details = self.collection_patcher.start()

    def tearDown(self):
        self.narration_patcher.stop()
        self.groq_patcher.stop()
        self.patcher.stop()
        self.collection_patcher.stop()
        self.client.close()
        app.state.database = self.original_database
        self.test_database.dispose()
        self.temp_directory.cleanup()

    def test_game_reads_selected_menu_without_external_search(self):
        response = self.client.post("/api/recommendations", json=BODY)
        self.assertEqual(response.status_code, 200)
        result = response.json()
        self.search.assert_not_awaited()
        self.assertEqual(result["restaurants"][0]["id"], "test-place")
        self.assertEqual(result["restaurants"][0]["price"], 8000)
        self.assertTrue(result["restaurants"][0]["menu_verified"])
        self.assertFalse(result["constraints_verified"])
        # 5단계부터 고정 배열이 아니라 SQLAlchemy 메뉴 카탈로그를 사용한다.
        self.assertFalse(result["menu_catalog_demo"])
        self.assertFalse(result["has_more"])

    def test_game_candidates_only_returns_backend_pool_without_external_search(self):
        response = self.client.post("/api/menus/candidates", json={
            "location": LOCATION, "radius_m": 500,
            "conditions": {"budget": 9000, "minutes": 30, "cuisine": "중식"},
        })
        self.assertEqual(response.status_code, 200)
        self.assertEqual([m["id"] for m in response.json()["menus"]], ["noodle"])
        self.assertNotIn("menu", response.json())
        self.search.assert_not_awaited()
        self.collect_details.assert_not_awaited()
        self.interpret.assert_not_awaited()

    def test_game_draw_respects_conditions_without_external_search(self):
        # 메뉴 추첨만으로 카카오 검색·Playwright·Groq가 실행되면 안 된다.
        response = self.client.post(
            "/api/menus/draw",
            json={"location": LOCATION, "radius_m": 500,
                  "conditions": {"budget": 9000, "cuisine": "중식"}},
        )
        self.assertEqual(response.status_code, 200)
        result = response.json()
        self.assertEqual(result["menu"]["id"], "noodle")
        self.assertEqual(result["menu"]["cuisine"], "중식")
        self.assertEqual(result["restaurants"], [])
        self.search.assert_not_awaited()
        self.collect_details.assert_not_awaited()
        self.interpret.assert_not_awaited()

    def test_game_draw_returns_no_menu_when_conditions_have_no_candidate(self):
        response = self.client.post(
            "/api/menus/draw",
            json={"location": LOCATION, "conditions": {"budget": 1000}},
        )
        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.json()["menu"])
        self.search.assert_not_awaited()
        self.collect_details.assert_not_awaited()

    def test_stored_result_is_read_without_collection_or_insert(self):
        self.search.return_value = {
            "items": [{
                **ITEM,
                "address": "서울 테스트로 1",
                "category": "음식점 > 중식",
                "category_group_code": "FD6",
                "place_url": "https://place.map.kakao.com/test-place",
            }],
            "has_more": False,
        }
        response = self.client.post("/api/recommendations", json=BODY)
        self.assertEqual(response.status_code, 200)
        self.assertNotIn("storage", response.json())
        self.search.assert_not_awaited()
        self.collect_details.assert_not_awaited()
        with self.test_database.session_factory() as session:
            stored = session.get(Restaurant, "test-place")
            self.assertIsNotNone(stored)
            self.assertEqual((stored.name, stored.cuisine), ("테스트 식당", "중식"))

    def test_chat_reuses_same_menu_search(self):
        response = self.client.post("/api/chat", json={**BODY, "message": "가까운 식당 보여줘"})
        self.assertEqual(response.status_code, 200)
        self.search.assert_not_awaited()
        self.assertEqual(response.json()["result"]["restaurants"][0]["id"], "test-place")

    def test_empty_result_does_not_retry_or_expand_radius(self):
        with self.test_database.session_factory.begin() as session:
            session.get(Restaurant, "test-place").operating_status = "closed"
        result = self.client.post("/api/recommendations", json=BODY).json()
        self.assertEqual(result["restaurants"], [])
        self.assertIn("DB 메뉴가 없습니다", result["message"])
        self.assertEqual(result["radius_m"], 500)
        self.search.assert_not_awaited()

    def test_no_catalog_candidate_never_calls_kakao(self):
        # 예시 카탈로그 후보가 없거나 유효하지 않은 ID면 외부 검색하지 않습니다.
        for override in ({"conditions": {"budget": 1000}}, {"menu_id": "missing"}):
            result = self.client.post("/api/recommendations", json={**BODY, **override}).json()
            self.assertIsNone(result["menu"])
            self.assertEqual(result["restaurants"], [])
        self.search.assert_not_awaited()

    def test_kakao_outage_does_not_affect_db_recommendations(self):
        self.search.side_effect = KakaoError("kakao_permission", "권한 확인 필요")
        for endpoint, extra in (("recommendations", {}), ("chat", {"message": "식당 보여줘"})):
            response = self.client.post(f"/api/{endpoint}", json={**BODY, **extra})
            self.assertEqual(response.status_code, 200)
            result = response.json().get("result") or response.json()
            self.assertEqual(result["restaurants"][0]["id"], "test-place")
            self.search.assert_not_awaited()

    def test_explanation_and_condition_proposal_do_not_search(self):
        for message, parsed in [("메뉴 설명해줘", QuestionInterpretation.model_validate({"intent":"explain_menu","menu_id":"noodle"}, context={"menu_ids":{"noodle"}})),
                                ("예산을 바꿔줘", QuestionInterpretation(intent="change_conditions",condition_patch={"budget":9000}))]:
            self.interpret.return_value=parsed
            response = self.client.post("/api/chat", json={**BODY, "message": message})
            self.assertEqual(response.status_code, 200)
            if parsed.intent == 'change_conditions':
                self.assertEqual(response.json()['applied_patch'],{'budget':9000})
                self.assertIsNotNone(response.json()['result'])
            else:
                self.assertIsNone(response.json()["result"])
        self.search.assert_not_awaited()

    def test_conflicting_menu_does_not_search(self):
        # 메뉴가 실제 ID여도 현재 음식 조건을 통과하지 못하면 검색하지 않습니다.
        self.interpret.return_value=QuestionInterpretation.model_validate({"intent":"search_restaurants","menu_id":"noodle"},context={"menu_ids":{"noodle"}})
        response=self.client.post("/api/chat",json={**BODY,"conditions":{"cuisine":"한식"},"message":"짜장면 식당"})
        self.assertEqual(response.status_code,200)
        self.assertIsNone(response.json()["result"]["menu"])
        self.search.assert_not_awaited()

    def test_radius_patch_is_applied_immediately(self):
        self.interpret.return_value=QuestionInterpretation(intent="change_conditions",condition_patch={"radius_m":100,"budget":9000})
        response=self.client.post("/api/chat",json={**BODY,"message":"반경과 예산 변경"})
        # 4단계: 제안 버튼을 기다리지 않고 확정값과 새 메뉴를 반환한다.
        self.assertIsNone(response.json()["suggested_patch"])
        self.assertEqual(response.json()["applied_patch"],{"radius_m":100,"budget":9000})
        self.assertEqual(response.json()["radius_m"],100)
        self.assertIsNotNone(response.json()["result"]["menu"])
        self.search.assert_not_awaited()

    def test_clarification_never_displays_generated_store_facts(self):
        # 확인 의도에 가짜 가격이 섞여도 모델 문장 대신 서버 안내만 표시합니다.
        self.interpret.return_value=QuestionInterpretation(intent="clarify",clarification="가짜식당은 무조건 100원입니다",clarification_kind="unsupported")
        response=self.client.post("/api/chat",json={**BODY,"message":"알레르기 없는 식당"})
        self.assertNotIn("100원",response.json()["text"])
        self.assertIn("검증할 데이터가 없습니다",response.json()["text"])
        self.search.assert_not_awaited()

    def test_recommendation_has_conditions_and_displayed_product(self):
        self.interpret.return_value=QuestionInterpretation(intent="search_restaurants")
        text=self.client.post("/api/chat",json={**BODY,"message":"식당"}).json()["text"]
        self.assertIn("추천 메뉴:",text)
        self.assertIn("적용 조건:",text)
        self.assertIn("반경 500m",text)
        # 1단계: 확인 필요 식당도 같은 목록에 표시하고 실제 상품을 안내한다.
        self.assertIn("1. 테스트 식당 · 짜장면 · 8,000원",text)
        self.assertNotIn("인분 미확인",text)
        self.assertNotIn("채식",text)
        self.assertNotIn("맵기",text)

    def test_chat_missing_price_and_hours_have_exact_notices(self):
        # 서버 답변까지 확인하며 외부 Groq와 카카오는 기존 테스트 모의 객체를 사용한다.
        with self.test_database.session_factory.begin() as session:
            row=session.get(Restaurant,'test-place')
            row.menus[0].price=None
            row.menus[0].price_status='missing'
            row.business_hours=[]
        response=self.client.post('/api/chat',json={**BODY,'message':'짜장면 식당 알려줘'})
        self.assertEqual(response.status_code,200)
        data=response.json()
        self.assertIn('해당 식당의 메뉴 가격 확인 불가',data['text'])
        self.assertIn('영업시간 미기재로 인해 알 수 없습니다',data['text'])
        self.assertIsNone(data['result']['restaurants'][0]['price'])
        self.assertEqual(data['result']['restaurants'][0]['open_status'],'unknown')

    def test_clarify_scope_and_groq_errors_never_search(self):
        for parsed in (QuestionInterpretation(intent="clarify",clarification="어떤 메뉴인가요?"),QuestionInterpretation(intent="out_of_scope")):
            self.interpret.return_value=parsed
            self.assertEqual(self.client.post("/api/chat",json={**BODY,"message":"질문"}).status_code,200)
        self.interpret.side_effect=GroqError("groq_rate_limit","잠시 후 재시도",503)
        response=self.client.post("/api/chat",json={**BODY,"message":"추천"})
        self.assertEqual(response.status_code,503)
        self.assertEqual(response.headers["X-Error-Code"],"groq_rate_limit")
        self.search.assert_not_awaited()

    def test_clarification_is_saved_as_pending_and_normal_request_clears_it(self):
        # 값 없는 반경 변경은 세션의 대화 pending으로 저장하며 수집 pending과 섞지 않는다.
        self.interpret.return_value = QuestionInterpretation(
            intent="clarify", clarification_kind="radius"
        )
        response = self.client.post(
            "/api/chat", json={**BODY, "message": "반경을 줄여줘"}
        )
        self.assertEqual(response.status_code, 200)
        saved = self.client.get("/api/chat/session").json()
        self.assertEqual(saved["pending_action"]["kind"], "change_radius")
        self.assertEqual(saved["pending_action"]["current_value"], 500)

        # 다음 정상 추천 요청이 성공하면 이전 확인 대기를 해제한다.
        self.interpret.return_value = QuestionInterpretation(intent="recommend_menu")
        response = self.client.post(
            "/api/chat", json={**BODY, "message": "그냥 추천해줘"}
        )
        self.assertEqual(response.status_code, 200)
        self.assertIsNone(self.client.get("/api/chat/session").json()["pending_action"])

    def test_reroll_does_not_select_current_menu(self):
        self.interpret.return_value = QuestionInterpretation(intent="reroll_menu")
        response = self.client.post(
            "/api/chat", json={**BODY, "message": "다른 메뉴 추천해줘"}
        )
        self.assertEqual(response.status_code, 200)
        selected = response.json()["result"]["menu"]
        # 唯一 DB 후보를 제외하면 seed로 보충하지 않는다.
        self.assertIsNone(selected)
        # 메뉴만 다시 고르는 질문은 상세페이지 수집이나 카카오 검색을 시작하지 않는다.
        self.search.assert_not_awaited()

    def test_menu_recommendation_uses_database_catalog_without_search(self):
        self.interpret.return_value = QuestionInterpretation(intent="recommend_menu")
        response = self.client.post(
            "/api/chat", json={**BODY, "menu_id": None, "message": "메뉴 추천해줘"}
        )
        self.assertEqual(response.status_code, 200)
        result = response.json()["result"]
        self.assertIsNotNone(result["menu"])
        self.assertFalse(result["menu_catalog_demo"])
        self.assertIn(result["menu"]["source"], {"database", "catalog"})
        self.search.assert_not_awaited()

    def _add_second_eligible_menu(self):
        # 2단계 검증 전용: seed 대표 메뉴에 실제 판매 상품을 연결한다.
        # 운영 DB가 아닌 setUp의 임시 SQLite에만 저장한다.
        with self.test_database.session_factory.begin() as session:
            row=session.get(Restaurant,'test-place')
            row.menus.append(Menu(name='짬뽕',normalized_name='짬뽕',menu_catalog_id='spicynoodle',
                                  price=9000,price_status='known'))

    def test_stage2_menu_only_has_conditions_and_invitation_without_listing(self):
        self.interpret.return_value=QuestionInterpretation(intent='recommend_menu')
        # 외부 호출 여부뿐 아니라 식당 목록 생성 함수 자체가 실행되지 않는지 확인한다.
        with patch('app.db_recommendations.restaurant_payloads',side_effect=AssertionError('메뉴만 선정해야 합니다')):
            response=self.client.post('/api/chat',json={**BODY,'menu_id':None,'message':'메뉴 추천해줘'})
        self.assertEqual(response.status_code,200)
        data=response.json()
        self.assertIn('추천 메뉴: 짜장면',data['text'])
        self.assertIn('반경 500m',data['text'])
        self.assertIn('예산 10,000원 이하',data['text'])
        self.assertIn('식당까지 추천해드릴까요?',data['text'])
        self.assertEqual(data['result']['restaurants'],[])
        self.assertEqual(data['result']['message'],data['text'])
        self.search.assert_not_awaited()
        self.collect_details.assert_not_awaited()

    def test_stage2_reroll_only_excludes_current_menu_not_history(self):
        self._add_second_eligible_menu()
        # A를 고른 뒤 B, 다시 A가 나와야 한다. 세션의 과거 A 기록은 제외 사유가 아니다.
        self.client.post('/api/chat',json={**BODY,'message':'짜장면 식당 알려줘'})
        self.interpret.return_value=QuestionInterpretation(intent='reroll_menu')
        for expected in ['spicynoodle','noodle']:
            data=self.client.post('/api/chat',json={**BODY,'menu_id':None,'message':'다른 메뉴 추천해줘'}).json()
            self.assertEqual(data['result']['menu']['id'],expected)
            self.assertEqual(data['result']['restaurants'],[])
            self.assertIn('식당까지 추천해드릴까요?',data['text'])
            self.assertIn('적용 조건:',data['text'])
        saved=self.client.get('/api/chat/session').json()
        self.assertEqual(saved['selected_menu']['id'],'noodle')
        self.search.assert_not_awaited()

    def test_stage2_reroll_no_alternative_is_explicit(self):
        self.interpret.return_value=QuestionInterpretation(intent='reroll_menu')
        data=self.client.post('/api/chat',json={**BODY,'message':'다른 메뉴 추천해줘'}).json()
        self.assertIsNone(data['result']['menu'])
        self.assertIn('조건에 맞는 다른 메뉴가 없습니다',data['text'])
        self.assertNotIn('식당까지 추천해드릴까요?',data['text'])

    def test_stage2_reroll_respects_budget_even_when_other_catalog_exists(self):
        self._add_second_eligible_menu()
        self.interpret.return_value=QuestionInterpretation(intent='reroll_menu')
        data=self.client.post('/api/chat',json={**BODY,'conditions':{'budget':8000,'cuisine':'중식'},
                                               'message':'다른 메뉴 추천해줘'}).json()
        self.assertIsNone(data['result']['menu'])  # 짬뽕은 실제 상품가 9000원이므로 제외된다.

    def test_stage2_current_menu_search_uses_session(self):
        self.interpret.return_value=QuestionInterpretation(intent='recommend_menu')
        self.client.post('/api/chat',json={**BODY,'menu_id':None,'message':'메뉴 추천해줘'})
        self.interpret.return_value=QuestionInterpretation(intent='search_restaurants')
        data=self.client.post('/api/chat',json={**BODY,'menu_id':None,'message':'이 메뉴 파는 식당 알려줘'}).json()
        self.assertEqual(data['result']['menu']['id'],'noodle')
        self.assertEqual(data['result']['restaurants'][0]['menu_name'],'짜장면')

    def test_stage2_explicit_menu_overrides_selected_menu(self):
        self._add_second_eligible_menu()
        self.interpret.return_value=QuestionInterpretation.model_validate(
            {'intent':'search_restaurants','menu_id':'spicynoodle'},
            context={'menu_ids':{'noodle','spicynoodle'}})
        data=self.client.post('/api/chat',json={**BODY,'message':'짬뽕 식당 알려줘'}).json()
        self.assertEqual(data['result']['menu']['id'],'spicynoodle')
        self.assertEqual(data['result']['restaurants'][0]['menu_name'],'짬뽕')
        self.assertEqual(data['result']['restaurants'][0]['price'],9000)

    def test_stage2_no_selected_menu_does_not_randomly_search(self):
        data=self.client.post('/api/chat',json={**BODY,'menu_id':None,'message':'이 메뉴 파는 식당 알려줘'}).json()
        self.assertIsNone(data['result'])
        self.assertIn('먼저 메뉴를 정해주세요',data['text'])
        self.search.assert_not_awaited()

    def test_stage2_no_restaurant_has_exact_message_without_random_fallback(self):
        with self.test_database.session_factory.begin() as session:
            session.get(Restaurant,'test-place').operating_status='closed'
        data=self.client.post('/api/chat',json={**BODY,'message':'이 메뉴 식당 알려줘'}).json()
        self.assertEqual(data['result']['restaurants'],[])
        self.assertIsNone(data['result']['menu'])
        self.assertIn('선택 메뉴: 짜장면',data['text'])
        self.assertIn('현재 이 메뉴에 맞는 영업 중인 식당이 없어요. 다른 메뉴를 추천해드릴까요?',data['text'])
        self.assertEqual(data['result']['message'],data['text'])

    def test_stage2_menu_only_stream_never_emits_searching(self):
        self.interpret.return_value=QuestionInterpretation(intent='recommend_menu')
        with self.client.stream('POST','/api/chat/stream',json={**BODY,'menu_id':None,'message':'메뉴 추천해줘'}) as response:
            events=[json.loads(line) for line in response.iter_lines() if line]
        self.assertEqual(events[-1]['event'],'completed')
        self.assertNotIn('searching',[event['event'] for event in events])
        self.assertEqual(events[-1]['data']['result']['restaurants'],[])
        self.assertIn('식당까지 추천해드릴까요?',events[-1]['data']['text'])

    def test_restaurant_price_followup_reads_saved_database(self):
        # 첫 질문으로 추천 식당 ID와 상세페이지에서 확인한 가격을 세션에 저장한다.
        first = self.client.post(
            "/api/chat", json={**BODY, "message": "짜장면 식당 보여줘"}
        )
        self.assertEqual(first.status_code, 200)
        self.interpret.return_value = QuestionInterpretation.model_validate(
            {
                "intent": "ask_restaurant_detail",
                "restaurant_id": "test-place",
                "requested_detail": "price",
            },
            context={"menu_ids": {"noodle"}, "restaurant_ids": {"test-place"}},
        )

        response = self.client.post(
            "/api/chat", json={**BODY, "message": "그 식당 가격은?"}
        )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertIn("8,000원", payload["text"])
        self.assertEqual(payload["restaurant_detail"]["price"], 8000)
        # 후속 질문은 저장 DB만 읽으므로 카카오 검색은 최초 한 번뿐이다.
        self.search.assert_not_awaited()

    def test_restaurant_hours_followup_calculates_current_korea_time(self):
        self.client.post(
            "/api/chat", json={**BODY, "message": "짜장면 식당 보여줘"}
        )
        self.interpret.return_value = QuestionInterpretation.model_validate(
            {
                "intent": "ask_restaurant_detail",
                "restaurant_id": "test-place",
                "requested_detail": "hours",
            },
            context={"menu_ids": {"noodle"}, "restaurant_ids": {"test-place"}},
        )
        response = self.client.post(
            "/api/chat", json={**BODY, "message": "지금 영업 중이야?"}
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn("현재 한국 시간", response.json()["text"])
        self.assertEqual(response.json()["restaurant_detail"]["open_status"], "open")

    def test_restaurant_price_keeps_previously_displayed_product(self):
        self.client.post(
            "/api/chat", json={**BODY, "message": "짜장면 식당 보여줘"}
        )
        # 3단계: DB 가격이 바뀌어도 앞서 표시한 상품의 8000원으로 답한다.
        with self.test_database.session_factory.begin() as session:
            restaurant = session.get(Restaurant, "test-place")
            restaurant.menus[0].price = None
            restaurant.menus[0].price_status = "missing"
        self.interpret.return_value = QuestionInterpretation.model_validate(
            {
                "intent": "ask_restaurant_detail",
                "restaurant_id": "test-place",
                "requested_detail": "price",
            },
            context={"menu_ids": {"noodle"}, "restaurant_ids": {"test-place"}},
        )
        response = self.client.post(
            "/api/chat", json={**BODY, "message": "가격 알려줘"}
        )
        self.assertIn("8,000원", response.json()["text"])
        self.assertIn("앞서 표시한 가격 기준", response.json()["text"])
        self.assertEqual(response.json()["restaurant_detail"]["price"], 8000)

    def test_restaurant_address_menu_and_reason_followups_use_database(self):
        self.search.return_value = {
            "items": [{**ITEM, "address": "서울 테스트로 1"}],
            "has_more": False,
        }
        self.client.post(
            "/api/chat", json={**BODY, "message": "짜장면 식당 보여줘"}
        )
        checks = {
            "address": "서울 테스트로 1",
            "menu": "짜장면",
            "reason": "현재 위치를 기반으로 추천한 메뉴를 판매하는 식당을 추천드렸습니다.",
        }
        for requested_detail, expected in checks.items():
            self.interpret.return_value = QuestionInterpretation.model_validate(
                {
                    "intent": "ask_restaurant_detail",
                    "restaurant_id": "test-place",
                    "requested_detail": requested_detail,
                },
                context={
                    "menu_ids": {"noodle"},
                    "restaurant_ids": {"test-place"},
                },
            )
            response = self.client.post(
                "/api/chat", json={**BODY, "message": f"{requested_detail} 알려줘"}
            )
            self.assertEqual(response.status_code, 200)
            self.assertIn(expected, response.json()["text"])
        self.search.assert_not_awaited()

    def test_chat_stream_reports_progress_and_completed_result(self):
        # 실제 외부 호출 없이도 브라우저가 받는 JSON Lines 이벤트 순서를 검증한다.
        with self.client.stream(
            "POST",
            "/api/chat/stream",
            json={**BODY, "message": "짜장면 식당 보여줘"},
        ) as response:
            self.assertEqual(response.status_code, 200)
            self.assertIn("application/x-ndjson", response.headers["content-type"])
            events = [json.loads(line) for line in response.iter_lines() if line]

        names = [event["event"] for event in events]
        self.assertEqual(names[0], "started")
        self.assertIn("interpreting", names)
        self.assertIn("checking_database", names)
        self.assertIn("searching", names)
        self.assertNotIn("collecting", names)
        self.assertIn("filtering", names)
        self.assertEqual(names[-1], "completed")
        self.assertEqual(events[-1]["data"]["result"]["restaurants"][0]["id"], "test-place")

    def test_chat_stream_rejects_duplicate_session_request(self):
        # 스트림이 처리 중인 것으로 등록된 같은 쿠키 세션은 외부 호출 전에 거부한다.
        self.client.get("/api/chat/session")
        session_id = self.client.cookies.get("lunchrun_session")
        app.state.active_chat_streams.add(session_id)
        try:
            response = self.client.post(
                "/api/chat/stream",
                json={**BODY, "message": "식당 다시 보여줘"},
            )
            self.assertEqual(response.status_code, 409)
            self.assertIn("이미 처리 중", response.json()["detail"])
            self.search.assert_not_awaited()
        finally:
            app.state.active_chat_streams.discard(session_id)

    def test_chat_stream_returns_safe_failure_event(self):
        self.interpret.side_effect = GroqError(
            "groq_rate_limit", "잠시 후 다시 시도해 주세요.", 503
        )
        with self.client.stream(
            "POST", "/api/chat/stream", json={**BODY, "message": "추천해줘"}
        ) as response:
            events = [json.loads(line) for line in response.iter_lines() if line]
        self.assertEqual(response.status_code, 200)
        self.assertEqual(events[-1]["event"], "failed")
        self.assertEqual(events[-1]["code"], "groq_rate_limit")
        self.search.assert_not_awaited()

    def test_changed_conditions_do_not_reuse_previous_restaurant_context(self):
        self.client.post('/api/chat', json={**BODY, 'message':'식당 조회'})
        self.interpret.return_value = QuestionInterpretation.model_validate(
            {'intent':'ask_restaurant_detail', 'restaurant_id':'test-place', 'requested_detail':'price'},
            context={'menu_ids':{'noodle'}, 'restaurant_ids':{'test-place'}})
        response = self.client.post('/api/chat', json={**BODY, 'menu_id':None,
            'conditions':{'budget':1000, 'cuisine':'한식'}, 'message':'그 식당 가격'})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.interpret.call_args.kwargs['restaurants'], [])
        self.assertIn('다시 조회', response.json()['text'])
        self.assertNotIn('restaurant_detail', response.json())
        saved = self.client.get('/api/chat/session').json()
        self.assertEqual(saved['restaurant_ids'], [])
        self.assertIsNone(saved['selected_menu'])

    def test_empty_reroll_clears_selected_menu_in_server_session(self):
        self.client.post('/api/chat', json={**BODY, 'message':'식당 조회'})
        self.interpret.return_value = QuestionInterpretation(intent='reroll_menu')
        response = self.client.post('/api/chat', json={**BODY, 'message':'다른 메뉴'})
        self.assertIsNone(response.json()['result']['menu'])
        self.assertIsNone(self.client.get('/api/chat/session').json()['selected_menu'])
