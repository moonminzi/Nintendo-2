# RomFS 이미지에서 지정한 경로(접두사) 아래 파일을 꺼낸다.
# 사용법: python dump_romfs.py <nxnative> <RomFS.img> <출력 폴더> <경로1,경로2,...>
import sys, os
NXN, IMG, OUT, PFX = sys.argv[1:5]
sys.path.insert(0, NXN)
from dm.tools.romfs import Image
img = Image(IMG); pfx = [p.strip().rstrip('/') for p in PFX.split(',') if p.strip()]
def walk(k, path):
    for name, j in img.children(k):
        a, b, _, _, t, _ = img.entry(j)
        if t: yield path + '/' + name, a, b
        else: yield from walk(j, path + '/' + name)
n = 0
with open(IMG, 'rb') as f:
    for path, a, b in walk(0, ''):
        if not any(path == p or path.startswith(p + '/') for p in pfx): continue
        dst = os.path.join(OUT, path.lstrip('/')); os.makedirs(os.path.dirname(dst), exist_ok=True)
        f.seek(a); open(dst, 'wb').write(f.read(b)); n += 1; print(path, b)
print(f'{n} files')
