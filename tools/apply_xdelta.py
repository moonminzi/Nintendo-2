# xdelta 한국어 패치(원본 파일 + 차이 파일 → 바뀐 파일)를 RomFS 이미지의 원본에 적용해 덮어쓰기 폴더를 만든다.
# 사용법: python apply_xdelta.py <nxnative> <RomFS.img> <*.xdelta 가 든 폴더> <출력 폴더(그 안에 RomFS 경로대로 생김)>
# <이름>.xdelta 는 RomFS 안의 <이름> 파일(경로 무관, 하나여야 함)에 적용한다 (패치의 1patch_all.bat 과 같은 규칙).
import sys, os, subprocess, tempfile
NXN, IMG, PDIR, OUT = sys.argv[1:5]
sys.path.insert(0, NXN)
from dm.tools.romfs import Image
img = Image(IMG); by_name = {}
def walk(k, path):
    for name, j in img.children(k):
        a, b, _, _, t, _ = img.entry(j)
        if t: by_name.setdefault(name, []).append((path + '/' + name, a, b))
        else: walk(j, path + '/' + name)
walk(0, '')
patches = sorted(os.path.join(r, f) for r, _, fs in os.walk(PDIR) for f in fs if f.endswith('.xdelta'))
if not patches: sys.exit('[RED] .xdelta 파일이 없습니다')
fail = 0
with open(IMG, 'rb') as f:
    for p in patches:
        name = os.path.basename(p)[:-len('.xdelta')]; hits = by_name.get(name, [])
        if len(hits) != 1: print(f'[RED] {name}: RomFS 안에 {len(hits)}개 (하나여야 함)'); fail += 1; continue
        path, a, b = hits[0]; dst = os.path.join(OUT, path.lstrip('/')); os.makedirs(os.path.dirname(dst), exist_ok=True)
        with tempfile.NamedTemporaryFile(dir=OUT, delete=False) as t:
            f.seek(a); left = b
            while left: c = f.read(min(left, 64 << 20)); t.write(c); left -= len(c)
        r = subprocess.run(['xdelta3', '-d', '-f', '-s', t.name, p, dst], capture_output=True, text=True)
        os.unlink(t.name)
        if r.returncode: print(f'[RED] {name}: xdelta 실패 (원본 버전이 다를 수 있음) {r.stderr.strip()[:300]}'); fail += 1; continue
        print(f'ok {path}: {b:,} → {os.path.getsize(dst):,}')
sys.exit(1 if fail else 0)
