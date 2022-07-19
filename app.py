import asyncio
import json
import os
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import List, Optional

import aiohttp
from aiohttp.client_exceptions import ClientConnectorError
from pytablewriter import MarkdownTableWriter


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
    last_utime: datetime = datetime.now()  # last health check time
    last_dtime: Optional[datetime] = None  # last down time
    history: Optional[List[HealthCheckEvent]] = None


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
    try:
        async with session.post(url, data=payload, headers=header) as resp:
            project.last_utime = datetime.now()
            if resp.status != 200:
                project.status = Status.UNAVAILABLE
                project.last_dtime = datetime.now()
                print(f'{project.host} response status error: {resp.status}')
                return project
            # check the response has matches
            json_body = await resp.json()
            data = json_body.get('data', None)
            if data is None:
                project.status = Status.UNAVAILABLE
                project.last_dtime = datetime.now()
                print(f'{project.host} empty response data: {json_body}')
                return project
            matches = data[0].get('matches', None)
            if matches is None:
                print(f'{project.host} empty matches: {json_body}')
            project.status = Status.AVAILABLE if matches else Status.UNAVAILABLE
            # TODO: add the status to the history
            # project.history.append(HealthCheckEvent(ctime=project.last_time, project.status))
            return project
    except ClientConnectorError as e:
        print(f'failed to connect to {project.host}, {e}')
        project.status = Status.UNAVAILABLE
        project.last_dtime = datetime.now()
    finally:
        project.last_utime = datetime.now()
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


def write_to_markdown(projects):
    _matrix = []
    for p in projects:
        if p is None:
            continue
        _matrix.append([
            p.repo,
            '✅' if p.status == Status.AVAILABLE else '⛔️',
            p.last_utime.isoformat(),
            p.last_dtime.isoformat() if p.last_dtime is not None else 'None'
        ])

    table_header = 'DocsQA Status'
    # collect the data and write into a table
    writer = MarkdownTableWriter(
        table_name=table_header,
        headers=['project', 'Current Status', 'Last Check', 'Last Downtime'],
        value_matrix=_matrix,
        flavor='github'
    )
    # output the table into output.md
    with open('output.md', 'w') as f:
        output = writer.dumps()
        output = output.replace(f'{table_header}', f'{table_header}\n')
        f.write(output)


def entrypoint():
    # TODO: load the data.json()

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
        project = Project(repo=p['repo'], name=p['name'], host=f'https://{p["name"]}.docsqa.jina.ai')
        if project.host is None:
            print(f'skip {project}')
            continue
        projects_list.append(project)
    total_future = asyncio.ensure_future(health_check(projects_list))

    result = loop.run_until_complete(total_future)
    write_to_markdown(result)

    # TODO: Store the results into data.json


if __name__ == '__main__':
    entrypoint()
