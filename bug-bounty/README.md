# Meta Bug Bounty – Getting Started

Meta pays for **real security bugs** reported through its own program:
https://www.facebook.com/whitehat (free to join, no course or tool purchase needed).

## Step 1 – Set up your account (do this yourself)
1. Go to facebook.com/whitehat and sign in.
2. Read the **Terms**, **Scope** and **Researcher Guidelines** fully.
3. Create **test users** with Meta's test-account tools (Whitehat settings). Test only
   on accounts you own or those test users – never on real people's accounts.
4. Install a free intercepting proxy: **Burp Suite Community** or **OWASP ZAP**.

## Step 2 – Learn the bug types Meta pays most for
| Bug class | What it means | Typical example |
|---|---|---|
| IDOR / broken access control | Changing an ID lets you see or edit someone else's data | Change `post_id=123` to `124` and see a private post |
| Privacy-setting bypass | Content set to "Only me"/"Friends" leaks to others | Private photo visible through a different API endpoint |
| Account takeover | Getting into another account | Password-reset token works for a different user |
| XSS | Your script runs in another user's browser | Unescaped input in a page or message |
| CSRF | Tricking a logged-in user into an action | State-changing request with no token check |
| Business logic | Abusing how a feature is supposed to work | Removing yourself as admin but keeping admin powers |

Free training: **PortSwigger Web Security Academy** (portswigger.net/web-security) –
do the *Access control*, *Authentication*, *XSS* and *CSRF* labs first.

## Step 3 – Practice locally
`lab/` contains a tiny fake social app with deliberate bugs. Run it and find them:

```bash
python3 bug-bounty/lab/app.py      # then open http://127.0.0.1:8000
```
Log in as `alice` / `alice123`. Goal: find at least 3 bugs (see `lab/HINTS.md` only if stuck).

## Step 4 – Hunt on Meta (in scope, on your test accounts)
- Pick **one** feature (e.g. Groups, Marketplace, Instagram close friends, Messenger).
- Use two test accounts: A (attacker) and B (victim). Capture A's requests in Burp,
  swap in B's IDs, and check whether A can see or change B's data.
- Check the *same* data through every surface: web, mobile app API, Graph API, older endpoints.
- Write down everything; one well-proven bug beats twenty guesses.

## Step 5 – Report
Use `REPORT_TEMPLATE.md`. Clear steps + proof of impact = faster triage and higher payout.

## Rules that keep you paid (and out of trouble)
- Never access, change or keep real users' data. Stop as soon as impact is shown.
- No DoS, spam, social engineering or mass automated scanning.
- Don't disclose publicly until Meta fixes it and allows it.
- Ignore anyone selling "Meta exploits", "private methods" or bounty courses.
