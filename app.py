import math
from pathlib import Path
from decimal import Decimal
import asyncio
import json
import os
from dataclasses import dataclass, asdict, field
from datetime import datetime
from enum import Enum
from typing import List, Optional

import aiohttp
from aiohttp.client_exceptions import ClientConnectorError
from pytablewriter import MarkdownTableWriter
from jina import Client


health_check_failed = False


class Status(str, Enum):
    AVAILABLE = 'AVAILABLE'
    UNAVAILABLE = 'UNAVAILABLE'


@dataclass
class HealthCheckEvent:
    ctime: datetime
    status: Status


@dataclass
class Project:
    repo: str
    name: str
    host: str
    status: Status = Status.AVAILABLE
    ctime: datetime = datetime.now()  # first health check time
    last_utime: datetime = datetime.now()  # last health check time
    last_dtime: Optional[datetime] = None  # last down time
    history: List[HealthCheckEvent] = field(default_factory=lambda: [])


class ProjectJSONEncoder(json.JSONEncoder):
    def default(self, obj):
        if not isinstance(obj, Project):
            return super().default(obj)

        proj = asdict(obj)
        proj['last_utime'] = proj['last_utime'] and proj['last_utime'].isoformat()
        proj['ctime'] = proj['ctime'] and proj['ctime'].isoformat()
        proj['last_dtime'] = proj['last_dtime'] and proj['last_dtime'].isoformat()
        proj['history'] = [
            self._healthcheck_event_default(his) for his in proj['history']
        ]
        return proj

    def _healthcheck_event_default(self, obj):
        obj['ctime'] = obj['ctime'].isoformat()
        return obj


class ProjectJSONDecoder(json.JSONDecoder):
    def decode(self, s):
        objs = super().decode(s)
        projects = []
        for obj in objs:
            obj['status'] = Status(obj['status'])
            obj['ctime'] = datetime.fromisoformat(obj['ctime'])
            obj['last_utime'] = datetime.fromisoformat(obj['last_utime'])
            if isinstance(obj['last_dtime'], str):
                obj['last_dtime'] = datetime.fromisoformat(obj['last_dtime'])
            obj['history'] = obj['history'] and [
                self._healthcheck_event_decode(his) for his in obj['history']
            ]
            projects.append(Project(**obj))
        return projects

    def _healthcheck_event_decode(self, obj):
        obj['ctime'] = datetime.fromisoformat(obj['ctime'])
        obj['status'] = Status(obj['status'])
        return HealthCheckEvent(**obj)



header = {
    'Authorization': os.environ.get('DOCSQA_ADMIN_TOKEN'),
    'Content-Type': 'application/json',
}


async def get_project_list():
    async with aiohttp.ClientSession() as session:
        async with session.get('https://apidocsqa.jina.ai/projects', headers=header) as resp:
            json_body = await resp.json()
            return json_body


async def _health_check(project, session):
    header = {'Content-Type': 'application/json', 'accept': 'application/json'}
    payload = json.dumps({'data': [{'text': f'how to debug {project.repo}'}]})
    url = os.path.join(project.host, 'search')
    client = Client(host=project.host)
    success = await client.client._dry_run()
    project.last_utime = datetime.now()
    project.status = Status.AVAILABLE if success else Status.UNAVAILABLE
    project.last_dtime = datetime.now() if not success else None
    project.history.append(HealthCheckEvent(ctime=datetime.now(), status=project.status))
    print(f'{project.host} status: {project.status}')
    if not success:
        global health_check_failed
        health_check_failed = True
    return project


async def health_check(projects_list):
    tasks = []
    custom_headers = {
        'User-Agent': 'aiohttp client 0.17'
    }

    results = []
    async with aiohttp.ClientSession(headers=custom_headers) as session:
        # For each project put it into a task queue
        for project in projects_list:
            # send POST request to /search endpoint for each project
            result = await _health_check(project, session)
            results.append(result)
            await asyncio.sleep(1)
        return results


def calculate_uptime(project):
    from datetime import timedelta
    up_time = timedelta()
    cur_time = project.ctime
    for hc_event in project.history:
        if hc_event.ctime >= project.ctime:
            if hc_event.status is Status.AVAILABLE:
                up_time += hc_event.ctime - cur_time
            cur_time = hc_event.ctime
    total_time = cur_time - project.ctime
    return Decimal(up_time.total_seconds()) * 100 / Decimal(total_time.total_seconds()) if total_time.seconds > 0 else 0


def write_to_markdown(projects):
    _matrix = []
    for p in projects:
        if p is None:
            continue
        _matrix.append([
            p.repo,
            '✅' if p.status == Status.AVAILABLE else '⛔️',
            p.last_utime.strftime('%m/%d/%Y, %H:%M:%S'),
            p.last_dtime.strftime('%m/%d/%Y, %H:%M:%S') if p.last_dtime is not None else 'None',
            f'{calculate_uptime(p):.3f} (since {p.ctime.strftime("%m/%d/%Y, %H:%M:%S")})'
        ])

    table_header = 'DocsQA Status'
    # collect the data and write into a table
    writer = MarkdownTableWriter(
        table_name=table_header,
        headers=['project', 'Current Status', 'Last Check', 'Last Downtime', '% Uptime'],
        value_matrix=_matrix,
        flavor='github'
    )
    # output the table into output.md
    with open('output.md', 'w') as f:
        output = writer.dumps()
        output = output.replace(f'{table_header}', f'{table_header}\n')
        f.write(output)


def entrypoint():
    data_path = os.environ.get('DATA_PATH', 'data.json')
    if Path(data_path).exists():
        with open(data_path, 'r') as f:
            stored_projects = {
                proj.repo: proj for proj in json.load(f, cls=ProjectJSONDecoder)
            }
            print(stored_projects)
    else:
        stored_projects = {}

    # GET request to retrieve the project list
    loop = asyncio.get_event_loop()
    projects = loop.run_until_complete(get_project_list())
    projects_list = []
    for p in projects:
        if p is None:
            print(f'skip {project}')
            continue
        if p['status'] != 'PUBLISHED':
            print(f'{p["name"]} is not published but is {p["status"]}')
            continue
        if p['repo'] in stored_projects:
            project = stored_projects[p['repo']]
        else:
            project = Project(repo=p['repo'], name=p['name'], host=f'https://{p["name"]}.docsqa.jina.ai')
        if project.host is None:
            print(f'skip {project}')
            continue
        projects_list.append(project)
    total_future = asyncio.ensure_future(health_check(projects_list))

    result = loop.run_until_complete(total_future)
    write_to_markdown(result)

    with open(data_path, 'w') as f:
        json.dump(result, f, cls=ProjectJSONEncoder)

    global health_check_failed
    print(health_check_failed)




if __name__ == '__main__':
    entrypoint()
