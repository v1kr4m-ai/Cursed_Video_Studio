"""Find which field in DJI's djmd metadata separates D-Log M clips from Normal clips.

The djmd track is protobuf with an unpublished schema. This decodes the wire format
generically (field numbers and values, no names), flattens nested messages to paths like
"3.2.7", and prints paths whose value is the same within each labelled group but differs
between groups. Run:  python -I poc/djmd_diff.py <ffmpeg> <dlogm.osv>... -- <normal.osv>...
"""

import subprocess
import sys
from collections import defaultdict


def varint(b, i):
    r = s = 0
    while True:
        c = b[i]; i += 1
        r |= (c & 0x7F) << s; s += 7
        if c < 0x80:
            return r, i


def decode(b, prefix, out, depth=0):
    """Return True if b parses fully as protobuf. Fills out[path] -> list of values."""
    i, local = 0, []
    try:
        while i < len(b):
            key, i = varint(b, i)
            f, wt = key >> 3, key & 7
            if f == 0:
                return False
            p = f"{prefix}{f}"
            if wt == 0:
                v, i = varint(b, i); local.append((p, v))
            elif wt == 1:
                local.append((p, b[i:i + 8].hex())); i += 8
            elif wt == 5:
                local.append((p, b[i:i + 4].hex())); i += 4
            elif wt == 2:
                n, i = varint(b, i)
                chunk = b[i:i + n]; i += n
                if i > len(b):
                    return False
                sub = defaultdict(list)
                if depth < 8 and chunk and decode(chunk, p + ".", sub, depth + 1):
                    for k, vs in sub.items():
                        local.extend((k, v) for v in vs)
                else:
                    local.append((p, chunk[:24].hex() if not chunk.isascii() else chunk[:40].decode()))
            else:
                return False
    except IndexError:
        return False
    for k, v in local:
        out[k].append(v)
    return True


def clip_fields(ffmpeg, path):
    data = subprocess.run([ffmpeg, "-v", "error", "-i", path, "-map", "0:d:0", "-c", "copy",
                           "-frames:d", "1", "-f", "data", "-"], capture_output=True).stdout
    out = defaultdict(list)
    decode(data, "", out)
    # A field that repeats within one packet is a list; keep its first value as the signature.
    return {k: v[0] for k, v in out.items()}


def main():
    ffmpeg, rest = sys.argv[1], sys.argv[2:]
    cut = rest.index("--")
    groups = {"dlogm": rest[:cut], "normal": rest[cut + 1:]}
    fields = {g: [clip_fields(ffmpeg, p) for p in ps] for g, ps in groups.items()}
    keys = set.intersection(*(set(f) for fs in fields.values() for f in fs))
    for k in sorted(keys, key=lambda s: [int(x) for x in s.split(".")]):
        vals = {g: {f[k] for f in fs} for g, fs in fields.items()}
        if all(len(v) == 1 for v in vals.values()) and vals["dlogm"] != vals["normal"]:
            print(f"{k:14} dlogm={vals['dlogm'].pop()!s:30} normal={vals['normal'].pop()}")


if __name__ == "__main__":
    main()
