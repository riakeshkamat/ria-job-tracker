import asyncio
import json

import httpx
import pytest
from fastapi.testclient import TestClient

from tracker.app import create_app
from tracker.catalog import parse_directory
from tracker.collector import Collector
from tracker.config import Config
from tracker.db import Database
from tracker.domain import canonical_url
from tracker.sources import Fetcher, aggregate_job, board_from_url, parse_community_json, validate_source


@pytest.fixture
def setup(tmp_path):
    config=Config(data_dir=tmp_path,secret='x'*40,password='',production=False,schedule=False)
    config.prepare()
    return config,Database(tmp_path/'coverage.sqlite3')


def test_directories_validate_entire_snapshot_before_import(setup):
    config,db=setup
    data={'providers':{p:{'live':[[f'company{i}',1] for i in range(300)]}
                       for p in ['ashby','greenhouse','lever','recruitee']}}
    rows=parse_directory(json.dumps(data),'open-ats')
    db.add_sources(rows,'open-ats')
    assert db.source_summary()['enabled']==1200
    with db.connect() as c:c.execute("UPDATE sources SET enabled=0 WHERE slug='company0'")
    db.add_sources(rows,'open-ats')
    assert db.source_summary()['enabled']==1196
    data['providers']['ashby']['live'][-1]=['../../localhost',1]
    with pytest.raises(ValueError):parse_directory(json.dumps(data),'open-ats')
    assert db.source_summary()['total']==1200


def test_directory_and_newly_discovered_board_join_same_run(setup,monkeypatch):
    config,db=setup
    db.add_source('directory','open-ats','Directory')
    async def collect(self,source):
        if source['provider']=='directory':return [],[('ashby','acme','Acme')]
        return [dict(external_id='1',title='Software Engineer I',company='Acme',location='New York',
                     country='US',description='Visa sponsorship is available.',
                     apply_url='https://jobs.ashbyhq.com/acme/1')],[]
    monkeypatch.setattr(Fetcher,'collect',collect)
    asyncio.run(Collector(db,config).run())
    run=db.runs()[0]
    assert run['status']=='success' and run['success_count']==2
    assert run['found_count']==1  # directory entries are not job postings
    assert db.jobs()['jobs'][0]['sponsorship']=='supported'


def test_failed_directory_keeps_existing_feeds_and_no_closures(setup,monkeypatch):
    config,db=setup
    db.add_source('directory','open-ats','Directory');db.add_source('ashby','acme','Acme')
    async def collect(self,source):
        if source['provider']=='directory':raise ValueError('Malformed directory')
        return [],[]
    monkeypatch.setattr(Fetcher,'collect',collect)
    asyncio.run(Collector(db,config).run())
    assert db.runs()[0]['status']=='partial'
    assert db.runs()[0]['success_count']==1
    assert db.source_summary()['enabled']==2


def test_source_pages_search_and_health_counts_are_global(setup):
    config,db=setup
    db.add_sources([('ashby',f'company{i}',f'Company {i}') for i in range(205)],'test')
    for s in db.sources()[:2]:db.source_failed(s['id'],None,'HTTP 404')
    app=create_app(config,db)
    with TestClient(app) as c:
        first=c.get('/api/sources?search=company&limit=100').json()
        second=c.get('/api/sources?search=company&limit=100&offset=100').json()
        assert first['total']==second['total']==205
        assert len(first['sources'])==len(second['sources'])==100
        assert not {s['id'] for s in first['sources']} & {s['id'] for s in second['sources']}
        failed=c.get('/api/sources?health=failed').json()
        assert failed['total']==failed['summary']['failed']==2
        assert c.get('/api/sources?limit=50000').status_code==400
        assert c.get('/api/overview').json()['coverage']['failed']==2


def test_community_feeds_keep_employer_links_not_apply_service():
    data={'updatedAt':'2026-10-17','jobs':[dict(title='Software Engineer I',company='Acme',
          location='US',url='https://applyguy.ai/jobs/1',listingUrl='https://jobs.ashbyhq.com/acme/1')]}
    assert parse_community_json(json.dumps(data),'ApplyGuy')[0]['apply_url']=='https://jobs.ashbyhq.com/acme/1'
    data={'api_version':1,'jobs':[
        dict(track='new-grad-swe',active=True,title='Software Engineer',company_name='Acme',apply_url='https://example.com/1'),
        dict(track='internships',active=True),dict(track='new-grad-swe',active=False)]}
    assert len(parse_community_json(json.dumps(data),'Ricsign'))==1
    for slug in ['owner/repo/../data.json','owner/repo?x=1','owner/repo//data.json']:
        with pytest.raises(ValueError):validate_source('github',slug)
    validate_source('github','owner/repo/data/v1/jobs.json')


