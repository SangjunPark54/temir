---
title: Temir
emoji: 🚙
colorFrom: yellow
colorTo: gray
sdk: docker
app_port: 7860
pinned: false
license: mit
short_description: 아이폰이 리모컨, Tesla 브라우저가 스크린
---

# Temir — 아이폰으로 조작하는 Tesla 스크린

아이폰(리모컨)과 Tesla 브라우저(뷰어)를 **클라우드 WebSocket 중계**로 연결합니다.
네이티브 앱 설치, Apple 개발자 계정, 핫스팟 로컬 포트가 전혀 필요 없습니다 —
양쪽 모두 이 Space로 "나가는" HTTPS/WSS 연결만 사용하므로 iOS 포트 정책의 영향을 받지 않습니다.

## 사용 방법

1. **Tesla 브라우저**에서 이 Space 주소를 열고 → **TESLA SCREEN** 선택
2. 화면에 표시된 **QR을 아이폰 카메라로 스캔** (또는 아이폰에서 접속 후 코드 6자리 입력)
3. 아이폰 리모컨에서 콘텐츠 전송:
   - **YouTube** — 링크 전송, 재생/일시정지/탐색/볼륨 원격 제어
   - **사진** — 사진첩에서 업로드 → 차량 화면 슬라이드쇼
   - **지도** — 장소 검색 / 내 위치 / 실시간 위치 추적
   - **텍스트** — 차량 화면에 큰 글씨로 표시
   - **링크** — 웹페이지 주소를 차량으로 전송

## 알아둘 것

- 아이폰 **전체 화면 미러링은 iOS Safari가 화면 캡처 API를 지원하지 않아 웹 기술로는 불가능**합니다.
  이 앱은 그 대신 "콘텐츠 동기화" 방식으로 같은 사용자 경험을 제공합니다.
- Tesla 정책상 **동영상 재생은 주차 중에만** 가능합니다. 지도/텍스트/사진은 주행 중에도 표시됩니다.
- 세션은 인메모리로만 유지됩니다. Space가 재시작되면 코드가 초기화됩니다.
- 마지막 활동 후 3시간이 지난 세션은 자동 정리됩니다.

## 로컬 실행

```bash
pip install -r requirements.txt
uvicorn app.main:app --host 0.0.0.0 --port 7860
```

## 구조

```
├── Dockerfile
├── requirements.txt
├── app/main.py        # FastAPI — 룸/시그널링(WebSocket)/업로드/QR
└── static/
    ├── index.html     # 진입 페이지 (역할 선택)
    ├── tv.html        # Tesla 뷰어 (페어링 → 시계/유튜브/사진/지도/텍스트/링크)
    ├── remote.html    # 아이폰 리모컨
    └── temir.css      # 공통 디자인 토큰
```
