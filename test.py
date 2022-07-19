import os
import pytest
import json
from datetime import datetime
from app import Project, ProjectJSONEncoder, ProjectJSONDecoder, Status, HealthCheckEvent, entrypoint
from aioresponses import aioresponses


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


def test_entrypoint(tmp_path):
    old_data_path = os.environ.get('DATA_PATH', 'data.json')
    data_path = os.environ['DATA_PATH'] = str(tmp_path / 'data.json')

    def call_entrypoint():
        with aioresponses() as m:
            projects = [{'repo': f'repo{i}', 'name': f'name{i}', 'status': 'PUBLISHED'} for i in range(5)]
            m.get('https://apidocsqa.jina.ai/projects', status=200, payload=projects)
            for p in projects:
                m.post(f'https://{p["name"]}.docsqa.jina.ai/search', status=200, payload={'data': [{'matches': 'answer'}]})
            entrypoint()

    call_entrypoint()

    with open(data_path, 'r') as f:
        data = json.load(f)
        assert all(len(proj['history']) == 1 for proj in data)

    call_entrypoint()

    with open(data_path, 'r') as f:
        data = json.load(f)
        assert all(len(proj['history']) == 2 for proj in data)

    os.environ['DATA_PATH'] = old_data_path
