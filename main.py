import os
import hmac
import hashlib
import time
import requests
from urllib.parse import urlencode
from datetime import datetime, timedelta
from fastapi import FastAPI, Request
from slack_bolt import App
from slack_bolt.adapter.fastapi import SlackRequestHandler

# 1. 환경 변수 로드
SLACK_BOT_TOKEN = os.environ.get("SLACK_BOT_TOKEN")
SLACK_SIGNING_SECRET = os.environ.get("SLACK_SIGNING_SECRET")

COUPANG_ACCESS_KEY = os.environ.get("COUPANG_ACCESS_KEY")
COUPANG_SECRET_KEY = os.environ.get("COUPANG_SECRET_KEY")
COUPANG_VENDOR_ID = os.environ.get("COUPANG_VENDOR_ID")

# 2. Slack Bolt 앱 & FastAPI 앱 초기화
slack_app = App(token=SLACK_BOT_TOKEN, signing_secret=SLACK_SIGNING_SECRET)
handler = SlackRequestHandler(slack_app)
api_app = FastAPI()

# 3. 쿠팡 WING HMAC 서명 생성 함수
def generate_coupang_signature(method: str, uri: str, secret_key: str, access_key: str) -> str:
    datetime_gmt = time.strftime('%y%m%dT%H%M%SZ', time.gmtime())
    message = datetime_gmt + method + uri
    signature = hmac.new(
        secret_key.encode('utf-8'),
        message.encode('utf-8'),
        hashlib.sha256
    ).hexdigest()
    return f"CEA algorithm=HmacSHA256, access-key={access_key}, signed-date={datetime_gmt}, signature={signature}"

# 4. 쿠팡 WING API [결제완료] 주문 수집 함수 (에러 상세 반환)
def get_coupang_paid_orders():
    today = datetime.now()
    start_date = (today - timedelta(days=7)).strftime('%Y-%m-%d')
    end_date = today.strftime('%Y-%m-%d')

    path = f"/v2/providers/openapi/apis/api/v4/vendors/{COUPANG_VENDOR_ID}/ordersheets"
    query_params = {
        "createdAtFrom": start_date,
        "createdAtTo": end_date,
        "status": "ACCEPT"
    }
    query_string = urlencode(query_params)
    full_uri = f"{path}?{query_string}"
    
    auth_header = generate_coupang_signature("GET", full_uri, COUPANG_SECRET_KEY, COUPANG_ACCESS_KEY)
    
    headers = {
        "Authorization": auth_header,
        "Content-Type": "application/json;charset=UTF-8"
    }
    
    url = f"https://api-gateway.coupang.com{full_uri}"
    
    response = requests.get(url, headers=headers)
    if response.status_code == 200:
        res_data = response.json()
        return res_data.get("data", [])
    else:
        # 쿠팡이 거절한 원인(상태 코드와 에러 메시지)을 그대로 반환
        print(f"쿠팡 API 에러: {response.status_code} - {response.text}")
        return f"ERROR_{response.status_code}_{response.text}"

# 5. 슬랙 멘션 핸들러
@slack_app.event("app_mention")
def handle_app_mentions(event, say):
    text = event.get("text", "")
    
    if "주문" in text or "신규" in text or "확인" in text or "목록" in text or "보여" in text:
        say("⏳ 쿠팡 WING에서 **[결제완료]** 주문을 조회하고 있습니다 잠시만요! 📦")
        
        result = get_coupang_paid_orders()
        
        # 에러 문자열이 반환된 경우 슬랙에 원인 출력
        if isinstance(result, str) and result.startswith("ERROR_"):
            say(f"❌ 쿠팡 API 연동 실패:\n```{result}```")
            return

        if result is None:
            say("❌ 쿠팡 API 응답을 받지 못했습니다.")
            return

        if not result:
            say("✅ 현재 **[결제완료]** 상태인 신규 주문이 없습니다.")
            return

        orders = result
        blocks = [
            {
                "type": "header",
                "text": {
                    "type": "plain_text",
                    "text": f"📦 쿠팡 신규 주문 목록 (총 {len(orders)}건)",
                    "emoji": True
                }
            },
            {"type": "divider"}
        ]

        for order in orders:
            order_id = order.get("orderId")
            order_date = order.get("orderedAt")
            receiver_name = order.get("receiver", {}).get("name", "이름 없음")
            receiver_addr = order.get("receiver", {}).get("addr1", "") + " " + order.get("receiver", {}).get("addr2", "")
            
            items_str = ""
            for item in order.get("orderItems", []):
                product_name = item.get("vendorItemName")
                quantity = item.get("shippingCount")
                items_str += f"• *{product_name}* ({quantity}개)\n"

            blocks.append({
                "type": "section",
                "fields": [
                    {"type": "mrkdwn", "text": f"*주문번호:*\n{order_id}"},
                    {"type": "mrkdwn", "text": f"*주문일시:*\n{order_date}"},
                    {"type": "mrkdwn", "text": f"*수령인:*\n{receiver_name}"},
                    {"type": "mrkdwn", "text": f"*배송지:*\n{receiver_addr}"}
                ]
            })
            blocks.append({
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"*주문 상품:*\n{items_str}"
                }
            })
            blocks.append({"type": "divider"})

        say(blocks=blocks)
    else:
        say("안녕하세요! 저를 태그하고 **'결제완료 주문 보여줘'**라고 말씀해 보세요!")

# 6. FastAPI 라우터 설정
@api_app.post("/slack/events")
async def slack_events_endpoint(req: Request):
    return await handler.handle(req)
