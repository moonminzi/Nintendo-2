# Nintendo

nxnative IPA 빌드용 저장소. iPhone·iPad용 IPA와 Apple Silicon Mac용 네이티브 앱(.app)을 만든다.

## Build IPA 워크플로우의 `platform`

| 값 | 결과물 | 올라가는 곳 |
|---|---|---|
| `ios` (기본) | IPA | `s3://…/ipa/ipa-<번호>/`, 릴리스 `ipa-<번호>` |
| `mac-app` | Mac 앱 (`<이름>.app.zip`) | `s3://…/ipa/ipa-<번호>/mac/`, 릴리스 `mac-<번호>` |
| `both` | IPA → Mac 앱 순서로 둘 다 | 위 두 곳 모두 |

Mac 앱 참고:

- Apple Silicon(M1 이후) Mac 전용. 게임 데이터는 앱 안에 들어간다(`romfs: separate`는 IPA에만 적용).
- ad-hoc 서명이라 처음 열 때 macOS가 막는다. 시스템 설정 → 개인정보 보호 및 보안 → "그래도 열기", 또는
  `xattr -dr com.apple.quarantine "/Applications/<이름>.app"`.
- `mac_gpu`: 앱에 미리 넣을 파이프라인 캐시의 GPU. 기본 `none`이면 첫 실행 때 Mac이 직접 만든다
  (러너의 GPU는 실제 Mac과 달라서 러너 기준으로 만들면 쓸 수 없음).
- 세이브는 `~/Library/Application Support/nxnative/<타이틀 ID>/`, 로그는 `~/Library/Logs/nxnative/`.
- 자동 서명(nago-sign)은 IPA에만 적용된다.
