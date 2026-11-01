"""kino_loopback_block.py (2026-11-01, owner: "do 2" - close the loopback hole).

Windows Firewall never filters loopback, so the rule "Kino - no direct internet" left every local service open to his user:
the web server's admin port (Caddy 2019), the MT5 terminal, the app, ollama, n8n. This adds one persistent WFP filter per IP
version at ALE_AUTH_CONNECT: a connection whose user is "kino" and that is loopback is blocked. Nobody else is touched.

python kino_loopback_block.py add | remove | show      (run as administrator)
"""
import ctypes, ctypes.wintypes as wt, sys, uuid

fw = ctypes.WinDLL("fwpuclnt.dll")
adv = ctypes.WinDLL("advapi32.dll")
NAME = "Kino - no local services"


class GUID(ctypes.Structure):
    _fields_ = [("b", ctypes.c_ubyte * 16)]

    @classmethod
    def of(cls, s):
        g = cls()
        ctypes.memmove(g.b, uuid.UUID(s).bytes_le, 16)
        return g


LAYER_V4 = "c38d57d1-05a7-4c33-904f-7fbceee60e82"   # FWPM_LAYER_ALE_AUTH_CONNECT_V4
LAYER_V6 = "4a72393b-319f-44bc-84c3-ba54dcb3b6b4"   # FWPM_LAYER_ALE_AUTH_CONNECT_V6
COND_USER = "af043a0a-b34d-4f86-979c-c90371af6e66"  # FWPM_CONDITION_ALE_USER_ID
COND_FLAGS = "632ce23b-5167-435c-86d7-e903684aa80c"  # FWPM_CONDITION_FLAGS
FWP_UINT32, FWP_SD = 3, 14
MATCH_EQUAL, MATCH_FLAGS_ALL_SET = 0, 6
IS_LOOPBACK = 0x1
ACTION_BLOCK = 0x1001
PERSISTENT = 0x1


class BLOB(ctypes.Structure):
    _fields_ = [("size", ctypes.c_uint32), ("data", ctypes.c_void_p)]


class VALUE(ctypes.Structure):
    _fields_ = [("type", ctypes.c_uint32), ("u", ctypes.c_uint64)]


class COND(ctypes.Structure):
    _fields_ = [("fieldKey", GUID), ("matchType", ctypes.c_uint32), ("value", VALUE)]


class DISPLAY(ctypes.Structure):
    _fields_ = [("name", wt.LPWSTR), ("description", wt.LPWSTR)]


class ACTION(ctypes.Structure):
    _fields_ = [("type", ctypes.c_uint32), ("filterType", GUID)]


class FILTER(ctypes.Structure):
    _fields_ = [("filterKey", GUID), ("displayData", DISPLAY), ("flags", ctypes.c_uint32), ("providerKey", ctypes.c_void_p),
                ("providerData", BLOB), ("layerKey", GUID), ("subLayerKey", GUID), ("weight", VALUE),
                ("numFilterConditions", ctypes.c_uint32), ("filterCondition", ctypes.POINTER(COND)), ("action", ACTION),
                ("providerContextKey", GUID), ("reserved", ctypes.c_void_p), ("filterId", ctypes.c_uint64),
                ("effectiveWeight", VALUE)]


def _engine():
    h = wt.HANDLE()
    r = fw.FwpmEngineOpen0(None, 10, None, None, ctypes.byref(h))
    if r:
        raise OSError("FwpmEngineOpen0 0x%x" % (r & 0xffffffff))
    return h


def _sd_blob(sid):
    p, n = ctypes.c_void_p(), ctypes.c_ulong()
    if not adv.ConvertStringSecurityDescriptorToSecurityDescriptorW("O:LSD:(A;;CC;;;%s)" % sid, 1, ctypes.byref(p), ctypes.byref(n)):
        raise OSError("SDDL %s" % ctypes.GetLastError())
    return BLOB(n.value, p.value)


def _sid(user="kino"):
    sid, sz, dom, dsz, use = ctypes.create_string_buffer(256), wt.DWORD(256), ctypes.create_unicode_buffer(256), wt.DWORD(256), wt.DWORD()
    if not adv.LookupAccountNameW(None, user, sid, ctypes.byref(sz), dom, ctypes.byref(dsz), ctypes.byref(use)):
        raise OSError("LookupAccountName %s" % ctypes.GetLastError())
    s = wt.LPWSTR()
    adv.ConvertSidToStringSidW(sid, ctypes.byref(s))
    return s.value


def _ours(h):
    """ids of our filters, found by name"""
    import subprocess, re, os, tempfile
    f = os.path.join(tempfile.gettempdir(), "kino_wfp.xml")
    subprocess.run(["netsh", "wfp", "show", "filters", "file=" + f], capture_output=True)
    x = open(f, encoding="utf-8", errors="replace").read()
    os.remove(f)
    out = []
    for m in re.finditer(r"<item>\s*<filterKey>.*?</item>\s*(?=<item>\s*<filterKey>|</filters>)", x, re.S):
        it = m.group(0)
        if "<name>%s</name>" % NAME in it:
            fid = re.search(r"<filterId>(\d+)</filterId>", it)
            lay = re.search(r"<layerKey>([^<]+)</layerKey>", it)
            out.append((int(fid.group(1)) if fid else None, lay.group(1) if lay else "?", it))
    return out


def add():
    h = _engine()
    sd = _sd_blob(_sid())
    ids = []
    for layer in (LAYER_V4, LAYER_V6):
        c = (COND * 2)()
        c[0].fieldKey = GUID.of(COND_USER)
        c[0].matchType = MATCH_EQUAL
        c[0].value.type = FWP_SD
        c[0].value.u = ctypes.addressof(sd)
        c[1].fieldKey = GUID.of(COND_FLAGS)
        c[1].matchType = MATCH_FLAGS_ALL_SET
        c[1].value.type = FWP_UINT32
        c[1].value.u = IS_LOOPBACK
        f = FILTER()
        f.filterKey = GUID.of(str(uuid.uuid4()))
        f.displayData = DISPLAY(NAME, "Kino's Windows user may not connect to local services (loopback)")
        f.flags = PERSISTENT
        f.layerKey = GUID.of(layer)
        f.numFilterConditions = 2
        f.filterCondition = c
        f.action.type = ACTION_BLOCK
        fid = ctypes.c_uint64()
        r = fw.FwpmFilterAdd0(h, ctypes.byref(f), None, ctypes.byref(fid))
        if r:
            raise OSError("FwpmFilterAdd0 0x%x" % (r & 0xffffffff))
        ids.append(fid.value)
    fw.FwpmEngineClose0(h)
    return ids


def remove():
    h = _engine()
    n = 0
    for fid, _, _ in _ours(h):
        if fid is not None and not fw.FwpmFilterDeleteById0(h, ctypes.c_uint64(fid)):
            n += 1
    fw.FwpmEngineClose0(h)
    return n


if __name__ == "__main__":
    a = (sys.argv[1:] or ["show"])[0]
    if a == "add":
        print("added", add())
    elif a == "remove":
        print("removed", remove())
    else:
        for fid, lay, it in _ours(None):
            import re
            print(fid, lay, re.findall(r"<fieldKey>([^<]+)</fieldKey>", it))
