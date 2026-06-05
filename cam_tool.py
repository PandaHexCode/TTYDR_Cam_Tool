"""
cam_tool.py  v2.0
Paper Mario: The Thousand-Year Door (Switch Remake) – .cam.zst Editor
======================================================================
Alle Felder vollständig editierbar. Lossless round-trip garantiert.

Befehle:
  python cam_tool.py extract <datei.cam.zst>           -> datei.cam.json
  python cam_tool.py extract <datei.cam.zst> -o ziel.json
  python cam_tool.py pack    <datei.cam.json>           -> datei.cam.zst
  python cam_tool.py pack    <datei.cam.json> -o ziel.cam.zst
  python cam_tool.py info    <datei.cam.zst>

Felder im JSON:
  camera          : FOV, Near-Clip, Far-Clip
  curves[]        : Kamera-Kurven (CamCrv_*) mit allen Parametern
  shapes[]        : Kollisionsformen (CamCol_*) mit BBox und Face-Referenzen
  areas[]         : Kamera-Clip-Bereiche (CamClp_*) mit allen Parametern
  play_shapes[]   : Play-Model-Formen (PlyMdl_*)
  vtx_points[]    : Kollisions-Vertices als {x, y, z}
  face_polys[]    : Polygone als {vtxIdx_start, vtxIdx_count}
  vtx_indices[]   : Vertex-Index-Liste (flach)
  path_points[]   : Kamera-Pfad-Punkte als {x, y, z}
  anim_curve_flag : 0 oder 1 (Animations-Kurven-Schalter)
  roadcam_data_hex: Haupt-Konfig (als Hex – selten bearbeitet)
"""

import struct, json, sys
from pathlib import Path

try:
    import zstandard as zstd
except ImportError:
    import subprocess
    subprocess.check_call([sys.executable, "-m", "pip", "install",
                           "zstandard", "--break-system-packages", "-q"])
    import zstandard as zstd

CURVE_SIZE     = 0x10C                              
SHAPE_SIZE     = 0x68                               
AREA_SIZE      = 0x68                                                  
PLAYSHAPE_SIZE = 0x70                               

SYM_MAP = {
    "_ZN4data3fld7roadcamL6cameraE"   : "camera",
    "_ZN4data3fld7roadcamL4faceE"     : "face",
    "_ZN4data3fld7roadcamL5pointE"    : "point",
    "_ZN4data3fld7roadcamL3vtxE"      : "vtx",
    "_ZN4data3fld7roadcamL6vtxIdxE"   : "vtxIdx",
    "_ZN4data3fld7roadcamL9animCurveE": "animCurve",
    "_ZN4data3fld7roadcamL5curveE"    : "curve",
    "_ZN4data3fld7roadcamL5shapeE"    : "shape",
    "_ZN4data3fld7roadcamL4areaE"     : "area",
    "_ZN4data3fld7roadcamL9playShapeE": "playShape",
    "_ZN4data3fld7roadcam4dataE"      : "data",
}

