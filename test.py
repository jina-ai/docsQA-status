import json
import os
from datetime import datetime
from datetime import timedelta
from unittest import mock

import pytest
from aioresponses import aioresponses

from app import Project, ProjectJSONEncoder, ProjectJSONDecoder, Status, HealthCheckEvent, entrypoint, calculate_uptime


@pytest.mark.parametrize('dtime', ['2022-07-20T07:27:38.720774', None])
def test_projects_encode_decode(tmp_path, dtime):
    projects = [
        Project(
            repo='repo',
            name='name',
            host='host',
            status=Status.UNAVAILABLE,
            last_dtime=datetime.fromisoformat(dtime) if isinstance(dtime, str) else None,
            history=[HealthCheckEvent(ctime=datetime.now(), status=Status.AVAILABLE)]
        )
    ]

    with open(tmp_path / 'data.json', 'w') as f:
        json.dump(projects, f, cls=ProjectJSONEncoder)

    with open(tmp_path / 'data.json', 'r') as f:
        projects_decoded = json.load(f, cls=ProjectJSONDecoder)

    assert projects == projects_decoded


@pytest.fixture()
def tmp_env(tmp_path):
    with mock.patch.dict(os.environ, {'DATA_PATH': str(tmp_path / 'data.json')}):
        yield


def test_entrypoint(tmp_env):
    data_path = os.environ['DATA_PATH']

    def call_entrypoint():
        with aioresponses() as m:
            projects = [{'repo': f'repo{i}', 'name': f'name{i}', 'status': 'PUBLISHED'} for i in range(5)]
            m.get('https://apidocsqa.jina.ai/projects', status=200, payload=projects)
            for p in projects:
                m.post(f'https://{p["name"]}.docsqa.jina.ai/search', status=200,
                       payload={'data': [{'matches': 'answer'}]})
            entrypoint()

    call_entrypoint()

    with open(data_path, 'r') as f:
        data = json.load(f)
        assert all(len(proj['history']) == 1 for proj in data)

    call_entrypoint()

    with open(data_path, 'r') as f:
        data = json.load(f)
        assert all(len(proj['history']) == 2 for proj in data)
    print(os.environ['DATA_PATH'])


@pytest.mark.parametrize('days', [1, 2, 3])
def test_calculate_uptime(days):
    ctime = datetime.fromisoformat('2022-07-19T07:27:38.720774')
    utime = ctime + timedelta(days=days)
    project = Project(
        repo='repo',
        name='name',
        host='host',
        status=Status.UNAVAILABLE,
        ctime=ctime,
        last_utime=utime,
        uptime=22
    )
    assert calculate_uptime(project) == 22 * 100 / (days * 24)
