import os
import json
import requests
from flask import Flask, render_template, request, jsonify
from playwright.sync_api import sync_playwright
import google.generativeai as genai

app = Flask(__name__)

# ⚠️ [보안] API Key는 소스코드에 직접 적지 않고, 클라우드(Render) 환경변수에 등록하여 숨깁니다.
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "YOUR_ACTUAL_GEMINI_API_KEY")
genai.configure(api_key=GEMINI_API_KEY)

# ⚠️ 1단계에서 복사한 본인의 구글 문서 ID를 여기에 붙여넣으세요.
GOOGLE_DOC_ID = "여기에_구글_문서_ID를_입력하세요"

# 1. 구글 문서(Google Docs)로부터 실시간 가이드라인 텍스트 긁어오기
def get_google_doc_guideline(doc_id):
    try:
        # 구글 문서의 텍스트 내보내기용 오픈 주소
        export_url = f"https://docs.google.com/document/d/{doc_id}/export?format=txt"
        response = requests.get(export_url, timeout=10)
        if response.status_code == 200:
            print("[시스템] 구글 문서 지식 베이스 동기화 완료")
            return response.text
    except Exception as e:
        print(f"[경고] 구글 문서 로드 실패: {str(e)}")
    
    # 실패 시 작동할 최소한의 기본 가이드라인
    return "이중 질문, 유도성 질문, 모호한 문항 표현을 감점 처리할 것."

# 2. URL로부터 설문지 문항을 강제로 긁어오는 Playwright 크롤러 (오타 전면 수정 완료)
def scrape_survey_content(url):
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context()  # 🔗 표준 명령어로 완벽 교정
        page = context.new_page()
        
        # 실제 사람이 접속하는 것처럼 User-Agent 위장 설정
        page.set_extra_http_headers({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        })
        
        print(f"[시스템] 설문지 접속 중: {url}")
        page.goto(url, wait_until="networkidle", timeout=30000)
        page.wait_for_timeout(2000)
        
        survey_text = page.locator("body").inner_text()
        browser.close()
        return survey_text

# 3. 메인 대시보드 페이지 렌더링
@app.route('/')
def index():
    return render_template('index.html')

# 4. 비동기 진단 API 엔드포인트
@app.route('/diagnose', methods=['POST'])
def diagnose():
    try:
        data = request.get_json()
        survey_url = data.get('surveyUrl')
        
        if not survey_url:
            return jsonify({"status": "error", "message": "설문지 URL이 입력되지 않았습니다."}), 400
        
        # Step A: 구글 문서 원격지에서 최신 가이드라인 실시간 수집
        guideline = get_google_doc_guideline(GOOGLE_DOC_ID)

        # Step B: Playwright 가동하여 웹페이지 문항 스크래핑
        scraped_content = scrape_survey_content(survey_url)
        
        if not scraped_content.strip():
            raise Exception("설문지 주소에서 문항 텍스트를 추출하지 못했습니다. 주소를 다시 확인해 주세요.")

        # Step C: Gemini 프롬프트 조립
        prompt = f"""
        당신은 설문조사 방법론 전문가인 'Survey Doctor' Agent입니다.
        아래의 [채점 및 검증 가이드라인]을 엄격히 준수하여, 스크래핑된 [설문지 데이터]를 정밀 진단해 주세요.
        
        [채점 및 검증 가이드라인]
        {guideline}
        
        [스크래핑된 설문지 데이터]
        {scraped_content}
        
        [요구사항]
        결과는 웹 화면에 시각화하기 좋게 반드시 아래의 JSON 포맷으로만 답변하세요. 마크다운 기호(```json)는 생략하고 순수 JSON 문자열로만 반환하세요.
        {{
          "score": 0,
          "summary": "설문지에 대한 한 줄 요약 평가",
          "details": [
            {{"type": "감점요인 또는 장점 유형", "message": "상세 분석 및 수정 제안 내용"}}
          ]
        }}
        """

        # Step D: 최신 모델을 활용한 AI 추론
        model = genai.GenerativeModel('gemini-2.5-flash')
        response = model.generate_content(prompt)
        
        ai_text = response.text.strip()
        ai_text = ai_text.replace("```json", "").replace("```", "").strip()
        
        return jsonify({"status": "success", "data": json.loads(ai_text)})

    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

if __name__ == '__main__':
    # 클라우드 서버 환경에서는 포트를 유동적으로 열어야 하므로 호스트 설정을 변경합니다.
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)