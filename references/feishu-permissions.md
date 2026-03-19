# Feishu Permissions Notes

## Required concepts

- Application-identity permissions and user-identity permissions are different.
- `user_access_token` only carries user-identity permissions.
- Feishu OAuth must explicitly request business scopes, otherwise authorization may only include basic identity access.

## Known error codes

- `99991668`: invalid access token
- `99991679`: required user-identity permission missing

## Practical guidance

- After Feishu approves a new permission, re-run OAuth and get a fresh `user_access_token`.
- If the authorization page only shows basic identity permission, review `FEISHU_OAUTH_SCOPES`.
- Use comma-separated scopes, for example:

```text
docx:document,docx:document:create,docs:document.media:upload
```
