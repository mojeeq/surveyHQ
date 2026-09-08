

def test_a_renamed_dataset_downloads_under_its_new_name(client, auth_headers, stata_file):
    """The download is named after the dataset, not after what it was called first.

    The filename comes from the slug, which was set once at creation and left
    alone by every rename after it - so a dataset renamed twice still arrived
    in Excel under the name it had on the day it was uploaded, which is the one
    name nobody was looking for.
    """
    with stata_file.open("rb") as handle:
        created = client.post(
            "/api/v1/datasets/upload",
            headers=auth_headers,
            files={"file": ("original_name.dta", handle, "application/octet-stream")},
        )
    assert created.status_code in (200, 201), created.text
    payload = created.json()
    dataset_id = (payload["datasets"][0] if "datasets" in payload else payload)["id"]

    for name in ("Second name", "Third name"):
        renamed = client.patch(
            f"/api/v1/datasets/{dataset_id}", headers=auth_headers, json={"name": name}
        )
        assert renamed.status_code == 200, renamed.text

    assert client.get(f"/api/v1/datasets/{dataset_id}", headers=auth_headers).json()[
        "slug"
    ] == "third-name"

    downloaded = client.get(
        f"/api/v1/datasets/{dataset_id}/download?format=csv", headers=auth_headers
    )
    assert downloaded.status_code == 200, downloaded.text
    assert "third-name.csv" in downloaded.headers["content-disposition"]


def test_renaming_to_the_same_name_in_another_case_keeps_the_slug(
    client, auth_headers, stata_file
):
    """A rename must not collide with the dataset's own slug and gain a "-2"."""
    with stata_file.open("rb") as handle:
        created = client.post(
            "/api/v1/datasets/upload",
            headers=auth_headers,
            files={"file": ("case_test.dta", handle, "application/octet-stream")},
        )
    dataset_id = (
        created.json()["datasets"][0] if "datasets" in created.json() else created.json()
    )["id"]
    # Both renames are checked, and the second one especially: the slug this
    # asserts on is what the first rename already produced, so a second rename
    # that failed would leave the assertion passing and the case it was written
    # for untested.
    for name in ("Water survey", "Water Survey"):
        renamed = client.patch(
            f"/api/v1/datasets/{dataset_id}", headers=auth_headers, json={"name": name}
        )
        assert renamed.status_code == 200, renamed.text

    dataset = client.get(f"/api/v1/datasets/{dataset_id}", headers=auth_headers).json()
    assert dataset["name"] == "Water Survey"
    assert dataset["slug"] == "water-survey"
