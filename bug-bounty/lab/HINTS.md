# Lab hints (try first, read later)

There are 5 deliberate bugs. Each matches a real class Meta pays for.

1. **Privacy bypass via API** – the web page `/post?id=` checks privacy. Does `/api/post?id=` do the same? Try post 102 as alice.
2. **Data exposure (IDOR)** – `/api/user?id=` shows your own email. What about `id=3`?
3. **Stored XSS** – your bio is shown on `/profile`. Is it escaped? Try `<script>alert(1)</script>`.
4. **IDOR on write** – the bio form sends a hidden `id`. Change it (Burp or browser dev tools) to `2`.
5. **Account takeover** – request a reset for *your own* account, then submit the reset form with your token but `id=2`. Can you log in as bob with the new password?

For each one, practice writing a full report with `../REPORT_TEMPLATE.md`.