def test_recruitee_multilocation_and_two_snapshot_closure(setup):
    config,db=setup
    db.add_source('recruitee','acme','Acme');source=db.sources()[0]
    payload={'offers':[dict(id=1,title='Junior Software Engineer',locations=[dict(city='London',country='UK',country_code='GB'),
           dict(city='New York',country='United States',country_code='US')],
           description='<p>Visa sponsorship is available.</p>',requirements='0-2 years of experience.',
           careers_url='https://acme.recruitee.com/o/engineer',careers_apply_url='https://acme.recruitee.com/o/engineer/c/new')]}
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda _:httpx.Response(200,json=payload))) as c:
            return (await Fetcher(c).collect(source))[0]
    jobs=asyncio.run(run());db.ingest(source,jobs,None,config.start_date)
    assert db.jobs()['jobs'][0]['sponsorship']=='supported'
    assert jobs[0]['country']=='US'
    assert canonical_url(jobs[0]['apply_url'])=='https://acme.recruitee.com/o/engineer'
    assert board_from_url(jobs[0]['apply_url'])==('recruitee','acme')
    db.ingest(source,[],None,config.start_date);assert db.jobs()['total']==1
    db.ingest(source,[],None,config.start_date);assert db.jobs('closed')['total']==1


def test_jobicy_cursor_traversal_and_loop_rejection(monkeypatch):
    async def no_pace(self,url):pass
    monkeypatch.setattr(Fetcher,'pace',no_pace)
    item=dict(id=1,jobTitle='Software Engineer I',companyName='Acme',url='https://jobicy.com/jobs/1')
    def handler(request):
        cursor=request.url.params.get('cursor')
        return httpx.Response(200,json={'jobs':[dict(item,id=2)] if cursor else [item],
                                       'nextCursor':None if cursor else 'abc/?+','hasMore':not bool(cursor)})
    async def run(transport):
        async with httpx.AsyncClient(transport=transport) as c:return await Fetcher(c).aggregate('jobicy')
    assert len(asyncio.run(run(httpx.MockTransport(handler))))==2
    with pytest.raises(ValueError,match='repeated'):
        asyncio.run(run(httpx.MockTransport(lambda _:httpx.Response(200,json={
            'jobs':[item],'nextCursor':'same','hasMore':True}))))


def test_aggregate_expiry_never_becomes_employer_closure_and_cannot_overwrite_employer(setup):
    config,db=setup
    db.add_source('himalayas','us-engineering','Himalayas');aggregate=db.sources()[0]
    item=dict(external_id='1',title='Software Engineer I',company='Acme',location='New York',country='US',
              description='Community description',apply_url='https://jobs.ashbyhq.com/acme/1')
    db.ingest(aggregate,[item],None,config.start_date)
    db.ingest(aggregate,[],None,config.start_date);db.ingest(aggregate,[],None,config.start_date)
    assert db.jobs()['jobs'][0]['availability']=='unverified'
    db.add_source('ashby','acme','Acme');employer=next(s for s in db.sources() if s['provider']=='ashby')
    db.ingest(employer,[dict(item,description='We cannot provide visa sponsorship.')],None,config.start_date)
    db.ingest(aggregate,[item],None,config.start_date)
    assert db.jobs('all')['jobs'][0]['sponsorship']=='restricted'
    assert db.jobs('all')['jobs'][0]['description']=='We cannot provide visa sponsorship.'


def test_irrelevant_jobs_not_persisted_but_manual_entries_preserved(setup):
    config,db=setup;db.add_source('ashby','acme','Acme');s=db.sources()[0]
    item=dict(external_id='1',title='Registered Nurse',company='Acme',location='NY',country='US',
              description='',apply_url='https://example.com/job/1')
    db.ingest(s,[item],None,config.start_date)
    assert db.jobs('all')['total']==0 and db.sources()[0]['job_count']==1
    db.add_source('manual','user','Manual');s=next(s for s in db.sources() if s['provider']=='manual')
    db.ingest(s,[item],None,config.start_date)
    assert db.jobs('all')['total']==1


def test_himalayas_preserves_multicountry_scope_and_attribution():
    j=dict(guid='https://himalayas.app/companies/acme/jobs/1',title='Engineer',companyName='Acme',
           applicationLink='https://example.com/apply',pubDate=1792263938,
           locationRestrictions=['Canada','United States'])
    row=aggregate_job(j,'himalayas')
    assert row['country']=='US' and row['apply_url']==j['guid'] and row['posted_at'].startswith('2026-')


def test_aggregate_experience_scope_is_read_without_promoting_visa_claims(setup):
    config,db=setup;db.add_source('remotive','us-engineering','Remotive');s=db.sources()[0]
    item=dict(external_id='1',title='Software Engineer',company='Acme',location='US',country='US',
              description='Requires 6 years of experience. Visa sponsorship is available.',apply_url='https://remotive.com/jobs/1')
    db.ingest(s,[item],None,config.start_date)
    assert db.jobs()['total']==0
    record=db.jobs('excluded')['jobs'][0]
    assert record['min_years']==6 and record['sponsorship']=='unknown'
