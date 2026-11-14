"""Gemini 질문 해석과 5단계 답변 구성을 분리한 클라이언트.

Google AI Studio의 OpenAI 호환 엔드포인트를 사용해 기존 OpenAI 형식의
메시지·JSON 응답 계약을 그대로 유지한다.
"""
import asyncio
from dataclasses import dataclass

import httpx
from pydantic import ValidationError

from ..chat_policy import QuestionInterpretation, build_interpretation_messages, parse_interpretation
from ..config import Settings
from ..schemas import Conditions


@dataclass
class GeminiError(Exception):
    # 외부 응답 원문·질문·인증 헤더는 오류 객체에 저장하지 않습니다.
    code: str
    message: str
    status_code: int = 502

    def __str__(self) -> str:
        return self.message


class GeminiClient:
    URL = "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions"
    MODELS_URL = "https://generativelanguage.googleapis.com/v1beta/openai/models"

    async def check_connection(self) -> dict:
        # 생성 토큰을 쓰지 않고 모델 목록 조회로 인증·설정 모델의 사용 가능 여부를 확인합니다.
        key = self._settings.gemini_api_key.get_secret_value().strip()
        if not key:
            return dict(status="disconnected", code="gemini_config", message="Gemini API 키가 설정되지 않았습니다.")
        try:
            async with asyncio.timeout(self._settings.gemini_timeout_seconds):
                async with httpx.AsyncClient(timeout=self._settings.gemini_timeout_seconds,
                                             follow_redirects=False, transport=self._transport) as client:
                    response = await client.get(self.MODELS_URL,
                                                headers={"Authorization": f"Bearer {key}"})
        except (TimeoutError, httpx.TimeoutException):
            return dict(status="unknown", code="gemini_timeout", message="연결 확인 시간이 초과되었습니다.")
        except httpx.RequestError:
            return dict(status="unknown", code="gemini_connection", message="Gemini 네트워크 연결을 확인하지 못했습니다.")
        # 오류 원문이나 모델 전체 목록은 브라우저로 보내지 않습니다.
        if response.status_code in (401, 403):
            return dict(status="disconnected", code="gemini_auth" if response.status_code == 401 else "gemini_permission",
                        message="Gemini 인증 키 또는 사용 권한을 확인해 주세요.")
        if response.status_code != 200:
            return dict(status="unknown", code="gemini_rate_limit" if response.status_code == 429 else "gemini_upstream",
                        message="사용량 제한 또는 서비스 오류로 연결 상태를 확인하지 못했습니다.")
        try:
            data = response.json()["data"]
            if not isinstance(data, list) or any(not isinstance(m, dict) for m in data):
                raise ValueError
            # OpenAI 호환 목록은 "models/gemini-..." 형태의 ID를 반환할 수 있다.
            model_ids = {str(m.get("id", "")).removeprefix("models/") for m in data}
            available = self._settings.gemini_model in model_ids
        except (ValueError, TypeError, KeyError):
            return dict(status="unknown", code="gemini_response", message="연결 확인 응답 형식이 올바르지 않습니다.")
        if not available:
            return dict(status="disconnected", code="gemini_model", message="설정한 Gemini 모델을 사용할 수 없습니다.")
        return dict(status="connected", code="ok", message="인증과 설정 모델을 확인했습니다. 채팅 성공을 보장하는 검사는 아닙니다.")

    def __init__(self, settings: Settings, *, transport: httpx.AsyncBaseTransport | None = None):
        # 테스트에서는 모의 HTTP 전송을 주입하며 실제 키를 사용하지 않습니다.
        self._settings = settings
        self._transport = transport

    async def interpret(
        self,
        message: str,
        conditions: Conditions,
        radius_m: int,
        menus: list[dict],
        selected_menu_id: str | None = None,
        *,
        conversation_history: list[dict] | None = None,
        restaurants: list[dict] | None = None,
        candidate_restaurants: list[dict] | None = None,
        pending_action: dict | None = None,
    ) -> QuestionInterpretation:
        """최근 세션 문맥을 포함해 안전한 실행 계획 하나를 반환한다."""

        key = self._settings.gemini_api_key.get_secret_value().strip()
        if not key:
            raise GeminiError("gemini_config", "Gemini API 키가 설정되지 않았습니다. 서버 설정을 확인해 주세요.", 503)
        # 호출자가 잘못된 데이터를 주더라도 외부 요청 이전에 검사합니다.
        if not isinstance(message, str) or not 1 <= len(message.strip()) <= 500:
            raise ValueError("질문은 1~500자로 입력해 주세요.")
        if type(radius_m) is not int or not 50 <= radius_m <= 500:
            raise ValueError("반경은 50~500m 정수여야 합니다.")
        menu_ids = {m["id"] for m in menus}
        restaurant_ids = {
            item["id"]
            for item in [*(restaurants or []), *(candidate_restaurants or [])]
            if isinstance(item, dict) and isinstance(item.get("id"), str)
        }
        if selected_menu_id is not None and selected_menu_id not in menu_ids:
            raise ValueError("선택 메뉴가 메뉴 목록에 없습니다.")
        try:
            messages = build_interpretation_messages(
                message.strip(),
                conditions.model_dump(),
                radius_m,
                menus,
                selected_menu_id,
                conversation_history=conversation_history,
                restaurants=restaurants,
                candidate_restaurants=candidate_restaurants,
                pending_action=pending_action,
            )
        except (OSError, ValueError, KeyError, TypeError):
            raise GeminiError("gemini_policy", "질문 해석 지침 파일을 확인해 주세요.", 503) from None
        body = {"model": self._settings.gemini_model, "messages": messages,
                "max_completion_tokens": self._settings.gemini_max_completion_tokens,
                "response_format": {"type": "json_object"}, "temperature": 0}
        # 인증·한도·요청 오류는 형식 재요청 대상이 아니므로 즉시 안전한 오류로 반환한다.
        errors = {
            401: ("gemini_auth", "Gemini API 키 인증에 실패했습니다. 서버 설정을 확인해 주세요.", 503),
            403: ("gemini_permission", "해당 Gemini 모델의 사용 권한을 확인해 주세요.", 503),
            429: ("gemini_rate_limit", "AI 사용 한도에 도달했습니다. 잠시 후 다시 시도해 주세요.", 503),
            400: ("gemini_request", "Gemini 모델과 요청 옵션을 확인해 주세요.", 502),
            404: ("gemini_model", "Gemini 모델 이름과 사용 가능 여부를 확인해 주세요.", 503),
        }
        try:
            # 두 요청을 합친 전체 제한시간 안에서 형식 오류만 한 번 다시 요청한다.
            async with asyncio.timeout(self._settings.gemini_timeout_seconds):
                async with httpx.AsyncClient(
                    timeout=self._settings.gemini_timeout_seconds,
                    follow_redirects=False,
                    transport=self._transport,
                ) as client:
                    for attempt in range(2):
                        response = await client.post(
                            self.URL,
                            json=body,
                            headers={"Authorization": f"Bearer {key}"},
                        )
                        if response.status_code in errors:
                            raise GeminiError(*errors[response.status_code])
                        if response.status_code != 200:
                            raise GeminiError(
                                "gemini_upstream", "AI 서비스가 정상 응답하지 않았습니다."
                            )
                        try:
                            data = response.json()
                            choice = data["choices"][0]
                            if choice.get("finish_reason") == "length":
                                raise GeminiError(
                                    "gemini_truncated",
                                    "AI 출력 한도에 도달해 응답이 잘렸습니다. 서버의 출력 토큰 설정을 확인해 주세요.",
                                )
                            if choice.get("finish_reason") != "stop":
                                raise ValueError("Incomplete response")
                            result = choice["message"]
                            if result.get("tool_calls") or result.get("refusal"):
                                raise ValueError("Unsupported response")
                            return parse_interpretation(
                                result["content"], menu_ids, restaurant_ids
                            )
                        except GeminiError:
                            raise
                        except (
                            ValidationError,
                            ValueError,
                            KeyError,
                            IndexError,
                            TypeError,
                            AttributeError,
                        ):
                            if attempt == 0:
                                # 잘못된 원문은 다시 넣지 않고 같은 질문에 스키마 준수만 재강조한다.
                                body = {
                                    **body,
                                    "messages": [
                                        *messages,
                                        {
                                            "role": "user",
                                            "content": "이전 출력은 JSON Schema 검증에 실패했습니다. 같은 입력을 Schema에 맞는 JSON 객체 하나로 다시 해석하세요.",
                                        },
                                    ],
                                }
                                continue
                            # 두 번째 형식 오류도 검색으로 실행하지 않고 안전한 확인 상태로 낮춘다.
                            return QuestionInterpretation(
                                intent="clarify", clarification_kind="ambiguous"
                            )
        except GeminiError:
            raise
        except (TimeoutError, httpx.TimeoutException):
            raise GeminiError(
                "gemini_timeout", "AI 응답 시간이 초과되었습니다. 다시 시도해 주세요.", 504
            ) from None
        except httpx.RequestError:
            raise GeminiError(
                "gemini_connection", "AI 서비스에 연결할 수 없습니다. 잠시 후 다시 시도해 주세요.", 503
            ) from None

    async def compose_answer(self, context: dict) -> dict:
        """5단계: 결과 설명을 한 번만 요청한다. 재시도 대신 상위 계층이 서버 답변을 쓴다."""
        from ..answer_narration import build_narration_messages
        key=self._settings.gemini_api_key.get_secret_value().strip()
        if not key: raise GeminiError('gemini_config','답변 생성 키가 설정되지 않았습니다.',503)
        body={'model':self._settings.gemini_model,'messages':build_narration_messages(context),
              'temperature':0,'max_completion_tokens':min(512,self._settings.gemini_max_completion_tokens),
              'response_format':{'type':'json_object'}}
        try:
            async with asyncio.timeout(self._settings.gemini_narration_timeout_seconds):
                async with httpx.AsyncClient(timeout=self._settings.gemini_narration_timeout_seconds,
                                             follow_redirects=False,transport=self._transport) as client:
                    response=await client.post(self.URL,json=body,headers={'Authorization':f'Bearer {key}'})
            if response.status_code!=200:
                code={401:'gemini_auth',403:'gemini_permission',429:'gemini_rate_limit',400:'gemini_request',404:'gemini_model'}.get(response.status_code,'gemini_upstream')
                raise GeminiError(code,'답변 생성 요청을 완료하지 못했습니다.')
            data=response.json()
            choice=data['choices'][0]
            if choice.get('finish_reason')!='stop' or choice['message'].get('tool_calls') or choice['message'].get('refusal'):
                raise ValueError('incomplete_answer')
            content=choice['message']['content']
            if not isinstance(content,str): raise ValueError('invalid_content')
            usage=data.get('usage') or {}
            # 사용량 숫자만 반환하며 외부 응답 원문이나 헤더를 디버깅 메타데이터에 넣지 않는다.
            usage={key:usage[key] for key in ('prompt_tokens','completion_tokens','total_tokens')
                   if type(usage.get(key)) is int and usage[key]>=0}
            return {'content':content,'usage':usage or None}
        except GeminiError: raise
        except (TimeoutError,httpx.TimeoutException):
            raise GeminiError('gemini_timeout','답변 생성 시간이 초과되었습니다.',504) from None
        except httpx.RequestError:
            raise GeminiError('gemini_connection','답변 생성 서비스에 연결하지 못했습니다.',503) from None
        except (ValueError,TypeError,KeyError,IndexError,AttributeError):
            raise GeminiError('gemini_response','답변 생성 형식이 올바르지 않습니다.') from None
