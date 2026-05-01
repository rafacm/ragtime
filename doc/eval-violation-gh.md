# gh api recipe (planted violation)

To reply to a review comment on PR 123, run:

```bash
gh api repos/rafacm/ragtime/pulls/123/comments \
  -f body="See `process_episode()` for the fix — note the `pg_advisory_xact_lock` call." \
  -F in_reply_to=12345
```
