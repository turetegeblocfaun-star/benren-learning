from fastapi.testclient import TestClient


def test_stage1_backend_acceptance_page_is_available_in_test(client: TestClient) -> None:
    response = client.get("/api/v1/stage1-backend-check")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert "第一阶段后端验收台" in response.text
    assert "不属于正式产品前端" in response.text


def test_stage2_backend_acceptance_page_is_available_in_test(client: TestClient) -> None:
    response = client.get("/api/v1/stage2-backend-check")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert "第二阶段后端验收" in response.text
    assert "长材料 Tutor RAG" in response.text


def test_stage3_backend_acceptance_page_is_available_in_test(client: TestClient) -> None:
    response = client.get("/api/v1/stage3-backend-check")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert "第三阶段 PRD 全量后端验收" in response.text
    assert "通知投递" in response.text
    assert "扫描 PRD 全量后端合同" in response.text
    assert "不是正式前端" in response.text
