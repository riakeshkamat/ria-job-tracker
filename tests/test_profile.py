import asyncio
import json
import time

import httpx
import pytest
from fastapi.testclient import TestClient

from tracker.app import create_app
from tracker.config import Config
from tracker.db import Database
from tracker.domain import classify, relevant_role, search_location
from tracker.editions import eligibility
from tracker.plus import Plus
from tracker.profile import PROFILE, ai_instructions
from tracker.sources import Fetcher, ashby, load_seeds


@pytest.mark.parametrize('title',[
    'Business Analyst', 'Financial Analyst', 'FP&A Analyst', 'Financial Planning and Analysis Analyst',
    'Data Analyst', 'Business Intelligence Analyst', 'Strategy Analyst', 'Corporate Development Analyst',
    'Graduate Management Consultant', 'Business Operations Analyst', 'Pricing Analyst',
    'Investment Analyst', 'Credit Analyst', 'Risk Analyst', 'Junior Accountant',
    'Business Graduate Programme (Data and Analytics)', 'Finance Rotational Program 2027',
    'Graduate Analyst', 'Supply Chain Analyst', 'Revenue Analyst', 'Management Trainee',
])
def test_ria_roles_are_collected_without_skill_or_industry_matching(title):
    assert relevant_role(title)
    assert classify(title, 'Up to 3 years of experience. SQL and Python preferred.', 'Toronto, ON', 'CA')['in_scope']


@pytest.mark.parametrize('title',[
    'Software Engineer, Finance', 'Mobile Engineer, Treasury', 'Data Engineer - Finance', 'Analytics Engineer',
    'Business Intelligence Developer', 'Financial Software Developer', 'SWE Intern',
    'Senior Financial Analyst I', 'Director of Business Analytics', 'VP Finance',
    'Clinical Laboratory Analyst', 'Cybersecurity Analyst', 'Mechanical Engineer',
    'Financial Analyst Summer Associate', 'Business Analyst (Year in Industry)',
])
def test_swe_senior_and_unrelated_occupations_do_not_qualify(title):
    assert not classify(title, '0 years of experience.', 'New York, NY', 'US')['in_scope']


@pytest.mark.parametrize('location,country,countries',[
    ('Toronto, ON', '', ['CA']), ('Remote - Canada', '', ['CA']),
    ('London, UK', '', ['GB']), ('Edinburgh, Scotland', '', ['GB']),
    ('London', 'GB', ['GB']), ('Remote', 'CA', ['CA']),
    ('Remote (United States | Canada | United Kingdom)', '', ['US','CA','GB']),
    ('New York, NY · Toronto, ON · London, England', 'US', ['US','CA','GB']),
    ('New York, NY · Berlin, Germany', 'US', ['US']),
    ('Remote', '', []), ('Worldwide', '', []), ('Georgia', '', []),
    ('Dubai', 'US', []), ('Dubai', 'CA', []), ('Toronto, ON', 'US', []),
    ('London, England', 'US', []), ('Paris, France', 'FR', []),
    ('Remote, excluding Canada', '', []), ('Remote (not US)', '', []),
    ('Remote, non-Canada', '', []), ('Remote, not UK', '', []),
    ('Toronto, OH', 'US', ['US']), ('Scotland, PA', 'US', ['US']),
    ('Remote - London', 'GB', ['GB']), ('London', 'US', []),
    ('Remote, On-site', '', []),
])
def test_three_country_geography_never_guesses_from_remote_or_wrong_metadata(location,country,countries):
    assert search_location(location,country)[1]==countries


@pytest.mark.parametrize('location,country,allowed',[
    ('New York, NY','US',False), ('Toronto, ON','CA',True), ('London, England','GB',True),
    ('New York, NY · Toronto, ON','US',True),
])
def test_us_sponsorship_restrictions_do_not_hide_canada_or_uk(location,country,allowed):
    job={'title':'Financial Analyst I','description':'2 years of experience. No visa sponsorship.',
         'location':location,'country':country,'verified_at':'2026-10-17T17:00:00Z'}
    decision=eligibility(job,strict_cohort=False)
    assert decision['eligible']==allowed
    if allowed:assert any('Prior experience' in w for w in decision['warnings'])


def test_mixed_required_experience_does_not_choose_the_smallest_number():
    result=classify('Business Analyst','5 years of professional experience and 2 years of SQL experience required.','New York, NY')
    assert not result['in_scope'] and result['min_years']==5
    assert classify('Financial Analyst','Three years of experience required.','New York, NY')['in_scope']


