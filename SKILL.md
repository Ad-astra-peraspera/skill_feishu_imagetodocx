---
name: feishu-doc-image-uploader
description: Upload local images into Feishu docs through a verified docx image-block workflow. Use when Codex needs to insert a local image into an existing Feishu document, create a new Feishu document with an image, obtain or refresh a Feishu user_access_token with explicit OAuth scopes, or troubleshoot Feishu doc image upload permissions and OAuth scope issues.
---

# Feishu Doc Image Uploader

Use the bundled scripts instead of hand-writing Feishu OpenAPI requests.

## Workflow

1. On first use, ask the user to copy `.env.example` to `.env` in the skill root and fill `FEISHU_APP_ID`, `FEISHU_APP_SECRET`, and `FEISHU_OAUTH_SCOPES`.
2. Check whether `FEISHU_USER_ACCESS_TOKEN` is available.
3. If missing or expired, run `scripts/get_feishu_user_token.py` and use the default browser-popup flow first.
4. Fall back to `--no-browser`, `--print-url`, or `--code` only if the browser-popup flow fails or the user explicitly asks for a manual flow.
5. If the user needs to inspect document structure first, run `scripts/list_feishu_doc_blocks.py`.
6. If the user provides a `document_id`, use `scripts/insert_feishu_image.py`.
7. If the user wants a new document, use `scripts/create_feishu_doc_with_image.py`.
8. Return the emitted JSON and highlight `document_url`, `document_id`, `image_block_id`, and `file_token`.
9. When the user mentions a target location inside an existing doc, prefer `--anchor-block-id` or `--anchor-text` plus `--position`.

## First Use

1. Copy `.env.example` to `.env` in the skill root.
2. Fill at least:
   - `FEISHU_APP_ID`
   - `FEISHU_APP_SECRET`
   - `FEISHU_OAUTH_SCOPES`
3. Run `python scripts/get_feishu_user_token.py` to obtain a user token. Always try this default command first because it starts the local callback server and tries to open the browser automatically.
4. Use the upload scripts after the token is available.

Do not distribute personal runtime files such as:

- `feishu-user-token.json`
- `oauth-state.json`

Those files are generated locally and should stay with each user's own environment.

## Rules

- Use `user_access_token`, not `app_access_token` or `tenant_access_token`.
- Prefer the default browser-popup OAuth flow before any manual code-copy flow.
- Only use `--print-url` or `--code` when automatic browser launch or callback handling fails, or when the user explicitly requests a manual flow.
- Follow the Feishu image-block sequence exactly:
  1. Create an empty image block with `block_type=27`.
  2. Upload media with `parent_type=docx_image`.
  3. Set `parent_node` to the image block `block_id`, not the document ID.
  4. Pass `extra={"drive_route_token":"<document_id>"}` when uploading media.
  5. Call `replace_image.token=<file_token>` to bind the uploaded media to the image block.
- Prefer the existing scripts over crafting raw HTTP requests.
- Keep file paths local. If the user provides a remote URL, download it first or ask for a local path.

## Environment

- `FEISHU_USER_ACCESS_TOKEN`: required for Python upload scripts
- `FEISHU_APP_ID`: required for OAuth token retrieval
- `FEISHU_APP_SECRET`: required for OAuth token retrieval
- `FEISHU_OAUTH_SCOPES`: comma-separated Feishu OAuth scopes
- `FEISHU_REDIRECT_HOST`, `FEISHU_REDIRECT_PORT`, `FEISHU_REDIRECT_PATH`: optional OAuth callback settings
- `FEISHU_TOKEN_OUTPUT`: optional output path for the saved token JSON. Defaults to the user's local Codex skill state directory for the current skill folder.
- `FEISHU_STATE_STORE`: optional path for OAuth state persistence. Defaults to the user's local Codex skill state directory for the current skill folder.
- Empty values for optional path variables are treated as unset, so `FEISHU_TOKEN_OUTPUT=` and `FEISHU_STATE_STORE=` safely fall back to the default skill state directory.

## OAuth Notes

- Feishu OAuth must explicitly request business scopes.
- `FEISHU_OAUTH_SCOPES` must be comma-separated.
- After adding or approving new user-identity permissions in Feishu, obtain a fresh `user_access_token` by re-running OAuth.
- If Feishu returns `99991679`, re-check user-identity permissions, OAuth scopes, and whether the token was issued after the permission change.
- The OAuth helper persists `state` values to a local state store with expiration, then marks them used after a successful callback.

## Common Commands

Obtain a user token with the default browser-popup flow:

```powershell
python scripts/get_feishu_user_token.py
```

This is the preferred default flow. It starts the local callback server and tries to open the default browser automatically.

If the environment cannot launch a browser, the callback cannot be completed reliably, or the user explicitly requests a manual flow, use one of these fallbacks:

```powershell
python scripts/get_feishu_user_token.py --no-browser
```

```powershell
python scripts/get_feishu_user_token.py --print-url
```

After using a manual fallback, complete authorization in a normal browser, copy the returned authorization `code`, and exchange it manually:

```powershell
python scripts/get_feishu_user_token.py --code "<authorization_code>"
```

Saved runtime files are written to the user's local Codex skill state directory for the current skill folder by default, so they can be reused locally without being bundled into the shared skill files.
Default saved paths:

- token file: `~/.codex/skills/<skill-folder>/feishu-user-token.json`
- OAuth state store: `~/.codex/skills/<skill-folder>/oauth-state.json`

Upload and block-listing scripts automatically try to reuse the saved token file. If the saved `access_token` is expired but a `refresh_token` is available, they refresh the token automatically and overwrite the local token file.

Create a new Feishu document with an image:

```powershell
python scripts/create_feishu_doc_with_image.py --image "C:\path\to\demo.png" --title "Image Test"
```

Insert an image into an existing document:

```powershell
python scripts/insert_feishu_image.py --document-id "<doc_token>" --image "C:\path\to\demo.png"
```

List document blocks:

```powershell
python scripts/list_feishu_doc_blocks.py --document-id "<doc_token>"
```

List blocks filtered by text:

```powershell
python scripts/list_feishu_doc_blocks.py --document-id "<doc_token>" --contains-text "上传到这里"
```

Insert relative to a text anchor:

```powershell
python scripts/insert_feishu_image.py --document-id "<doc_token>" --image "C:\path\to\demo.png" --anchor-text "上传到这里" --position after
```

Insert relative to a known block:

```powershell
python scripts/insert_feishu_image.py --document-id "<doc_token>" --image "C:\path\to\demo.png" --anchor-block-id "<block_id>" --position before
```

## Troubleshooting

- `99991668`: token invalid. Refresh or re-authorize and verify the exact token value.
- `99991679`: user-identity permissions missing. Re-check Feishu user permissions and OAuth scopes.
- If Feishu reports a redirect URI error, ask the user to open the Feishu app configuration and add the exact redirect URI used by this skill. The default value is `http://127.0.0.1:3333/feishu/callback` unless `FEISHU_REDIRECT_HOST`, `FEISHU_REDIRECT_PORT`, or `FEISHU_REDIRECT_PATH` were changed in `.env`.
- If token or state storage fails and `.env` contains optional path overrides, verify the values are valid paths. Empty values are now treated as unset and will fall back to the default skill state directory.
- If callback validation fails, first retry the default browser-popup flow. If it still fails, fall back to `--print-url` plus `--code` and inspect the state mismatch message emitted by the script.
- If media upload succeeds but the image does not show in the doc, verify that `replace_image` was called with the returned `file_token`.
