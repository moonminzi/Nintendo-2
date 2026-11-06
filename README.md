# Nintendo

nxnative IPA 빌드용 저장소.

## 사용법

1. 시크릿 `PROD_KEYS`에 `prod.keys` 내용을 넣습니다.
2. 업로드 사이트(AWS Lambda, 링크는 따로 보관)에서 게임 파일(.nsp/.xci/.nsz/.xcz 또는 .zip)을 올립니다.
   파일은 S3 버킷 `nintendo-games-417178828989`의 `uploads/`에 들어가고 14일 뒤 자동 삭제됩니다.
   파일 대신 **링크로 추가**에 직접 다운로드 링크(Google Drive·Dropbox 공유 링크도 가능)를 넣어도 됩니다.
   이때는 `uploads/<파일이름>.url`에 링크만 저장되고, 빌드할 때 GitHub 러너가 그 링크에서 직접 받습니다.
3. Actions → **Build IPA** → Run workflow (`game_source: s3`).
4. 끝나면 실행 페이지의 Artifacts에서 `ipa`를 받습니다.

워크플로는 GitHub OIDC로 IAM 역할 `nintendo-github-build`(uploads/ 읽기 전용)를 맡아서 버킷에서 게임을 받으므로 AWS 키 시크릿이 필요 없습니다.

업로드 사이트(Lambda `nintendo-upload-site`) 코드는 `aws/upload-site/lambda_function.py`에 있습니다. 비밀번호는 Lambda 환경 변수 `TOKEN`에만 있습니다.