def test_country_filters_and_editions_cover_all_three_countries(tmp_path):
    cfg=Config(data_dir=tmp_path,secret='x'*40,password='',schedule=False,production=False)
    db=Database(tmp_path/'test.sqlite3');sid=db.add_source('ashby','acme','Acme');source=db.sources()[0]
    jobs=[]
    for i,(location,country) in enumerate([('New York, NY','US'),('Toronto, ON','CA'),('London, UK','GB')]):
        jobs.append(dict(external_id=str(i),title=f'Financial Analyst I - Team {i}',company='Acme',
                         location=location,country=country,description='3 years of experience. Starting June 2027.',
                         apply_url=f'https://jobs.ashbyhq.com/acme/{i}',posted_at='2026-10-17T15:00:00Z',posted_kind='employer_publication'))
    db.ingest(source,jobs,None,cfg.start_date)
    with TestClient(create_app(cfg,db)) as client:
        for country in PROFILE.countries:
            rows=client.get('/api/jobs',params={'country':country,'role':'finance'}).json()
            assert rows['total']==1 and rows['jobs'][0]['work_countries']==[country]
        assert client.get('/api/jobs?country=IN').status_code==400
        assert client.get('/api/overview').json()['publication']['limit']==100
    with db.connect() as c:
        c.execute("UPDATE jobs SET first_seen='2026-10-17T17:00:00Z',verified_at='2026-10-17T17:00:00Z'")
    from datetime import datetime
    db.publish_edition(datetime.fromisoformat('2026-10-17T22:30:00+00:00'),cfg.start_date)
    assert db.edition()['total']==3
    for job in db.edition()['jobs']:db.decide(job['id'],{'status':'applied'})
    assert db.jobs('tracked')['total']==3


def test_himalayas_collects_each_explicit_country_source():
    requested=[]
    def handler(request):
        requested.append(request.url.params['country'])
        return httpx.Response(200,json={'jobs':[]})
    async def collect():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            fetcher=Fetcher(client)
            for slug in ['us-business','ca-business','uk-business']:
                await fetcher.collect({'provider':'himalayas','slug':slug,'name':slug})
    asyncio.run(collect())
    assert requested==['US','CA','GB']


def test_smartrecruiters_does_not_limit_discovery_to_us():
    requests=[]
    def handler(request):
        requests.append(request)
        row={'id':'123','name':'Financial Analyst I','location':{'country':'gb','city':'London'}}
        if request.url.path.endswith('/123'):
            return httpx.Response(200,json={**row,'jobAd':{'sections':{'qualifications':{'text':'0-3 years of experience.'}}}})
        assert 'country' not in request.url.params
        return httpx.Response(200,json={'content':[row],'totalFound':1})
    async def collect():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await Fetcher(client).collect({'provider':'smartrecruiters','slug':'Acme','name':'Acme'})
    jobs,_=asyncio.run(collect())
    assert jobs[0]['country']=='GB' and jobs[0]['description'] and len(requests)==2


def test_multilocation_adapter_preserves_supported_country_among_foreign_locations():
    row=ashby({'title':'Financial Analyst','jobUrl':'https://jobs.ashbyhq.com/acme/1',
               'location':'Berlin, Germany','address':{'postalAddress':{'addressCountry':'DE'}},
               'secondaryLocations':[{'location':'London, England','address':{'postalAddress':{'addressCountry':'GB'}}}]}, {'name':'Acme'})
    assert row['country']=='GB' and search_location(row['location'],row['country'])[1]==['GB']


def test_fresh_database_has_no_inherited_account_and_rejects_other_host_credentials(tmp_path):
    dbs=[Database(tmp_path/f'{name}.sqlite3') for name in ['original','ria']]
    cfg=Config(data_dir=tmp_path,secret='x'*40,password='',schedule=False,production=False)
    original,ria=(Plus(db,cfg) for db in dbs)
    record={'access_token':'oauth-original','refresh_token':'original-refresh','client_id':'original-client',
            'id_token':'identity','subject':'original-owner','email':'original@example.com',
            'expires_at':time.time()+3600,'scopes':['chatgpt.tokens.use.direct'],'ext_agent_host_id':dbs[0].get('host_id')}
    original.save(record)
    load_seeds(dbs[1])
    assert not ria.status()['connected'] and dbs[1].jobs('all')['total']==0
    assert dbs[0].get('host_id')!=dbs[1].get('host_id')
    with TestClient(create_app(cfg,dbs[1])) as client:
        response=client.post('/api/chatgpt/import',json={'credentials':record,'plan_only_confirmed':True},headers={'X-Tracker-Request':'1'})
        assert response.status_code==400 and 'host ID' in response.json()['detail']
    assert original.record()['access_token']=='oauth-original' and ria.record() is None
    prompt=ai_instructions(cfg.start_date)
    assert 'Drexel' in prompt and 'FP&A' in prompt and 'Canada' in prompt
    assert 'US software new grad' not in prompt
