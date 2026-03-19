#!/usr/bin/env python3
import argparse
import json
import os
import sys
import urllib.error
import urllib.request

from feishu_token_utils import load_dotenv, resolve_user_access_token


load_dotenv()


OPENAPI_BASE = "https://open.feishu.cn/open-apis"


def load_access_token(explicit_token: str | None) -> str:
    return resolve_user_access_token(explicit_token)


def request_json(access_token: str, method: str, path: str) -> dict:
    req = urllib.request.Request(
        f"{OPENAPI_BASE}{path}",
        method=method,
        headers={"Authorization": f"Bearer {access_token}"},
    )

    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "ignore")
        raise RuntimeError(f"{method} {path} failed: {exc.code} {detail}") from exc


def get_document_blocks(access_token: str, doc_token: str) -> list[dict]:
    page_token = None
    blocks: list[dict] = []

    while True:
        suffix = "?page_size=500"
        if page_token:
            suffix += f"&page_token={page_token}"

        data = request_json(access_token, "GET", f"/docx/v1/documents/{doc_token}/blocks{suffix}")
        payload = data.get("data", {})
        page_items = payload.get("items") or payload.get("blocks") or []
        blocks.extend(page_items)

        if not payload.get("has_more"):
            break
        page_token = payload.get("page_token")
        if not page_token:
            break

    return blocks


def extract_plain_text(value) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return "".join(extract_plain_text(item) for item in value)
    if isinstance(value, dict):
        return "".join(extract_plain_text(item) for item in value.values())
    return ""


def summarize_block(block: dict, max_text_length: int) -> dict:
    block_id = block.get("block_id") or block.get("id")
    parent_id = block.get("parent_id") or block.get("parent_block_id")
    children = block.get("children") or block.get("child_ids") or []
    text = extract_plain_text(block).replace("\r", " ").replace("\n", " ").strip()
    if len(text) > max_text_length:
        text = text[: max_text_length - 3] + "..."

    return {
        "block_id": block_id,
        "parent_id": parent_id,
        "block_type": block.get("block_type"),
        "children_count": len(children),
        "text": text,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="List blocks from a Feishu document.")
    parser.add_argument("--document-id", required=True, help="Feishu doc token.")
    parser.add_argument("--access-token", help="Optional Feishu user_access_token.")
    parser.add_argument("--contains-text", help="Filter to blocks whose extracted text contains this string.")
    parser.add_argument("--max-text-length", type=int, default=120, help="Maximum summary text length per block.")
    args = parser.parse_args()

    access_token = load_access_token(args.access_token)
    blocks = get_document_blocks(access_token, args.document_id)
    summaries = [summarize_block(block, args.max_text_length) for block in blocks]

    if args.contains_text:
        summaries = [item for item in summaries if args.contains_text in (item.get("text") or "")]

    print(
        json.dumps(
            {
                "ok": True,
                "document_id": args.document_id,
                "count": len(summaries),
                "blocks": summaries,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
