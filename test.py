import json
import os
from datetime import datetime
from unittest import mock

import pytest
from aioresponses import aioresponses

from app import Project, ProjectJSONEncoder, ProjectJSONDecoder, Status, HealthCheckEvent, entrypoint


def test_projects_encode_decode(tmp_path):
    projects = [
        Project(
            repo='repo',
            name='name',
            host='host',
            status=Status.UNAVAILABLE,
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