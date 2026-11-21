---
name: execute-approved-actions
description: Apply human-approved Reckon SEO actions to the website and report the result for independent verification. Use when asked to execute, apply or publish approved SEO changes.
---

# Execute approved actions

Only act on actions a human has already approved in Reckon.

1. Call `reckon_approved_actions` for the website. Do nothing for anything not listed.
2. Skip, and tell the user about, any action whose `action_type` is not supported by the
   `wordpress-apply-action` skill (currently only `heading`). Do not claim it.
3. For one supported action, call `reckon_claim_action`. If it fails (for example HTTP
   409), someone else owns it: stop and do not write.
4. Perform the write and read-back exactly as the `wordpress-apply-action` skill describes,
   then call `reckon_report_action` with the observed state. If you cannot complete the
   write, report `failed` rather than leaving the claim open.
5. Tell the user the status Reckon returns. Say "verified" only when
   `verified_by_reckon` is true; `executed` alone means Reckon has not confirmed it.
6. Handle one action at a time and finish its report before claiming the next.

## Rules

- You cannot approve or reject actions, and you must not attempt to bypass approval.
- Never claim success from the write response alone.
- If you cannot reach the site's editing tool, report `failed`; do not guess.
