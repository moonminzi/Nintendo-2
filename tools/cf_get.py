#!/usr/bin/env python3
# 버킷 파일을 CloudFront(서명된 URL)로 받는다: S3에서 직접 받으면 GB당 요금, CloudFront는 월 1TB 무료.
# 사용법: cf_get.py <S3 키 또는 접두사/> <받을 폴더>
#   환경: CF_DOMAIN, CF_KEY_ID, CF_KEY_FILE(개인키 PEM), S3_BUCKET
#   접두사(…/)면 그 아래 파일을 전부 받는다(목록은 aws s3api). CloudFront가 안 되면 aws s3 cp 로 받는다.
import base64, json, os, subprocess, sys, time, urllib.parse

def sign(url, ttl=6 * 3600):
    exp = int(time.time() + ttl)
    pol = json.dumps({"Statement": [{"Resource": url, "Condition": {"DateLessThan": {"AWS:EpochTime": exp}}}]}, separators=(",", ":"))
    sig = subprocess.run(["openssl", "dgst", "-sha1", "-sign", os.environ["CF_KEY_FILE"]], input=pol.encode(), capture_output=True, check=True).stdout
    s = base64.b64encode(sig).decode().replace("+", "-").replace("=", "_").replace("/", "~")
    return "%s?Expires=%d&Signature=%s&Key-Pair-Id=%s" % (url, exp, s, os.environ["CF_KEY_ID"])

def keys(prefix):
    if not prefix.endswith("/"):
        return [prefix]
    out = subprocess.run(["aws", "s3api", "list-objects-v2", "--bucket", os.environ["S3_BUCKET"], "--prefix", prefix, "--output", "json"],
                         capture_output=True, check=True, text=True).stdout
    return [o["Key"] for o in (json.loads(out or "{}").get("Contents") or []) if not o["Key"].endswith("/")]

def get(key, dest_dir):
    dest = os.path.join(dest_dir, key.rsplit("/", 1)[1])
    url = "https://%s/%s" % (os.environ.get("CF_DOMAIN", ""), urllib.parse.quote(key, safe="/"))
    if os.environ.get("CF_DOMAIN") and os.environ.get("CF_KEY_ID") and os.path.exists(os.environ.get("CF_KEY_FILE", "")):
        r = subprocess.run(["curl", "-fL", "--retry", "5", "--retry-delay", "3", "--retry-all-errors", "-sS", "-o", dest, sign(url)])
        if r.returncode == 0:
            print("CloudFront:", key, os.path.getsize(dest), flush=True); return
        print("::warning::CloudFront 다운로드 실패, S3로 받음:", key, flush=True)
    subprocess.run(["aws", "s3", "cp", "s3://%s/%s" % (os.environ["S3_BUCKET"], key), dest, "--no-progress"], check=True)
    print("S3:", key, flush=True)

if __name__ == "__main__":
    src, dest_dir = sys.argv[1], sys.argv[2]
    os.makedirs(dest_dir, exist_ok=True)
    for k in keys(src): get(k, dest_dir)
