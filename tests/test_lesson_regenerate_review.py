from sqlalchemy import select

from server.database import Job, Lesson
from tests.test_platform import headers, platform, seed_lesson, start  # noqa: F401


def test_regenerate_requeues_the_original_inputs_for_a_new_lesson(platform):
    client, factory, ids = platform
    lesson_id, _ = seed_lesson(factory, ids)
    assert client.post(f"/api/lessons/{lesson_id}/regenerate", headers=headers("alice")).status_code == 409
    payload = {"lesson_id": lesson_id, "source_ids": ["s1"], "goal": "Understand fixture lists"}
    with factory.begin() as db:
        db.add(Job(owner_id=ids["alice"], dedup_key="original-fixture", kind="quick_lesson", payload=payload, state="completed"))
    assert client.post(f"/api/lessons/{lesson_id}/regenerate", headers=headers("bob")).status_code in {403, 404}
    response = client.post(f"/api/lessons/{lesson_id}/regenerate", headers=headers("alice"))
    assert response.status_code == 202, response.text
    copy = response.json()
    with factory.begin() as db:
        job = db.get(Job, copy["job_id"])
        assert job.kind == "quick_lesson" and job.payload == {**payload, "lesson_id": copy["id"]}
        lessons = db.scalars(select(Lesson).where(Lesson.owner_id == ids["alice"])).all()
        assert {x.title for x in lessons} == {"Fixture Python lesson"} and len(lessons) == 2


def test_review_replays_reached_parts_without_moving_the_session(platform):
    client, factory, ids = platform
    _, curriculum = seed_lesson(factory, ids)
    session = start(client, curriculum)
    replay = client.get(f"/api/sessions/{session['id']}/review/o0", headers=headers("alice"))
    assert replay.status_code == 200 and replay.json()["clips"]
    assert client.get(f"/api/sessions/{session['id']}/review/o1", headers=headers("alice")).status_code == 404
    assert client.get(f"/api/sessions/{session['id']}/review/o0", headers=headers("bob")).status_code in {403, 404}
    after = client.get(f"/api/sessions/{session['id']}", headers=headers("alice")).json()
    assert (after["objective_id"], after["route_revision"]) == (session["objective_id"], session["route_revision"])
