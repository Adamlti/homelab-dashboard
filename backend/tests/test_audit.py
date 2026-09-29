import pytest

from app.services import audit, tasks, roadmap


def test_project_edits_are_audited_atomically_and_survive_restart(monkeypatch):
    tasks.initialize()
    roadmap.initialize()
    task = tasks.add_task('Audit fixture')
    tasks.update_task(task['id'], {'completed': True})
    tasks.remove_task(task['id'])
    item = roadmap.add_item({'title': 'Audit roadmap', 'description': '', 'phase': 'Next'})
    roadmap.reorder([row['id'] for row in roadmap.list_items()])
    roadmap.remove_item(item['id'])
    tasks.initialize()
    assert len(audit.list_events()) == 6
    before = tasks.list_tasks()
    def fail(*args):
        raise RuntimeError('audit write failed')
    monkeypatch.setattr(audit, 'record', fail)
    with pytest.raises(RuntimeError):
        tasks.add_task('Must roll back')
    assert tasks.list_tasks() == before


def test_edit_history_is_bounded():
    tasks.initialize()
    with tasks.database() as connection, connection:
        for index in range(510):
            audit.record(connection, 'Tasks', f'Edit {index}')
    rows = audit.list_events()
    assert len(rows) == 500
    assert rows[0]['detail'] == 'Edit 10'
    assert rows[-1]['detail'] == 'Edit 509'