def parse_symbols(raw: bytes) -> dict:
    """Gibt {kurzname: (abs_offset, size)} zurück."""
    e_shoff     = struct.unpack_from('<Q', raw, 0x28)[0]
    e_shnum     = struct.unpack_from('<H', raw, 0x3C)[0]
    e_shentsize = struct.unpack_from('<H', raw, 0x3A)[0]
    e_shstrndx  = struct.unpack_from('<H', raw, 0x3E)[0]

    shstr_base = e_shoff + e_shstrndx * e_shentsize
    shstr = raw[
        struct.unpack_from('<Q', raw, shstr_base + 24)[0]:
        struct.unpack_from('<Q', raw, shstr_base + 24)[0] +
        struct.unpack_from('<Q', raw, shstr_base + 32)[0]
    ]

    secs = {}
    for i in range(e_shnum):
        base = e_shoff + i * e_shentsize
        ni   = struct.unpack_from('<I', raw, base)[0]
        end  = shstr.index(b'\x00', ni)
        secs[shstr[ni:end].decode('ascii', errors='replace')] = (
            struct.unpack_from('<Q', raw, base + 24)[0],          
            struct.unpack_from('<Q', raw, base + 32)[0],        
        )

    data_base  = secs['.data'][0]
    strtab_off, strtab_sz = secs['.strtab']
    symtab_off, symtab_sz = secs['.symtab']
    strtab = raw[strtab_off: strtab_off + strtab_sz]

    result = {}
    for i in range(symtab_sz // 24):
        base     = symtab_off + i * 24
        st_name  = struct.unpack_from('<I', raw, base)[0]
        st_value = struct.unpack_from('<Q', raw, base + 8)[0]
        st_size  = struct.unpack_from('<Q', raw, base + 16)[0]
        end      = strtab.index(b'\x00', st_name)
        name     = strtab[st_name:end].decode('ascii', errors='replace')
        if name in SYM_MAP:
            result[SYM_MAP[name]] = (data_base + st_value, st_size)

    return result

def load_cam(path: str):
    raw_zst = Path(path).read_bytes()
    raw     = zstd.ZstdDecompressor().decompress(raw_zst)
    return raw, parse_symbols(raw)

def get(raw, syms, name) -> bytes:
    off, sz = syms[name]
    return raw[off: off + sz]

def read_name(data: bytes) -> str:
    """Liest null-terminierten String aus 64-Byte Namensfeld."""
    end = data.index(b'\x00') if b'\x00' in data else len(data)
    return data[:end].decode('ascii', errors='replace')

def write_name(name: str) -> bytes:
    """Schreibt String in 64-Byte Namensfeld."""
    return (name.encode('ascii')[:63] + b'\x00').ljust(64, b'\x00')

def rf(data: bytes, off: int) -> float:
    return struct.unpack_from('<f', data, off)[0]

def ri(data: bytes, off: int) -> int:
    return struct.unpack_from('<I', data, off)[0]

def pf(v: float) -> bytes:
    return struct.pack('<f', v)

def pi(v: int) -> bytes:
    return struct.pack('<I', v)

def decode_camera(b: bytes) -> dict:
    fov, near, far = struct.unpack_from('<3f', b)
    return {"fov": fov, "near": near, "far": far}

def decode_curve(entry: bytes) -> dict:
    """
    268-Byte CamCrv_* Eintrag.
    Payload-Layout (offset relativ zu Byte 64):
      +000 i : flags       (immer 257 = 0x101)
      +004 f : zoom_offset (Zusatz-Zoom, 0=kein Offset)
      +008 f : zoom_scale  (Zoom-Faktor, typisch 2.0)
      +012 i : pad0
      +016 i : pad1
      +020 i : unk_int0    (immer 1)
      +024 i : unk_int1    (immer 2)
      +028 f : dist_near   (Kamera-Abstand nah, z.B. 19.0 oder 50.0)
      +032 f : dist_far    (Kamera-Abstand fern, z.B. 40.0)
      +036 i : pad2
      +040 f : unk_f2      (immer 1.0)
      +044 f : unk_f3      (immer 55.0)
      +048 i : pad3
      +052 i : pad4
      +056 f : unk_f4      (immer 14.0)
      +060 i : pad5
      +064 i : pad6
      +068 f : unk_f5      (immer -4.0)
      +072 i : pad7
      +076 i : pad8
      +080 i : pad9
      +084 i : flags2      (immer 16777473 = 0x01000101)
      +088 f : pitch_min   (min. Kamera-Pitch, z.B. -19.0 oder -50.0)
      +092 i : pad10
      +096 f : height_min  (immer -100.0)
      +100 f : height_max  (immer 40.0)
      +104 i : pad11
      +108 f : unk_f6      (immer 50.0)
      +112 i : anim_start  (Start-Frame der Animations-Kurve)
      +116 i : anim_len    (Länge der Animations-Kurve, meist 8)
      +120 i : shape_idx   (Index in shapes[])
      +124 i : area_idx    (Index in areas[])
      +128 i : playshp_idx (Index in play_shapes[], 0=keiner)
      +132 i : unk_int2    (meist 1)
      +136 i : pad12
      +140 f : angle_limit (immer -90.0)
      +144..200 : pad (alle 0)
    """
    name = read_name(entry[:64])
    p = entry[64:]
    return {
        "name"        : name,
        "flags"       : ri(p,   0),
        "zoom_offset" : rf(p,   4),
        "zoom_scale"  : rf(p,   8),
        "unk_int0"    : ri(p,  20),
        "unk_int1"    : ri(p,  24),
        "dist_near"   : rf(p,  28),
        "dist_far"    : rf(p,  32),
        "unk_f2"      : rf(p,  40),
        "unk_f3"      : rf(p,  44),
        "unk_f4"      : rf(p,  56),
        "unk_f5"      : rf(p,  68),
        "flags2"      : ri(p,  84),
        "pitch_min"   : rf(p,  88),
        "height_min"  : rf(p,  96),
        "height_max"  : rf(p, 100),
        "unk_f6"      : rf(p, 108),
        "anim_start"  : ri(p, 112),
        "anim_len"    : ri(p, 116),
        "shape_idx"   : ri(p, 120),
        "area_idx"    : ri(p, 124),
        "playshp_idx" : ri(p, 128),
        "unk_int2"    : ri(p, 132),
        "angle_limit" : rf(p, 140),
        "_pad_hex"    : (p[12:16] + p[16:20] + p[36:40] + p[48:52] +
                         p[52:56] + p[60:64] + p[64:68] + p[72:76] +
                         p[76:80] + p[80:84] + p[92:96] + p[104:108] +
                         p[136:140] + p[144:]).hex()
    }

def decode_shape(entry: bytes) -> dict:
    """
    104-Byte CamCol_* Eintrag.
      +000 (64B): name
      +064 f : bbox_minX
      +068 f : bbox_minY  (meist 0)
      +072 f : bbox_minZ
      +076 f : bbox_maxX
      +080 f : f_extra
      +084 4B: pad_hex
      +088 i : face_start  (erster Face-Index in face_polys[])
      +092 i : face_count  (Anzahl Faces)
      +096 i : shape_idx   (interner Index)
      +100 i : flags
    """
    name = read_name(entry[:64])
    return {
        "name"       : name,
        "bbox_minX"  : rf(entry, 64),
        "bbox_minY"  : rf(entry, 68),
        "bbox_minZ"  : rf(entry, 72),
        "bbox_maxX"  : rf(entry, 76),
        "f_extra"    : rf(entry, 80),
        "_pad_hex"   : entry[84:88].hex(),
        "face_start" : ri(entry, 88),
        "face_count" : ri(entry, 92),
        "shape_idx"  : ri(entry, 96),
        "flags"      : ri(entry, 100),
    }

def decode_area(entry: bytes) -> dict:
    """
    104-Byte CamClp_* Eintrag.
      +000 (64B): name
      +064 i : pad0
      +068 i : point_count   (Anzahl Punkte in path_points[])
      +072 f : clip_minZ
      +076 i : pad1
      +080 f : clip_maxZ
      +084 f : clip_minX_or_Y
      +088 4B: pad_hex
      +092 f/i: clip_scale   (float wenn sinnvoller Exp, sonst int)
      +096 i : vtx_start     (Start-Index in vtx_indices[])
      +100 i : vtx_count     (Anzahl Indices)
    """
    name = read_name(entry[:64])
                                                           
    raw92 = ri(entry, 92)
    exp92 = (raw92 >> 23) & 0xFF
    v92_is_float = 0x38 <= exp92 <= 0x4A and raw92 != 0
    return {
        "name"        : name,
        "pad0"        : ri(entry, 64),
        "point_count" : ri(entry, 68),
        "clip_minZ"   : rf(entry, 72),
        "pad1"        : ri(entry, 76),
        "clip_maxZ"   : rf(entry, 80),
        "clip_side"   : rf(entry, 84),
        "_pad_hex"    : entry[88:92].hex(),
        "clip_scale"  : rf(entry, 92) if v92_is_float else raw92,
        "vtx_start"   : ri(entry, 96),
        "vtx_count"   : ri(entry, 100),
    }

def decode_playshape(entry: bytes) -> dict:
    """
    112-Byte PlyMdl_* Eintrag.
      +000 (64B): name
      +064..111 : 12 Werte (floats/ints gemischt), als benannte Felder
    """
    name = read_name(entry[:64])
    vals = []
    for i in range(12):
        off = 64 + i*4
        iv  = ri(entry, off)
        fv  = rf(entry, off)
        exp = (iv >> 23) & 0xFF
                                                 
        if 0x38 <= exp <= 0x4E and iv != 0:
            vals.append(fv)
        else:
            vals.append(iv)
    return {"name": name, "values": vals}

def encode_camera(d: dict) -> bytes:
    return struct.pack('<3f', d['fov'], d['near'], d['far'])

def encode_curve(d: dict) -> bytes:
    pad = bytes.fromhex(d['_pad_hex'])
                                                                       
    pad_lens = [4,4,4,4,4,4,4,4,4,4,4,4,4, CURVE_SIZE-64-140+4-4]
                                                                              
    p = bytearray(CURVE_SIZE - 64)
                       
    cursor = 0
    for off_list, length in [
        (12,4),(16,4),(36,4),(48,4),(52,4),
        (60,4),(64,4),(72,4),(76,4),(80,4),
        (92,4),(104,4),(136,4)
    ]:
        p[off_list:off_list+length] = pad[cursor:cursor+length]
        cursor += length
                    
    p[144:] = pad[cursor:]

    struct.pack_into('<I', p,   0, d['flags'])
    struct.pack_into('<f', p,   4, d['zoom_offset'])
    struct.pack_into('<f', p,   8, d['zoom_scale'])
    struct.pack_into('<I', p,  20, d['unk_int0'])
    struct.pack_into('<I', p,  24, d['unk_int1'])
    struct.pack_into('<f', p,  28, d['dist_near'])
    struct.pack_into('<f', p,  32, d['dist_far'])
    struct.pack_into('<f', p,  40, d['unk_f2'])
    struct.pack_into('<f', p,  44, d['unk_f3'])
    struct.pack_into('<f', p,  56, d['unk_f4'])
    struct.pack_into('<f', p,  68, d['unk_f5'])
    struct.pack_into('<I', p,  84, d['flags2'])
    struct.pack_into('<f', p,  88, d['pitch_min'])
    struct.pack_into('<f', p,  96, d['height_min'])
    struct.pack_into('<f', p, 100, d['height_max'])
    struct.pack_into('<f', p, 108, d['unk_f6'])
    struct.pack_into('<I', p, 112, d['anim_start'])
    struct.pack_into('<I', p, 116, d['anim_len'])
    struct.pack_into('<I', p, 120, d['shape_idx'])
    struct.pack_into('<I', p, 124, d['area_idx'])
    struct.pack_into('<I', p, 128, d['playshp_idx'])
    struct.pack_into('<I', p, 132, d['unk_int2'])
    struct.pack_into('<f', p, 140, d['angle_limit'])

    return write_name(d['name']) + bytes(p)

def encode_shape(d: dict) -> bytes:
    b = write_name(d['name'])
    b += pf(d['bbox_minX']) + pf(d['bbox_minY']) + pf(d['bbox_minZ']) + pf(d['bbox_maxX'])
    b += pf(d['f_extra'])
    b += bytes.fromhex(d['_pad_hex'])
    b += pi(d['face_start']) + pi(d['face_count']) + pi(d['shape_idx']) + pi(d['flags'])
    return b[:SHAPE_SIZE].ljust(SHAPE_SIZE, b'\x00')

def encode_area(d: dict) -> bytes:
    b = write_name(d['name'])
    b += pi(d['pad0']) + pi(d['point_count'])
    b += pf(d['clip_minZ']) + pi(d['pad1'])
    b += pf(d['clip_maxZ']) + pf(d['clip_side'])
    b += bytes.fromhex(d['_pad_hex'])
                                 
    cs = d['clip_scale']
    b += (pf(cs) if isinstance(cs, float) else pi(cs))
    b += pi(d['vtx_start']) + pi(d['vtx_count'])
    return b[:AREA_SIZE].ljust(AREA_SIZE, b'\x00')

def encode_playshape(d: dict) -> bytes:
    b = write_name(d['name'])
    for v in d['values']:
        b += (pf(v) if isinstance(v, float) else pi(v))
    return b[:PLAYSHAPE_SIZE].ljust(PLAYSHAPE_SIZE, b'\x00')

def extract(cam_zst_path: str, out_json_path: str = None):
    p = Path(cam_zst_path)
    if out_json_path is None:
        name = p.name
        out_json_path = str(p.parent / (name[:-4] + '.json' if name.endswith('.zst') else name + '.json'))

    print(f"[extract] {p.name}")
    raw_zst = p.read_bytes()
    raw     = zstd.ZstdDecompressor().decompress(raw_zst)
    print(f"  {len(raw_zst):,} B  →  {len(raw):,} B")

    syms = parse_symbols(raw)
    def sec(n): return get(raw, syms, n)

    cb     = sec('curve')
    curves = [decode_curve(cb[i*CURVE_SIZE:(i+1)*CURVE_SIZE])
              for i in range(len(cb) // CURVE_SIZE)]

    sb     = sec('shape')
    shapes = [decode_shape(sb[i*SHAPE_SIZE:(i+1)*SHAPE_SIZE])
              for i in range(len(sb) // SHAPE_SIZE)]

    ab = sec("area")
    if len(ab) >= AREA_SIZE:
        areas = [decode_area(ab[i*AREA_SIZE:(i+1)*AREA_SIZE])
                 for i in range(len(ab) // AREA_SIZE)]
    else:
        areas = {"_raw_hex": ab.hex()}

    pb = sec("playShape")
    if len(pb) >= PLAYSHAPE_SIZE:
        play_shapes = [decode_playshape(pb[i*PLAYSHAPE_SIZE:(i+1)*PLAYSHAPE_SIZE])
                       for i in range(len(pb) // PLAYSHAPE_SIZE)]
    else:
        play_shapes = {"_raw_hex": pb.hex()}

    vb  = sec('vtx')
    vtx = [{"x": rf(vb, i*12), "y": rf(vb, i*12+4), "z": rf(vb, i*12+8)}
           for i in range(len(vb) // 12)]

    fb    = sec('face')
    faces = [{"vtxIdx_start": ri(fb, i*8), "vtxIdx_count": ri(fb, i*8+4)}
             for i in range(len(fb) // 8)]

    ib      = sec('vtxIdx')
    vtxidx  = list(struct.unpack_from(f'<{len(ib)//4}I', ib))

    ppb        = sec('point')
    path_pts   = [{"x": rf(ppb, i*12), "y": rf(ppb, i*12+4), "z": rf(ppb, i*12+8)}
                  for i in range(len(ppb) // 12)]

    result = {
        "_meta": {"source": p.name, "tool": "cam_tool.py v2.0"},
        "camera"          : decode_camera(sec('camera')),
        "curves"          : curves,
        "shapes"          : shapes,
        "areas"           : areas,
        "play_shapes"     : play_shapes,
        "vtx_points"      : vtx,
        "face_polys"      : faces,
        "vtx_indices"     : vtxidx,
        "path_points"     : path_pts,
        "anim_curve_flag" : list(sec('animCurve')),
        "roadcam_data_hex": sec('data').hex(),
    }

    with open(out_json_path, 'w', encoding='utf-8') as f:
        json.dump(result, f, indent=2, ensure_ascii=False)

    print(f"  {len(curves)} Kurven  |  {len(shapes)} Shapes  |  {len(areas)} Areas  "
          f"|  {len(play_shapes)} PlayShapes  |  {len(vtx)} Vertices")
    print(f"  ✓ {out_json_path}")
    return out_json_path

def pack(json_path: str, out_path: str = None):
    p = Path(json_path)
    if out_path is None:
        stem = p.stem                  
        if not stem.endswith('.cam'):
            stem += '.cam'
        out_path = str(p.parent / (stem + '.zst'))

    print(f"[pack] {p.name}")
    with open(json_path, 'r', encoding='utf-8') as f:
        d = json.load(f)

    src = d['_meta']['source']
    orig = next((c for c in [p.parent / src,
                              p.parent / (src if src.endswith('.zst') else src + '.zst')]
                 if c.exists()), None)
    if orig is None:
        found = list(p.parent.glob('*.cam.zst'))
        if found:
            orig = found[0]
            print(f"  Basis: {orig.name} (aus Ordner gewählt)")
        else:
            print(f"FEHLER: Original '{src}' nicht im selben Ordner gefunden.")
            sys.exit(1)
    else:
        print(f"  Basis: {orig.name}")

    raw  = bytearray(zstd.ZstdDecompressor().decompress(orig.read_bytes()))
    syms = parse_symbols(bytes(raw))

    def write(name, new_bytes):
        off, sz = syms[name]
        if len(new_bytes) != sz:
            print(f"  WARNUNG: '{name}' Größe {sz} → {len(new_bytes)} B")
        raw[off: off + sz] = new_bytes[:sz]

    write('camera',    encode_camera(d['camera']))
    write('curve',     b''.join(encode_curve(c) for c in d['curves']))
    write('shape',     b''.join(encode_shape(s) for s in d['shapes']))
                                                                       
    if isinstance(d["areas"], dict):
        write("area", bytes.fromhex(d["areas"]["_raw_hex"]))
    else:
        write("area", b"".join(encode_area(a) for a in d["areas"]))
                                                
    if isinstance(d["play_shapes"], dict):
        write("playShape", bytes.fromhex(d["play_shapes"]["_raw_hex"]))
    elif d["play_shapes"]:
        write("playShape", b"".join(encode_playshape(ps) for ps in d["play_shapes"]))

    vb = b''
    for pt in d['vtx_points']:
        vb += struct.pack('<3f', pt['x'], pt['y'], pt['z'])
    write('vtx', vb)

    fb = b''
    for face in d['face_polys']:
        fb += struct.pack('<2I', face['vtxIdx_start'], face['vtxIdx_count'])
    write('face', fb)

    write('vtxIdx', struct.pack(f'<{len(d["vtx_indices"])}I', *d['vtx_indices']))

    ppb = b''
    for pt in d['path_points']:
        ppb += struct.pack('<3f', pt['x'], pt['y'], pt['z'])
    write('point', ppb)

    write('animCurve', bytes(d['anim_curve_flag']))
    write('data',      bytes.fromhex(d['roadcam_data_hex']))

    compressed = zstd.ZstdCompressor(level=19).compress(bytes(raw))
    Path(out_path).write_bytes(compressed)
    print(f"  {len(raw):,} B  →  {len(compressed):,} B")
    print(f"  ✓ {out_path}")

def info(cam_zst_path: str):
    raw, syms = load_cam(cam_zst_path)
    p   = Path(cam_zst_path)
    def sec(n): return get(raw, syms, n)

    cb = sec('curve')
    sb = sec('shape')
    ab = sec('area')
    pb = sec('playShape')

    cam = decode_camera(sec('camera'))
    print(f"\n{'='*60}")
    print(f"  {p.name}")
    print(f"{'='*60}")
    print(f"  FOV {cam['fov']}°   Near {cam['near']}   Far {cam['far']}")
    print(f"  Kurven:     {len(cb)//CURVE_SIZE}")
    print(f"  Shapes:     {len(sb)//SHAPE_SIZE}")
    print(f"  Areas:      {len(ab)//AREA_SIZE}")
    print(f"  PlayShapes: {len(pb)//PLAYSHAPE_SIZE}")
    print(f"  Vertices:   {len(sec('vtx'))//12}")
    print(f"  Faces:      {len(sec('face'))//8}")
    print(f"  PathPoints: {len(sec('point'))//12}")

    print(f"\n  Kurven:")
    for i in range(len(cb)//CURVE_SIZE):
        c = decode_curve(cb[i*CURVE_SIZE:(i+1)*CURVE_SIZE])
        print(f"    [{i:2d}] {c['name']:<30}  zoom_offset={c['zoom_offset']}  "
              f"dist_near={c['dist_near']}  dist_far={c['dist_far']}  "
              f"pitch_min={c['pitch_min']}")

    print(f"\n  Shapes:")
    for i in range(len(sb)//SHAPE_SIZE):
        s = decode_shape(sb[i*SHAPE_SIZE:(i+1)*SHAPE_SIZE])
        print(f"    [{i:2d}] {s['name']:<35}  faces [{s['face_start']}..{s['face_start']+s['face_count']-1}]")

    print(f"\n  Areas (Clip-Bereiche):")
    for i in range(len(ab)//AREA_SIZE):
        a = decode_area(ab[i*AREA_SIZE:(i+1)*AREA_SIZE])
        print(f"    [{i:2d}] {a['name']:<30}  clipZ=[{a['clip_minZ']:.1f}..{a['clip_maxZ']:.1f}]"
              f"  vtx [{a['vtx_start']}..{a['vtx_start']+a['vtx_count']-1}]")

    print(f"\n  Play Shapes:")
    for i in range(len(pb)//PLAYSHAPE_SIZE):
        ps = decode_playshape(pb[i*PLAYSHAPE_SIZE:(i+1)*PLAYSHAPE_SIZE])
        print(f"    [{i:2d}] {ps['name']}")
    print()

def main():
    args = sys.argv[1:]
    if not args or args[0] in ('-h', '--help', 'help'):
        print(__doc__)
        sys.exit(0)

    cmd  = args[0]
    rest = args[1:]
    out  = None
    if '-o' in rest:
        idx = rest.index('-o')
        out = rest[idx + 1]
        rest = rest[:idx] + rest[idx+2:]

    if not rest:
        print("Fehler: Keine Eingabedatei angegeben.")
        sys.exit(1)

    if   cmd == 'extract': extract(rest[0], out)
    elif cmd == 'pack'   : pack(rest[0], out)
    elif cmd == 'info'   : info(rest[0])
    else:
        print(f"Unbekannter Befehl '{cmd}'. Benutze: extract | pack | info")
        sys.exit(1)

if __name__ == '__main__':
    main()