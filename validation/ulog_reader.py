"""Minimal PX4 ULog reader (no dependencies beyond numpy).

Format: https://docs.px4.io/main/en/dev_log/ulog_file_format.html
read_ulog(path) -> dict with:
    "topics": {(name, multi_id): numpy structured array}   (all logged topics)
    "info":   {key: value}                                 (info messages, e.g. sys_name, ver_hw)
    "params": {name: value}
    "logs":   [(timestamp_us, level, text)]                (logged console messages)
    "start_us": first timestamp in the file header
"""
import struct

import numpy as np

_BASIC = {
    "int8_t": "i1", "uint8_t": "u1", "int16_t": "<i2", "uint16_t": "<u2", "int32_t": "<i4",
    "uint32_t": "<u4", "int64_t": "<i8", "uint64_t": "<u8", "float": "<f4", "double": "<f8",
    "bool": "u1", "char": "S1",
}


def _parse_field(f):
    ftype, fname = f.split(" ")
    n = None
    if "[" in ftype:
        ftype, n = ftype[:-1].split("[")
        n = int(n)
    return ftype, n, fname


def _build_dtype(name, formats, cache):
    if name in cache:
        return cache[name]
    fields = []
    for f in formats[name]:
        ftype, n, fname = _parse_field(f)
        base = np.dtype(_BASIC[ftype]) if ftype in _BASIC else _build_dtype(ftype, formats, cache)
        if ftype == "char" and n:
            fields.append((fname, f"S{n}"))
        elif n:
            fields.append((fname, base, (n,)))
        else:
            fields.append((fname, base))
    dt = np.dtype(fields)
    cache[name] = dt
    return dt


def _decode_value(type_str, raw):
    ftype, n, _ = _parse_field(type_str + " x") if " " not in type_str else _parse_field(type_str)
    if ftype == "char":
        return raw.decode("utf-8", "replace").rstrip("\x00")
    dt = np.dtype(_BASIC.get(ftype, "u1"))
    arr = np.frombuffer(raw, dtype=dt)
    return arr if n else (arr[0].item() if len(arr) else None)


def read_ulog(path):
    data = open(path, "rb").read()
    if data[:7] != b"ULog\x01\x12\x35":
        raise ValueError(f"{path}: not a ULog file")
    start_us = struct.unpack_from("<Q", data, 8)[0]
    pos = 16
    formats, subs, chunks = {}, {}, {}
    info, params, logs = {}, {}, []
    while pos + 3 <= len(data):
        size, mtype = struct.unpack_from("<HB", data, pos)
        pos += 3
        payload = data[pos:pos + size]
        pos += size
        if len(payload) < size:
            break                                   # truncated tail
        t = chr(mtype)
        if t == "F":
            s = payload.decode("utf-8", "replace")
            name, body = s.split(":", 1)
            formats[name] = [x for x in body.split(";") if x]
        elif t == "A":
            multi_id, msg_id = struct.unpack_from("<BH", payload, 0)
            subs[msg_id] = (payload[3:].decode("utf-8", "replace"), multi_id)
        elif t == "D":
            msg_id = struct.unpack_from("<H", payload, 0)[0]
            chunks.setdefault(msg_id, []).append(payload[2:])
        elif t in "IMP":
            off = 1 if t == "M" else 0                 # multi-info has an is_continued byte
            klen = payload[off]
            key = payload[off + 1:off + 1 + klen].decode("utf-8", "replace")
            raw = payload[off + 1 + klen:]
            type_str, kname = key.rsplit(" ", 1)
            try:
                val = _decode_value(type_str, raw)
            except Exception:
                val = raw
            (params if t == "P" else info)[kname] = val
        elif t == "L":
            level = payload[0]
            ts = struct.unpack_from("<Q", payload, 1)[0]
            logs.append((ts, level, payload[9:].decode("utf-8", "replace")))
    cache, topics = {}, {}
    for msg_id, parts in chunks.items():
        if msg_id not in subs:
            continue
        name, multi_id = subs[msg_id]
        if name not in formats:
            continue
        dt = _build_dtype(name, formats, cache)
        buf = b"".join(p.ljust(dt.itemsize, b"\x00")[:dt.itemsize] for p in parts)
        topics[(name, multi_id)] = np.frombuffer(buf, dtype=dt)
    return dict(topics=topics, info=info, params=params, logs=logs, start_us=start_us)
