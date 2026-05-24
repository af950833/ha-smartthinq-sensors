# SmartThinQ LGE Sensors

Home Assistant에서 LG ThinQ 기기를 사용하기 위해 [ollo69]: https://github.com/ollo69/ha-smartthinq-sensors 의 코드를 수정한 컴포넌트입니다.

이 버전은 한국 계정 사용을 전제로 하며, 기존 모바일/OAuth 인증 방식 대신 ThinQ Web 로그인 흐름을 사용하도록 정리한 fork입니다.
LG 쌍쌍바 에어컨의 모드 및 회전 관련 부분 등이 수정 되었습니다(2019년형 쌍쌍바 에어컨(기본형)에서 테스트 되었습니다).

## 주요 변경점

- ThinQ Web 로그인 방식 사용
- 국가/언어를 `KR / ko-KR`로 고정
- 설정 화면에서 LG 계정 사용자 이름과 비밀번호만 입력
- `9006`, `9012` 응답 발생 시 client ID 갱신 처리
- Web refresh token 오류는 Home Assistant 재인증 흐름으로 처리
- 한국어 번역 추가

## 지원 환경

- Home Assistant 2025.1.0 이상
- LG ThinQ 한국 계정
- 이메일/비밀번호 기반 LG 계정

소셜 로그인 계정은 지원하지 않습니다.

## 설치

### HACS 설치

HACS를 사용 중이라면 custom repository로 추가해서 설치할 수 있습니다.

1. Home Assistant에서 `HACS`로 이동합니다.
2. 우측 상단 메뉴에서 `Custom repositories`를 선택합니다.
3. Repository에 아래 주소를 입력합니다.

```text
https://github.com/af950833/ha-smartthinq-sensors
```

4. Category는 `Integration`으로 선택합니다.
5. 추가 후 HACS에서 `SmartThinQ LGE Sensors`를 검색해 설치합니다.
6. Home Assistant를 재시작합니다.

### 수동 설치

이 저장소를 Home Assistant의 `custom_components` 아래에 배치합니다.

```text
custom_components/
  smartthinq_sensors/
    __init__.py
    manifest.json
    ...
```

파일 복사 후 Home Assistant를 재시작합니다.

## 설정

1. Home Assistant에서 `설정` > `기기 및 서비스`로 이동합니다.
2. `통합구성요소 추가`를 선택합니다.
3. `SmartThinQ LGE Sensors`를 검색합니다.
4. LG 계정 사용자 이름과 비밀번호를 입력합니다.

국가와 언어는 자동으로 `KR / ko-KR`로 저장됩니다.

## 지원 기기

기존 `smartthinq_sensors` 컴포넌트가 지원하던 LG ThinQ 기기 타입을 기반으로 합니다.

대표적으로 다음 기기를 지원합니다.

- 에어컨
- 세탁기 / 건조기
- 냉장고
- 공기청정기
- 제습기
- 식기세척기
- 오븐 / 레인지
- 정수기 / 온수기 계열

기기 모델과 ThinQ 서버 응답에 따라 노출되는 센서와 제어 항목은 달라질 수 있습니다.

## 로그와 오류

디버그 로그를 켜면 LG ThinQ 서버 응답이 매우 크게 출력될 수 있습니다.

문제 분석이 끝난 뒤에는 디버그 로그를 끄는 것을 권장합니다.

주의해서 볼 만한 오류 코드는 다음과 같습니다.

- `9006`
- `9012`
- `TokenError`
- `AuthenticationError`
- `InvalidCredentialError`

현재 버전은 `9006`, `9012`가 발생하면 client ID를 갱신하고 재시도 흐름으로 넘깁니다.

## 보안 주의

이 통합구성요소는 LG 계정 사용자 이름과 비밀번호를 사용해 ThinQ Web 로그인 흐름을 수행합니다.

- GitHub issue나 로그 공유 시 계정 정보, token, user number, device id가 포함되지 않도록 주의하세요.
- 디버그 로그에는 기기 정보와 서버 응답이 포함될 수 있습니다.

## 알려진 제한

- 한국 계정 전용입니다.
- 소셜 로그인 계정은 지원하지 않습니다.
- LG 공식 Public API 기반 통합구성요소가 아니며, LG 서버 변경에 따라 동작이 달라질 수 있습니다.
- ThinQ Web 로그인 페이지나 API 응답 구조가 변경되면 재인증 또는 코드 수정이 필요할 수 있습니다.
