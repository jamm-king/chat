from uuid import uuid4

import pytest
from sqlalchemy import select

from app.db import NotionResource
from app.references import extract_references
from test_notion_pages import BASE, CONNECTION_ID, HEADERS, PAGE_ID, USER_ID, page_app

RESOURCES = f"/integrations/notion/connections/{CONNECTION_ID}/resources"
CHILD_ID, DATABASE_ID, GRANDCHILD_ID = str(uuid4()), str(uuid4()), str(uuid4())
SOURCE = f'''# 여행 계획
<page url="https://app.notion.com/p/{CHILD_ID.replace('-', '')}">맛집 &amp; 카페</page>
<database url="https://app.notion.com/p/{DATABASE_ID.replace('-', '')}" inline="true">일정</database>
<video src="https://www.youtube.com/watch?v=example"></video>
<empty-block/>
본문과 체크리스트
- [x] 준비 완료
'''


def register(client, page_id=PAGE_ID, parent_id=None, user_id=USER_ID):
    body = {"page_id": page_id}
    if parent_id:
        body["parent_resource_id"] = parent_id
    return client.post(RESOURCES, headers=HEADERS, params={"userId": user_id}, json=body)


def read(client, resource_id, user_id=USER_ID):
    return client.get(f"/integrations/notion/resources/{resource_id}",
                      headers=HEADERS, params={"userId": user_id})


def test_register_preserves_source_and_does_not_follow_references(page_app):
    client, state, calls = page_app
    state["markdown"]["markdown"] = SOURCE
    response = register(client)
    assert response.status_code == 201
    data = response.json()
    assert data["raw_content"] == SOURCE and data["content"] == SOURCE
    assert data["parent_resource_id"] is None
    assert data["content_status"] == "complete"
    assert [item["kind"] for item in data["references"]] == ["page", "database", "video"]
    assert data["references"][0]["page_id"] == CHILD_ID
    assert data["references"][0]["can_register"] is True
    assert data["references"][0]["title"] == "맛집 & 카페"
    assert data["references"][1]["can_register"] is False
    assert data["references"][1]["page_id"] is None
    assert len(calls) == 2
    assert all(PAGE_ID in str(call.url) for call in calls)
    saved = read(client, data["id"])
    assert saved.status_code == 200 and saved.json()["references"] == data["references"]
    listing = client.get(RESOURCES, headers=HEADERS, params={"userId": USER_ID})
    assert listing.status_code == 200
    assert listing.json()[0]["id"] == data["id"]
    assert "raw_content" not in listing.json()[0]
    assert len(calls) == 2
    with client.app.state.sessions() as session:
        row = session.scalar(select(NotionResource))
        assert row.raw_content == SOURCE and row.page_id == PAGE_ID


def test_user_explicitly_registers_one_reference_as_a_child(page_app):
    client, state, calls = page_app
    state["markdown"]["markdown"] = SOURCE
    parent = register(client).json()
    state["page"]["id"] = CHILD_ID
    state["markdown"]["id"] = CHILD_ID
    state["markdown"]["markdown"] = f'<page url="https://www.notion.so/{GRANDCHILD_ID}">세부 자료</page>'
    child = register(client, CHILD_ID, parent["id"])
    assert child.status_code == 201
    assert child.json()["parent_resource_id"] == parent["id"]
    assert child.json()["page_id"] == CHILD_ID
    assert child.json()["references"][0]["page_id"] == GRANDCHILD_ID
    assert len(calls) == 4
    assert not any(GRANDCHILD_ID in str(call.url) for call in calls)
    assert read(client, parent["id"]).json()["content_status"] == "complete"


@pytest.mark.parametrize("target", [DATABASE_ID, GRANDCHILD_ID])
def test_database_or_unreferenced_page_cannot_be_registered_as_child(page_app, target):
    client, state, calls = page_app
    state["markdown"]["markdown"] = SOURCE
    parent = register(client).json()
    assert register(client, target, parent["id"]).status_code == 400
    assert len(calls) == 2


def test_failed_child_fetch_does_not_change_parent(page_app):
    client, state, calls = page_app
    state["markdown"]["markdown"] = SOURCE
    parent = register(client).json()
    state["status"] = 404
    assert register(client, CHILD_ID, parent["id"]).status_code == 404
    assert read(client, parent["id"]).json() == parent
    with client.app.state.sessions() as session:
        assert len(session.scalars(select(NotionResource)).all()) == 1
    assert len(calls) == 3


def test_duplicate_page_registration_is_rejected_without_fetch(page_app):
    client, _, calls = page_app
    assert register(client).status_code == 201
    assert register(client).status_code == 409
    assert len(calls) == 2


def test_resources_require_auth_and_ownership(page_app):
    client, _, calls = page_app
    resource = register(client).json()
    assert read(client, resource["id"], str(uuid4())).status_code == 404
    assert register(client, user_id=str(uuid4())).status_code == 404
    assert client.get(RESOURCES, headers=HEADERS, params={"userId": str(uuid4())}).status_code == 404
    assert client.post(RESOURCES, params={"userId": USER_ID}, json={"page_id": PAGE_ID}).status_code == 401
    assert client.get(f'/integrations/notion/resources/{resource["id"]}', params={"userId": USER_ID}).status_code == 401
    assert len(calls) == 2


def test_missing_parent_rejected_before_fetch(page_app):
    client, _, calls = page_app
    assert register(client, CHILD_ID, str(uuid4())).status_code == 404
    assert not calls


def test_partial_content_is_saved_as_partial(page_app):
    client, state, _ = page_app
    state["markdown"]["truncated"] = True
    state["markdown"]["unknown_block_ids"] = [CHILD_ID]
    response = register(client)
    assert response.status_code == 201
    assert response.json()["content_status"] == "partial"
    assert read(client, response.json()["id"]).json()["unknown_block_ids"] == [CHILD_ID]


def test_reference_extraction_ignores_code_and_non_notion_page_links():
    source = f'''```html
<page url="https://www.notion.so/{GRANDCHILD_ID}">example</page>
```
`<page url="https://www.notion.so/{GRANDCHILD_ID}">example</page>`
<page url="https://www.notion.so/{CHILD_ID}">first</page>
<page url="https://app.notion.com/p/{CHILD_ID.replace('-', '')}">duplicate</page>
<page url="https://notion.so.example.com/{GRANDCHILD_ID}">external</page>
<database url="https://www.notion.so/{DATABASE_ID}"/>
<video src="javascript:alert(1)"></video>
'''
    references = extract_references(source)
    assert len(references) == 3
    assert str(references[0].page_id) == CHILD_ID and references[0].title == "first"
    assert references[1].can_register is False
    assert references[2].kind == "database" and not references[2].can_register


def test_preview_exposes_references_without_marking_page_partial(page_app):
    client, state, calls = page_app
    state["markdown"]["markdown"] = SOURCE
    response = client.get(f"{BASE}/{PAGE_ID}", headers=HEADERS, params={"userId": USER_ID})
    assert response.status_code == 200
    assert response.json()["content_status"] == "complete"
    assert len(response.json()["references"]) == 3
    assert len(calls) == 2
