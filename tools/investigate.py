# 지원 목록에 없는 게임의 데이터 조사: 셰이더가 어디에 어떤 형식으로 들어 있는지 찾는다.
# 사용법: python investigate.py <nxnative 폴더> <빌드 폴더(<tid>_build)> <출력 폴더>
import sys, os, re, struct, zlib, collections, json
NXN, BUILD, OUT = sys.argv[1:4]
sys.path.insert(0, NXN); sys.path.insert(0, os.path.join(NXN, 'dm/tools'))
from dm.tools.romfs import Image
import nso
try: import zstandard
except ImportError: zstandard = None
os.makedirs(OUT, exist_ok=True)

NEEDLES = {'nvn_gfx': struct.pack('<I', 0x12345678), 'nvn_cmp': struct.pack('<I', 0x12345679),
           'glslc': struct.pack('<I', 0x19866891), 'BNSH': b'BNSH', 'SPIRV': struct.pack('<I', 0x07230203),
           'DXBC': b'DXBC', 'NVNsh': b'NVNs'}
def needles(d):
    return {k: d.count(v) for k, v in NEEDLES.items() if v in d}
def m4(b):
    s = b[:4]
    return s.decode('ascii') if all(32 <= c < 127 for c in s) and len(s) == 4 else s.hex()

rep = open(os.path.join(OUT, 'report.md'), 'w')
def p(*a, sep=' '):
    print(*a, sep=sep, file=rep); print(*a, sep=sep, flush=True)

images = []
for root, dirs, files in os.walk(BUILD):
    for f in files:
        if f.endswith('.img'): images.append(os.path.join(root, f))
p('# 조사 보고서\n\n이미지:', *images, sep='\n- ')

manifest = open(os.path.join(OUT, 'manifest.tsv'), 'w')
by_ext = collections.Counter(); ext_size = collections.Counter()
by_mag = collections.Counter(); mag_size = collections.Counter(); mag_samples = collections.defaultdict(list)
raw_hits = collections.defaultdict(list); dec_hits = collections.defaultdict(list)
dec_magic = collections.Counter(); dec_magic_samples = collections.defaultdict(list)
l5 = collections.Counter()
dirs = collections.Counter(); dir_size = collections.Counter()

def walk(img, k, path):
    for name, j in img.children(k):
        a, b, _, _, t, _ = img.entry(j)
        if t: yield path + '/' + name, a, b
        else: yield from walk(img, j, path + '/' + name)

def deep(path, f, off, size):
    hits = collections.Counter(); dhits = collections.Counter(); zt = zs = 0
    pos = 0; CH = 64 << 20
    while pos < size:
        f.seek(off + pos); d = f.read(min(CH + 64, size - pos))
        for k, v in needles(d).items(): hits[k] += v
        # zstd 프레임
        i = 0
        while zstandard and zs < 20:
            i = d.find(b'\x28\xb5\x2f\xfd', i)
            if i < 0: break
            zs += 1
            try:
                out = zstandard.ZstdDecompressor().decompressobj().decompress(d[i:i + (32 << 20)])
                if len(out) > 32:
                    dec_magic['zstd:' + m4(out)] += 1; dec_magic_samples['zstd:' + m4(out)].append(path)
                    for k2, v in needles(out).items(): dhits['zstd:' + k2] += v
            except Exception: pass
            i += 4
        # zlib 스트림
        for mt in re.finditer(rb'\x78[\x01\x5e\x9c\xda]', d):
            if zt >= 40: break
            i = mt.start(); zt += 1
            try:
                o = zlib.decompressobj(); out = o.decompress(d[i:i + (8 << 20)], 64 << 20)
                if len(out) > 32:
                    dec_magic['zlib:' + m4(out)] += 1; dec_magic_samples['zlib:' + m4(out)].append(f'{path}@{i+pos:#x}')
                    for k2, v in needles(out).items(): dhits['zlib:' + k2] += v
            except Exception: pass
        pos += CH
    if hits: raw_hits[path] = dict(hits)
    if dhits: dec_hits[path] = dict(dhits)

