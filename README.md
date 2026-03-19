# Feishu Doc Image Uploader Skill

A Codex skill for uploading local images into Feishu docs through a verified docx image-block workflow.

## What It Does

- Obtain or refresh a Feishu `user_access_token`
- Create a new Feishu document and insert a local image
- Insert a local image into an existing Feishu document
- Find anchor blocks in a document before inserting an image
- Troubleshoot common OAuth scope and redirect issues

## Folder Structure

```text
feishu_doc_image_uploader_1.0.1/
├─ SKILL.md
├─ README.md
├─ .env.example
├─ .gitignore
├─ agents/
│  └─ openai.yaml
├─ references/
│  └─ feishu-permissions.md
└─ scripts/
   ├─ create_feishu_doc_with_image.py
   ├─ feishu_token_utils.py
   ├─ get_feishu_user_token.py
   ├─ insert_feishu_image.py
   └─ list_feishu_doc_blocks.py
```

## Quick Start

1. Copy `.env.example` to `.env`.
2. Fill:
   - `FEISHU_APP_ID`
   - `FEISHU_APP_SECRET`
   - `FEISHU_OAUTH_SCOPES`
3. Run the default OAuth flow:

```powershell
python scripts/get_feishu_user_token.py
```

This default flow starts a local callback server and tries to open the browser automatically.

## Common Commands

Get a token:

```powershell
python scripts/get_feishu_user_token.py
```

Manual fallback if browser callback is inconvenient:

```powershell
python scripts/get_feishu_user_token.py --print-url
python scripts/get_feishu_user_token.py --code "<authorization_code>"
```

Create a new Feishu document with an image:

```powershell
python scripts/create_feishu_doc_with_image.py --image "C:\path\to\demo.png" --title "Image Test"
```

Insert an image into an existing document:

```powershell
python scripts/insert_feishu_image.py --document-id "<doc_token>" --image "C:\path\to\demo.png"
```

List blocks in a document:

```powershell
python scripts/list_feishu_doc_blocks.py --document-id "<doc_token>"
```

Find an anchor block by text:

```powershell
python scripts/list_feishu_doc_blocks.py --document-id "<doc_token>" --contains-text "上传到这里"
```

Insert relative to an anchor text:

```powershell
python scripts/insert_feishu_image.py --document-id "<doc_token>" --image "C:\path\to\demo.png" --anchor-text "上传到这里" --position after
```

## Runtime Files

This skill keeps runtime files out of the distributed skill folder.

By default, generated files are stored in the user's Codex skill state directory for the current skill folder:

- `feishu-user-token.json`
- `oauth-state.json`

## Notes

- Use `user_access_token`, not `app_access_token` or `tenant_access_token`
- Empty values for `FEISHU_TOKEN_OUTPUT` and `FEISHU_STATE_STORE` fall back to the default state directory
- If Feishu reports a redirect URI error, configure the app redirect URI to match the skill settings
- Default redirect URI: `http://127.0.0.1:3333/feishu/callback`
