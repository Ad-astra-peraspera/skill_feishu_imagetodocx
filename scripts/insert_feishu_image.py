#!/usr/bin/env python3
import argparse
import json
import mimetypes
import os
import sys
import urllib.error
import urllib.request
import uuid
from pathlib import Path

from feishu_token_utils import load_dotenv, resolve_user_access_token


OPENAPI_BASE = "https://open.feishu.cn/open-apis"


load_dotenv()


def load_access_token(explicit_token: str | None) -> str:
    return resolve_user_access_token(explicit_token)


def request_json(access_token: str, method: str, path: str, body: dict | None = None) -> dict:
    headers = {"Authorization": f"Bearer {access_token}"}
    payload = None
    if body is not None:
        payload = json.dumps(body, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json; charset=utf-8"

    req = urllib.request.Request(
        f"{OPENAPI_BASE}{path}",
        data=payload,
        method=method,
        headers=headers,
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


def block_id_of(block: dict) -> str | None:
    return block.get("block_id") or block.get("id")


def parent_id_of(block: dict) -> str | None:
    return block.get("parent_id") or block.get("parent_block_id")


def child_ids_of(block: dict) -> list[str]:
    children = block.get("children") or block.get("child_ids") or []
    return [str(item) for item in children]


def extract_plain_text(value) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return "".join(extract_plain_text(item) for item in value)
    if isinstance(value, dict):
        parts: list[str] = []
        for nested in value.values():
            parts.append(extract_plain_text(nested))
        return "".join(parts)
    return ""


def find_anchor_block(blocks: list[dict], anchor_block_id: str | None, anchor_text: str | None) -> dict | None:
    if anchor_block_id:
        for block in blocks:
            if block_id_of(block) == anchor_block_id:
                return block
        raise RuntimeError(f"Anchor block not found: {anchor_block_id}")

    if anchor_text:
        for block in blocks:
            if anchor_text in extract_plain_text(block):
                return block
        raise RuntimeError(f"Anchor text not found in document blocks: {anchor_text}")

    return None


def resolve_insertion_parent_and_index(
    doc_token: str,
    blocks: list[dict],
    anchor_block_id: str | None,
    anchor_text: str | None,
    index: int | None,
    position: str,
) -> tuple[str, int]:
    if anchor_block_id or anchor_text:
        anchor_block = find_anchor_block(blocks, anchor_block_id, anchor_text)
        assert anchor_block is not None

        parent_block_id = parent_id_of(anchor_block) or doc_token
        if parent_block_id == doc_token:
            sibling_ids = [
                block_id_of(block)
                for block in blocks
                if parent_id_of(block) == doc_token and block_id_of(block)
            ]
        else:
            parent_block = next((block for block in blocks if block_id_of(block) == parent_block_id), None)
            sibling_ids = child_ids_of(parent_block or {})

        current_block_id = block_id_of(anchor_block)
        if not current_block_id:
            raise RuntimeError("Anchor block is missing a block_id.")
        if current_block_id not in sibling_ids:
            raise RuntimeError("Anchor block could not be located among its parent's children.")

        current_index = sibling_ids.index(current_block_id)
        insert_index = current_index if position == "before" else current_index + 1
        return parent_block_id, insert_index

    return doc_token, (index if index is not None else 0)


def create_image_block(access_token: str, doc_token: str, parent_block_id: str, index: int) -> str:
    data = request_json(
        access_token,
        "POST",
        f"/docx/v1/documents/{doc_token}/blocks/{parent_block_id}/children",
        {
            "index": index,
            "children": [
                {
                    "block_type": 27,
                    "image": {},
                }
            ],
        },
    )
    children = data.get("data", {}).get("children", [])
    if not children or children[0].get("block_type") != 27:
        raise RuntimeError(f"image block create mismatch: {json.dumps(data, ensure_ascii=False)}")
    return children[0]["block_id"]


def upload_media_to_image_block(access_token: str, doc_token: str, image_block_id: str, image_path: Path) -> str:
    boundary = f"----CodexBoundary{uuid.uuid4().hex}"
    filename = image_path.name
    mime = mimetypes.guess_type(str(image_path))[0] or "application/octet-stream"
    file_bytes = image_path.read_bytes()

    parts: list[bytes] = []

    def add_field(name: str, value: str) -> None:
        parts.append(f"--{boundary}\r\n".encode("utf-8"))
        parts.append(f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode("utf-8"))
        parts.append(value.encode("utf-8"))
        parts.append(b"\r\n")

    add_field("file_name", filename)
    add_field("parent_type", "docx_image")
    add_field("parent_node", image_block_id)
    add_field("size", str(len(file_bytes)))
    add_field("extra", json.dumps({"drive_route_token": doc_token}, ensure_ascii=False))

    parts.append(f"--{boundary}\r\n".encode("utf-8"))
    parts.append(
        (
            f'Content-Disposition: form-data; name="file"; filename="{filename}"\r\n'
            f"Content-Type: {mime}\r\n\r\n"
        ).encode("utf-8")
    )
    parts.append(file_bytes)
    parts.append(b"\r\n")
    parts.append(f"--{boundary}--\r\n".encode("utf-8"))

    body = b"".join(parts)
    req = urllib.request.Request(
        f"{OPENAPI_BASE}/drive/v1/medias/upload_all",
        data=body,
        method="POST",
        headers={
            "Authorization": f"Bearer {access_token}",
            "Content-Type": f"multipart/form-data; boundary={boundary}",
            "Content-Length": str(len(body)),
        },
    )

    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "ignore")
        raise RuntimeError(f"upload_all failed: {exc.code} {detail}") from exc

    file_token = data.get("data", {}).get("file_token")
    if not file_token:
        raise RuntimeError(f"upload_all returned no file_token: {json.dumps(data, ensure_ascii=False)}")
    return file_token


def replace_image(access_token: str, doc_token: str, image_block_id: str, file_token: str) -> None:
    data = request_json(
        access_token,
        "PATCH",
        f"/docx/v1/documents/{doc_token}/blocks/{image_block_id}",
        {
            "replace_image": {
                "token": file_token,
            }
        },
    )
    token = data.get("data", {}).get("block", {}).get("image", {}).get("token")
    if token != file_token:
        raise RuntimeError(f"replace_image mismatch: {json.dumps(data, ensure_ascii=False)}")


def lookup_doc_url(access_token: str, doc_token: str) -> str:
    data = request_json(access_token, "GET", f"/drive/v1/files?page_size=200")
    for item in data.get("data", {}).get("files", []):
        if item.get("token") == doc_token:
            return item.get("url", "")
    return ""


def main() -> int:
    parser = argparse.ArgumentParser(description="Insert a local image into an existing Feishu doc.")
    parser.add_argument("--document-id", required=True, help="Feishu doc token.")
    parser.add_argument("--image", required=True, help="Path to the local image file.")
    parser.add_argument("--index", type=int, help="Insert index under the root block when no anchor is provided.")
    parser.add_argument("--anchor-block-id", help="Insert relative to an existing block ID.")
    parser.add_argument("--anchor-text", help="Insert relative to the first block containing this text.")
    parser.add_argument(
        "--position",
        choices=["before", "after"],
        default="after",
        help="When using an anchor, insert before or after the anchor block.",
    )
    parser.add_argument("--access-token", help="Optional Feishu user_access_token.")
    args = parser.parse_args()

    image_path = Path(args.image).expanduser().resolve()
    if not image_path.exists():
        raise SystemExit(f"Image not found: {image_path}")

    if args.anchor_block_id and args.anchor_text:
        raise SystemExit("Use only one of --anchor-block-id or --anchor-text.")

    access_token = load_access_token(args.access_token)
    blocks = get_document_blocks(access_token, args.document_id)
    parent_block_id, insert_index = resolve_insertion_parent_and_index(
        args.document_id,
        blocks,
        args.anchor_block_id,
        args.anchor_text,
        args.index,
        args.position,
    )

    image_block_id = create_image_block(access_token, args.document_id, parent_block_id, insert_index)
    file_token = upload_media_to_image_block(access_token, args.document_id, image_block_id, image_path)
    replace_image(access_token, args.document_id, image_block_id, file_token)
    doc_url = lookup_doc_url(access_token, args.document_id)

    result = {
        "ok": True,
        "image_path": str(image_path),
        "document_id": args.document_id,
        "document_url": doc_url,
        "parent_block_id": parent_block_id,
        "insert_index": insert_index,
        "image_block_id": image_block_id,
        "file_token": file_token,
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
