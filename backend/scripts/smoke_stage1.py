from __future__ import annotations

import json
import os
import time
import uuid
from typing import Any

import httpx


def require(response: httpx.Response, expected: int = 200) -> dict[str, Any]:
    if response.status_code != expected:
        raise RuntimeError(
            f"{response.request.method} {response.request.url} -> "
            f"{response.status_code}: {response.text[:500]}"
        )
    return response.json()


def key(label: str) -> str:
    return f"stage1-smoke-{label}-{uuid.uuid4().hex}"


def main() -> None:
    base_url = os.environ.get("STAGE1_SMOKE_BASE_URL", "http://127.0.0.1:3100").rstrip("/")
    invite_code = os.environ.get("STAGE1_SMOKE_INVITE")
    if not invite_code:
        raise SystemExit("请通过 STAGE1_SMOKE_INVITE 提供测试邀请码。")

    with httpx.Client(base_url=base_url, timeout=20, follow_redirects=False) as client:
        require(client.post("/api/v1/auth/invite-session", json={"invite_code": invite_code}))
        require(client.get("/api/v1/me"))

        course = require(
            client.post(
                "/api/v1/courses",
                headers={"Idempotency-Key": key("course")},
                json={"temporary_title": None},
            ),
            201,
        )
        course_id = course["id"]

        manifest = {
            "items": [
                {
                    "client_item_id": "smoke-paste-1",
                    "declared_type": "text",
                    "text": "第一章 函数基础\n\n函数描述输入与输出之间的确定关系。",
                    "display_name": "函数基础课堂讲义.txt",
                }
            ]
        }
        batch = require(
            client.post(
                f"/api/v1/courses/{course_id}/material-batches",
                headers={"Idempotency-Key": key("upload")},
                data={"manifest": json.dumps(manifest, ensure_ascii=False)},
            ),
            202,
        )
        material_id = batch["materials"][0]["id"]

        deadline = time.monotonic() + 25
        material: dict[str, Any] | None = None
        candidate: dict[str, Any] | None = None
        while time.monotonic() < deadline:
            material = require(client.get(f"/api/v1/materials/{material_id}"))
            candidate_response = client.get(f"/api/v1/courses/{course_id}/title-candidate")
            if candidate_response.status_code == 200:
                candidate = candidate_response.json()
            elif candidate_response.status_code != 404:
                require(candidate_response)
            if material["status"] == "usable" and candidate:
                break
            if material["status"] == "failed":
                raise RuntimeError(
                    f"材料解析失败：{material['error_code']} {material['error_message']}"
                )
            time.sleep(0.5)
        if material is None or material["status"] != "usable" or not candidate:
            raise RuntimeError("等待材料解析或课程命名超时。")

        version_id = material["active_parse_version_id"]
        version = require(client.get(f"/api/v1/materials/{material_id}/versions/{version_id}"))
        if not version["segments"]:
            raise RuntimeError("解析版本没有可追溯片段。")

        confirmed = require(
            client.post(
                f"/api/v1/courses/{course_id}/title-confirmations",
                headers={"Idempotency-Key": key("title")},
                json={
                    "candidate_id": candidate["candidates"][0]["id"],
                    "edited_title": None,
                    "expected_course_version": course["version"],
                },
            )
        )
        snapshot = require(
            client.post(
                f"/api/v1/courses/{course_id}/context-snapshots",
                headers={"Idempotency-Key": key("snapshot")},
                json={
                    "task_type": "stage1_validation",
                    "selected_materials": [
                        {
                            "id": material_id,
                            "parse_version": version_id,
                            "selected_order": 0,
                        }
                    ],
                },
            ),
            201,
        )
        if snapshot["status"] != "ready" or snapshot["coverage_status"] != "complete":
            raise RuntimeError(
                f"上下文快照未就绪：{snapshot['status']}/{snapshot['coverage_status']}"
            )
        source_id = snapshot["source_ref_ids"][0]
        source = require(client.get(f"/api/v1/source-refs/{source_id}"))
        original = client.get(f"/api/v1/materials/{material_id}/original")
        if original.status_code != 200 or not original.content:
            raise RuntimeError("原件回看接口不可用。")

        print("第 1 阶段完整联调通过")
        print(f"课程：{confirmed['title']} ({course_id})")
        print(f"快照：{snapshot['id']} / {snapshot['segment_count']} 个来源片段")
        print(f"预览：{base_url}/contexts/{snapshot['id']}")
        print(f"来源：{base_url}/sources/{source['id']}")


if __name__ == "__main__":
    main()
