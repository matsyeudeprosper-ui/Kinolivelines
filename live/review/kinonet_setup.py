"""kinonet_setup.py (2026-11-05, owner: "Approved-toolbox with internet: yes").

One-time setup of the Windows user "kinonet": the hands that run Kino's APPROVED tools with internet.
  - kinonet is a standard user with the same deny list as kino (projects, terminals, keys, admin profile, secrets)
  - its home C:\\KinoNet sits OUTSIDE Kino's world: python copy + approved\\ (only the admin writes there) + out\\ (kinonet writes)
    so Kino cannot swap an approved tool or the python that runs it
  - internet yes, but no loopback (WFP) and no private / tailnet / cloud-metadata addresses (firewall)
Run as Administrator:  python kinonet_setup.py        (idempotent)
"""
import os, secrets, shutil, subprocess, sys

ROOT = r"C:\KinoNet"
SECRET = r"C:\ProgramData\kino_secret\net_pw.txt"
DENY = [r"C:\Projects", r"C:\NestTerminals", r"C:\ProkNetKeys", r"C:\ProkNetBrain", r"C:\config", r"C:\Caddy", r"C:\Android",
        r"C:\tools", r"C:\nssm", r"C:\Users\Administrator", r"C:\Users\cloudbase-init", r"C:\ProgramData\kino_secret"]
PRIVATE = "10.0.0.0/8,172.16.0.0/12,192.168.0.0/16,100.64.0.0/10,169.254.0.0/16,127.0.0.0/8,fc00::/7,fe80::/10,::1"


def sh(*a, ok=True):
    r = subprocess.run(list(a), capture_output=True, text=True)
    if ok and r.returncode:
        print("FAILED", a, r.stdout[-400:], r.stderr[-400:])
    return r


def main():
    # 1 the user
    if sh("powershell", "-NoProfile", "-c", "Get-LocalUser kinonet", ok=False).returncode:
        pw = secrets.token_urlsafe(24) + "aA1!"
        open(SECRET, "w", encoding="ascii").write(pw)
        env = dict(os.environ, KN_PW=pw)            # the password never sits on a command line
        r = subprocess.run(["powershell", "-NoProfile", "-c",
                            "New-LocalUser -Name kinonet -Password (ConvertTo-SecureString $env:KN_PW -AsPlainText -Force) "
                            "-PasswordNeverExpires -UserMayNotChangePassword -Description 'Kino approved tools (internet)' | Out-Null; "
                            "Add-LocalGroupMember -Group Users -Member kinonet"], capture_output=True, text=True, env=env)
        if r.returncode:
            sys.exit("user not created: " + r.stderr[-400:])
        print("user kinonet created")
    else:
        print("user kinonet exists")
    # 2 the deny list (same as kino)
    for p in DENY:
        if os.path.exists(p):
            sh("icacls", p, "/deny", "kinonet:(OI)(CI)(RX,W)")
    # kino's world: kinonet reads nothing of it and writes nothing to it
    sh("icacls", r"C:\KinoWorld", "/deny", "kinonet:(OI)(CI)(RX,W)")
    # 3 its own home, outside the world, inheritance cut (no BUILTIN\Users)
    for d in ("", "approved", "out", "python"):
        os.makedirs(os.path.join(ROOT, d), exist_ok=True)
    if not os.path.exists(os.path.join(ROOT, "python", "python.exe")):
        # from the admin's own install, not Kino's copy (he can write to his)
        src = os.path.join(os.environ["LOCALAPPDATA"], "Programs", "Python", "Python311")
        shutil.copytree(src, os.path.join(ROOT, "python"), dirs_exist_ok=True,
                        ignore=shutil.ignore_patterns("site-packages", "__pycache__", "Scripts", "Doc", "tcl", "Tools"))
    sh("icacls", ROOT, "/inheritance:r", "/grant:r", "Administrators:(OI)(CI)(F)", "SYSTEM:(OI)(CI)(F)",
       "kinonet:(OI)(CI)(RX)", "kino:(OI)(CI)(RX)")
    sh("icacls", os.path.join(ROOT, "out"), "/grant", "kinonet:(OI)(CI)(M)")
    # 4 network: no local services (WFP loopback), no private ranges (firewall)
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "robots"))
    import kino_loopback_block as LB
    nm = "Kinonet - no local services"
    if not LB._ours(None, nm):
        print("wfp", LB.add("kinonet", nm))
    sid = LB._sid("kinonet")
    sh("powershell", "-NoProfile", "-c", "Remove-NetFirewallRule -DisplayName 'Kinonet - no private networks' -ErrorAction SilentlyContinue", ok=False)
    sh("powershell", "-NoProfile", "-c",
       "New-NetFirewallRule -DisplayName 'Kinonet - no private networks' -Direction Outbound -Action Block -RemoteAddress %s "
       "-LocalUser 'D:(A;;CC;;;%s)' | Out-Null" % (PRIVATE, sid))
    print("done")


if __name__ == "__main__":
    main()
