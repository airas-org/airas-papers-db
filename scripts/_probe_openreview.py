"""TEMPORARY diagnostic: discover the correct OpenReview venue IDs / query shape.

Not part of the pipeline. Removed once the venue IDs are fixed.
"""
import httpx

HOSTS = {"v2": "https://api2.openreview.net", "v1": "https://api.openreview.net"}
GUESSES = [
    "NeurIPS.cc/2023/Workshop/MLSB",
    "NeurIPS.cc/2024/Workshop/MLSB",
    "ICLR.cc/2024/Workshop/GEM",
    "ICLR.cc/2025/Workshop/GEM",
    "ICLR.cc/2025/Workshop/LMRL",
]
KEYWORDS = ("MLSB", "GEM", "LMRL")


def discover(client):
    """List real venue ids containing our keywords."""
    for ver, host in HOSTS.items():
        for gid in ("venues", "active_venues"):
            try:
                r = client.get(f"{host}/groups", params={"id": gid}, timeout=60)
                r.raise_for_status()
                groups = r.json().get("groups", [])
                members = groups[0].get("members", []) if groups else []
            except Exception as e:
                print(f"[discover] {ver} {gid}: FAILED {type(e).__name__}: {e}")
                continue
            hits = [m for m in members if any(k in m.upper() for k in KEYWORDS)]
            print(f"[discover] {ver} {gid}: {len(members)} venues, {len(hits)} keyword hits")
            for h in sorted(hits):
                print(f"    {h}")


def probe(client, venue):
    """Try each plausible query shape for one venue id."""
    print(f"\n=== {venue} ===")
    for ver, host in HOSTS.items():
        # does the group even exist?
        try:
            r = client.get(f"{host}/groups", params={"id": venue}, timeout=30)
            print(f"  [{ver}] group exists: {r.status_code == 200} ({r.status_code})")
        except Exception as e:
            print(f"  [{ver}] group check failed: {type(e).__name__}")

        queries = {
            "content.venueid": {"content.venueid": venue},
            "invitation/Submission": {"invitation": f"{venue}/-/Submission"},
            "invitation/Blind_Submission": {"invitation": f"{venue}/-/Blind_Submission"},
            "domain": {"domain": venue},
        }
        for label, params in queries.items():
            try:
                r = client.get(f"{host}/notes", params={**params, "limit": 3}, timeout=30)
                if r.status_code != 200:
                    print(f"  [{ver}] {label:28} -> HTTP {r.status_code}")
                    continue
                data = r.json()
                notes = data.get("notes", [])
                print(f"  [{ver}] {label:28} -> {data.get('count', '?')} count, {len(notes)} notes")
                if notes:
                    c = notes[0].get("content", {})
                    def val(k):
                        v = c.get(k)
                        return v.get("value") if isinstance(v, dict) else v
                    print(f"        keys      : {sorted(c.keys())[:12]}")
                    print(f"        venueid   : {val('venueid')!r}")
                    print(f"        venue     : {val('venue')!r}")
                    t = val("title") or ""
                    print(f"        title     : {str(t)[:70]!r}")
                    print(f"        has abstract: {bool(val('abstract'))}, pdf: {val('pdf')!r}")
            except Exception as e:
                print(f"  [{ver}] {label:28} -> FAILED {type(e).__name__}: {e}")


def main():
    with httpx.Client(follow_redirects=True) as client:
        print("########## DISCOVERY ##########")
        discover(client)
        print("\n########## PROBES ##########")
        for v in GUESSES:
            probe(client, v)


if __name__ == "__main__":
    main()
