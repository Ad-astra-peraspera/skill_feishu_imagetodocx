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


def create_doc(access_token: str, title: str) -> str:
    data = request_json(access_token, "POST", "/docx/v1/documents", {"title": title})
    doc_token = data.get("data", {}).get("document", {}).get("document_id")
    if not doc_token:
        raise RuntimeError(f"create document returned no document_id: {json.dumps(data, ensure_ascii=False)}")
    return doc_token


def create_image_block(access_token: str, doc_token: str, index: int) -> str:
    data = request_json(
        access_token,
        "POST",
        f"/docx/v1/documents/{doc_token}/blocks/{doc_token}/children",
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
    parser = argparse.ArgumentParser(description="Create a Feishu doc and insert an image.")
    parser.add_argument("--title", default="Codex Feishu Image Test", help="Title for the new docx file.")
    parser.add_argument("--image", required=True, help="Path to the local image file.")
    parser.add_argument("--index", type=int, default=0, help="Insert index under the root block.")
    parser.add_argument("--access-token", help="Optional Feishu user_access_token.")
    args = parser.parse_args()

    image_path = Path(args.image).expanduser().resolve()
    if not image_path.exists():
        raise SystemExit(f"Image not found: {image_path}")

    access_token = load_access_token(args.access_token)
    doc_token = create_doc(access_token, args.title)
    image_block_id = create_image_block(access_token, doc_token, args.index)
    file_token = upload_media_to_image_block(access_token, doc_token, image_block_id, image_path)
    replace_image(access_token, doc_token, image_block_id, file_token)
    doc_url = lookup_doc_url(access_token, doc_token)

    result = {
        "ok": True,
        "title": args.title,
        "image_path": str(image_path),
        "document_id": doc_token,
        "document_url": doc_url,
        "image_block_id": image_block_id,
        "file_token": file_token,
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
