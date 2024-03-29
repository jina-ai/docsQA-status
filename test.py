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
        history=[
            HealthCheckEvent(ctime=ctime+timedelta(hours=1+i), status=Status.AVAILABLE if i%2==0 else Status.UNAVAILABLE) for i in range(6)
        ]
    )
    assert calculate_uptime(project) == 50


def test_calculate_uptime_overflow():
    ctime = datetime.fromisoformat('2022-07-20T17:11:38.421227')
    utime = datetime.fromisoformat('2022-07-21T06:10:52.922811')
    project = Project(
        repo='repo',
        name='name',
        host='host',
        status=Status.UNAVAILABLE,
        ctime=ctime,
        last_utime=utime,
        history=[
            HealthCheckEvent(ctime=ctime+timedelta(hours=1+i), status=Status.AVAILABLE if i%2==0 else Status.UNAVAILABLE) for i in range(6)
        ]
    )
    result = calculate_uptime(project)
    assert result == 50

@pytest.mark.parametrize('data_path', ['test_data.json'])
def test_calculate_uptime(data_path):
    with open(data_path, 'r') as f:
            stored_projects = {
                proj.repo: proj for proj in json.load(f, cls=ProjectJSONDecoder)
            }
    for key in stored_projects.keys():
        assert calculate_uptime(stored_projects[key]) <= 100
