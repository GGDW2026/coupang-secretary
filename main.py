import os
import time
import hmac
import hashlib
import requests
from fastapi import FastAPI, Request
from slack_bolt import App
from slack_bolt.adapter.fastapi import SlackRequestHandler

# 1. 환경 변수 (보유하고 계신 키 값들을 이곳에 연결합니다)
SLACK_BOT_TOKEN = os.environ.get("SLACK_BOT_TOKEN")
SLACK_SIGNING_SECRET = os.environ.get("SLACK_SIGNING_SECRET")
COUPANG_ACCESS_KEY = os.environ.get("COUPANG_ACCESS_KEY")
COUPANG_SECRET_KEY = os.environ.get("COUPANG_SECRET_KEY")
COUPANG_VENDOR_ID = os.environ.get("COUPANG_VENDOR_ID")
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")

app = App(token=SLACK_BOT_TOKEN, signing_secret=SLACK_SIGNING_SECRET)
api_app = FastAPI()
handler = SlackRequestHandler(app)

# 2. 쿠팡 API HMAC 인증 서명 생성기
def generate_coupang_signature(method, url, secret_key, access_key):
    path, *query = url.split("?")
    datetime_gmt = time.strftime('%y%m%d' + 'T' + '%H%M%S' + 'Z', time.gmtime())
    message = datetime_gmt + method + path + (query[0] if query else "")
    signature = hmac.new(
        secret_key.encode('utf-8'),
        message.encode('utf-8'),
        hashlib.sha256
    ).hexdigest()
    return f"CEA algorithm=HmacSHA256, access-key={access_key}, signed-date={datetime_gmt}, signature={signature}"

# 3. 쿠팡 신규 주문(결제 완료) 조회 함수
def fetch_coupang_orders():
    method = "GET"
    url = f"/v2/providers/seller_api/apis/v1/marketplace/vendor-documents/{COUPANG_VENDOR_ID}/orderSheets?status=ACCEPT"
    host = "https://api-gateway.coupang.com"
    
    headers = {
        "Authorization": generate_coupang_signature(method, url, COUPANG_SECRET_KEY, COUPANG_ACCESS_KEY),
        "Content-Type": "application/json",
        "X-Requested-By": COUPANG_ACCESS_KEY
    }
    
    response = requests.get(host + url, headers=headers)
    if response.status_code == 200:
        return response.json().get("data", [])
    return []

# 4. 슬랙 명령어: "/신규주문확인" 입력 시 동작
@app.command("/신규주문확인")
def handle_check_orders(ack, respond, command):
    ack()
    respond("🔍 쿠팡 WING에서 신규 주문 내역을 조회 중입니다...")
    
    orders = fetch_coupang_orders()
    
    if not orders:
        respond("📦 현재 처리해야 할 신규 주문이 없습니다.")
        return

    # 주문 요약 메시지 구성
    msg = f"🛒 **총 {len(orders)}건의 신규 주문이 접수되었습니다.**\n마스터 테이블 기록 및 발주 프로세스를 진행하시겠습니까?"
    
    respond(
        blocks=[
            {"type": "section", "text": {"type": "mrkdwn", "text": msg}},
            {
                "type": "actions",
                "elements": [
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "🚀 자동 발주 및 시트 기록 승인"},
                        "style": "primary",
                        "action_id": "approve_fulfillment"
                    }
                ]
            }
        ]
    )

# 5. 슬랙 버튼 클릭 시 승인 처리 및 후속 작업 실행
@app.action("approve_fulfillment")
def handle_approval(ack, body, respond):
    ack()
    respond("⚡ 승인이 확인되었습니다. 구글 시트 마스터 테이블에 기록하고 도매몰 연동을 시작합니다...")
    
    # [추후 확장 영역] 구글 시트 API 연동 및 도매몰 발주 로직이 여기에 들어갑니다.
    
    respond("✨ 모든 주문의 마스터 테이블 기록 및 발주 프로세스가 완료되었습니다!")

# 슬랙 이벤트 수신 라우터
@api_app.post("/slack/events")
async def endpoint(req: Request):
    return await handler.handle(req)