# Bug Report Template (Meta Bug Bounty)

**Title:** [Bug class] in [feature] allows [attacker] to [impact]
_e.g. "IDOR in Group post edit endpoint allows any member to edit other members' posts"_

## Summary
One or two sentences: what is broken and why it matters.

## Affected product / endpoint
- Product: (Facebook / Instagram / WhatsApp / Messenger / ...)
- Surface: (web / Android / iOS / Graph API)
- Endpoint or URL:

## Accounts used
- Attacker test account ID:
- Victim test account ID:

## Steps to reproduce
1. Log in as attacker...
2. Send this request (paste raw HTTP request from Burp)...
3. Change parameter `X` from attacker's value to victim's value...
4. Observe...

## Expected result
What should have happened (e.g. "403 / error, no data returned").

## Actual result
What happened instead (e.g. "Victim's private post body returned in response").

## Impact
Who can be attacked, what the attacker gains, what preconditions are needed.

## Proof
Screenshots / screen recording / request-response pairs (test accounts only).

## Suggested fix (optional)
e.g. "Check that the requesting user owns `post_id` before returning it."
