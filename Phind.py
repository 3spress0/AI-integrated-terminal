#!/usr/bin/env python3
import argparse
import sys
import json
import browser_cookie3
import cloudscraper

_PHIND_SEARCH_URL = "https://phind.com/api/web/search"


def load_phind_cookies():
    """
    Load all cookies for phind.com (and any related CF cookie) from your default browser.
    Print which cookie names and domains were found so you can verify they exist.
    """
    try:
        cj = browser_cookie3.load(domain_name="phind.com")
    except Exception as e:
        print("[ERROR] Failed to load browser cookies for phind.com:", e)
        sys.exit(1)

    # Filter down to cookies whose domain ends with phind.com (or Cloudflare if it shows up that way)
    phind_cookies = []
    for cookie in cj:
        dom = cookie.domain.lower()
        if dom.endswith("phind.com") or "phind.com" in dom:
            phind_cookies.append(cookie)

    if not phind_cookies:
        print("[ERROR] No cookies for phind.com were found. Exiting.")
        sys.exit(1)

    # Print a debug list of what cookie names and domains we loaded
    print(">> Loaded the following cookies for phind.com (and subdomains):")
    found_names = set()
    for c in phind_cookies:
        print(f"   • {c.name}  (domain = {c.domain})")
        found_names.add(c.name)

    # Check for expected names
    required_names = {"cf_clearance", "__Secure-next-auth.session-token"}
    missing = required_names - found_names
    if missing:
        print(f"[WARNING] You appear to be missing {missing}.")
        print("  → Make sure you are logged into phind.com in your browser and try again.")
    return cj


def phind_query(prompt: str, cookie_jar):
    """
    Send a POST to Phind’s “web search” endpoint (via cloudscraper),
    using the browser cookies we just loaded. Return parsed JSON.
    """
    scraper = cloudscraper.create_scraper(
        browser={"browser": "chrome", "platform": "windows", "mobile": False}
    )
    scraper.cookies = cookie_jar

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/114.0.0.0 Safari/537.36"
        ),
        "Accept": "application/json, text/plain, */*",
        "Content-Type": "application/json;charset=UTF-8",
        "Origin": "https://phind.com",
        "Referer": "https://phind.com/",
    }

    payload = {"q": prompt}

    resp = scraper.post(_PHIND_SEARCH_URL, json=payload, headers=headers)
    try:
        resp.raise_for_status()
    except Exception as e:
        print(f"[ERROR] HTTP error while querying Phind: {e}  (status {resp.status_code})")
        print("[ERROR] Response body:")
        print(resp.text)
        sys.exit(1)

    try:
        return resp.json()
    except Exception:
        print("[ERROR] Response was not valid JSON. Raw response below:")
        print(resp.text)
        sys.exit(1)


def extract_answer(json_data: dict):
    """
    Try a few common patterns to pull out a human-readable answer string from Phind’s JSON.
    Return None if nothing matches.
    """
    if not isinstance(json_data, dict):
        return None

    # Pattern 1: top-level "answer"
    ans = json_data.get("answer")
    if isinstance(ans, str):
        return ans

    # Pattern 2: "data" -> "answer"
    data = json_data.get("data", {})
    if isinstance(data, dict):
        ans2 = data.get("answer")
        if isinstance(ans2, str):
            return ans2

    # Pattern 3: "messages" -> list of {role, text}
    messages = json_data.get("messages")
    if isinstance(messages, list):
        for m in messages:
            if m.get("role") == "assistant" and isinstance(m.get("text"), str):
                return m["text"]

    return None


def main():
    parser = argparse.ArgumentParser(
        description=(
            "Standalone Phind CLI (no manual cookies). "
            "You must be logged into phind.com in your browser."
        )
    )
    parser.add_argument(
        "--prompt", required=True,
        help="The question or prompt to send to Phind."
    )
    args = parser.parse_args()

    cookie_jar = load_phind_cookies()
    print()
    print(">> Querying Phind for:", args.prompt)
    print()

    result = phind_query(args.prompt, cookie_jar)

    answer = extract_answer(result)
    if answer:
        print(">> Phind’s Answer:\n")
        print(answer.strip())
    else:
        print(">> Could not locate an “answer” field in Phind’s JSON response.")
        print(">> Full JSON follows:\n")
        print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()