for im in images:
    try: img = Image(im)
    except Exception as e: p(f'\n{im}: 읽기 실패 {e}'); continue
    with open(im, 'rb') as f:
        for path, a, b in walk(img, 0, ''):
            f.seek(a); head = f.read(32)
            ext = os.path.splitext(path)[1].lower() or '(없음)'
            mg = m4(head)
            print(f'{os.path.basename(im)}\t{path}\t{b}\t{head.hex()}', file=manifest)
            by_ext[ext] += 1; ext_size[ext] += b; by_mag[mg] += 1; mag_size[mg] += b
            if len(mag_samples[mg]) < 6: mag_samples[mg].append(f'{path} ({b:,}) {head[:16].hex()}')
            top = '/'.join(path.split('/')[:3]); dirs[top] += 1; dir_size[top] += b
            if len(head) >= 4:
                w = struct.unpack('<I', head[:4])[0]; l5[w & 7] += 1
            deep(path, f, a, b)
manifest.close()

def table(title, cnt, size, samples=None, n=60):
    p(f'\n## {title}\n')
    for k, c in cnt.most_common(n):
        p(f'- `{k}` × {c} ({size[k]/1e6:,.1f} MB)' + (''.join(f'\n    - {s}' for s in samples[k]) if samples else ''))
table('확장자', by_ext, ext_size)
table('파일 앞 4바이트(매직)', by_mag, mag_size, mag_samples)
table('폴더(2단계)', dirs, dir_size, n=80)
p('\n## 원본 그대로 셰이더 표식이 나온 파일\n'); [p(f'- {k}: {v}') for k, v in sorted(raw_hits.items(), key=lambda x: -sum(x[1].values()))[:150]]
p('\n## 압축 해제 후 셰이더 표식이 나온 파일\n'); [p(f'- {k}: {v}') for k, v in sorted(dec_hits.items(), key=lambda x: -sum(x[1].values()))[:150]]
p('\n## 압축 해제 결과의 매직\n'); [p(f'- `{k}` × {c}: ' + ', '.join(dec_magic_samples[k][:4])) for k, c in dec_magic.most_common(60)]
p('\n## 앞 4바이트 & 7 (Level-5 압축 방식 값) 분포\n'); p(dict(l5))

# 실행 파일(main 등) 문자열
KEY = re.compile(rb'shader|shdr|bnsh|nvn|glsl|spir|program|effect|\.sh\b|\.vsh|\.fsh|\.psh|xfsa|xpck|arc0|arc1|cpk|\.pck|\.fa\b|\.g4|\.xc\b|\.xb\b|material|technique|pipeline|vertex|fragment|pixel', re.I)
for root, ds, files in os.walk(BUILD):
    if os.sep + 'exefs' not in root.lower() + os.sep and not any(f in ('main', 'main.npdm') for f in files): continue
    for fn in files:
        if fn.endswith('.npdm'): continue
        fp = os.path.join(root, fn)
        if os.path.getsize(fp) < 4096: continue
        d = open(fp, 'rb').read()
        if d[:4] == b'NSO0':
            try: d = bytes(nso.load(d, fp).image)
            except Exception as e: p(f'\n{fp}: NSO 해제 실패 {e}'); continue
        ss = [s for s in re.findall(rb'[\x20-\x7e]{5,200}', d) if KEY.search(s)]
        name = fp.replace(BUILD, '').strip('/').replace('/', '_')
        with open(os.path.join(OUT, f'strings_{name}.txt'), 'wb') as o: o.write(b'\n'.join(dict.fromkeys(ss)))
        p(f'\n## 실행 파일 {fp.replace(BUILD, "")} ({len(d):,} bytes): 셰이더 표식 {needles(d)}, 관련 문자열 {len(ss)}개 → strings_{name}.txt')
rep.close()
