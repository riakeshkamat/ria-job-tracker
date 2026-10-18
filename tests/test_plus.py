import asyncio
import json
import time

import httpx
import pytest

from tracker.config import Config
from tracker.db import Database
from tracker.plus import PlanError,Plus
from tracker.sources import ashby,lever


def test_nullable_ashby_location_is_valid():
    result=ashby({'title':'Business Analyst','jobUrl':'https://jobs.ashbyhq.com/acme/1',
                  'address':None,'secondaryLocations':[{'location':'New York','address':None}],
                  'descriptionPlain':'0-2 years of experience'}, {'name':'Acme'})
    assert result['location']=='New York'
    assert result['country']==''


def test_nullable_lever_country_is_unknown_not_a_failed_snapshot():
    result=lever({'id':'123','text':'Business Analyst','categories':{'location':None},'country':None,
                  'description':None,'lists':None,'hostedUrl':'https://jobs.lever.co/acme/123'}, {'name':'Acme'})
    assert result['country']=='' and result['location']==''


@pytest.mark.parametrize('terminal',['response.completed','response.failed',None])
def test_review_requires_completed_grounded_stream_and_reserves_usage(tmp_path,monkeypatch,terminal):
    config=Config(data_dir=tmp_path,secret='x'*40,password='',production=False,schedule=False,ai_limit=1)
    config.prepare()
    db=Database(tmp_path/'test.sqlite3')
    sid=db.add_source('ashby','acme','Acme')
    source=next(s for s in db.sources() if s['id']==sid)
    job={'external_id':'1','title':'Business Analyst New Grad 2027','company':'Acme','location':'New York',
         'country':'US','description':'OPT eligibility will be assessed individually.','apply_url':'https://jobs.ashbyhq.com/acme/1'}
    db.ingest(source,[job],None,'2027-06-01')
    plus=Plus(db,config)
    plus.save({'access_token':'oauth-test','refresh_token':'renewal-test','client_id':'registered-client',
               'expires_at':time.time()+3600,'scopes':['chatgpt.tokens.use.direct']})
    db.set('chatgpt_model','eligible-test-model');db.set('plan_only_confirmed',True)
    advice={'sponsorship':'unknown','quote':'OPT eligibility will be assessed individually.','note':'Future sponsorship is unspecified.'}
    events=[{'type':'response.output_text.delta','delta':json.dumps(advice)}]
    if terminal: events.append({'type':terminal})
    data=''.join('data: '+json.dumps(event)+'\n\n' for event in events)
    requests=[]
    def handler(request):
        requests.append(request)
        body=json.loads(request.content)
        assert body['store'] is False and body['stream'] is True
        assert 'background' not in body and 'max_output_tokens' not in body
        assert request.headers['authorization']=='Bearer oauth-test'
        return httpx.Response(200,content=data,headers={'content-type':'text/event-stream'})
    client_class=httpx.AsyncClient
    monkeypatch.setattr('tracker.plus.httpx.AsyncClient',lambda **kwargs:client_class(transport=httpx.MockTransport(handler),**kwargs))
    if terminal=='response.completed':
        assert asyncio.run(plus.review())==1
        assert db.jobs()['jobs'][0]['ai_review']['sponsorship']=='unknown'
        assert plus.status()['last_success']['model']=='eligible-test-model'
        assert asyncio.run(plus.review())==0 # daily cap prevents a second request
    else:
        with pytest.raises(PlanError): asyncio.run(plus.review())
        assert db.jobs()['jobs'][0]['ai_review'] is None
        assert plus.status()['last_success'] is None
    assert len(requests)==1
    assert db.get('chatgpt_usage')['count']==1
    assert plus.status()['daily_used']==1
    assert plus.status()['daily_remaining']==0
    assert db.jobs()['total']==1 # AI advice/failures never silently remove openings


def test_connection_status_migrates_completed_reviews_once_and_resets_usage(tmp_path,monkeypatch):
    config=Config(data_dir=tmp_path,secret='x'*40,password='',production=False,schedule=False,ai_limit=30)
    db=Database(tmp_path/'test.sqlite3')
    plus=Plus(db,config)
    plus.save({'access_token':'oauth-test','email':'ria@example.test','scopes':['chatgpt.tokens.use.direct']})
    db.set('chatgpt_model','test-model')
    db.set('chatgpt_model_name','Test Model')
    sid=db.add_source('ashby','acme','Acme')
    source=next(s for s in db.sources() if s['id']==sid)
    db.ingest(source,[{'external_id':'1','title':'Business Analyst','company':'Acme','location':'New York',
                      'country':'US','description':'Entry level','apply_url':'https://jobs.ashbyhq.com/acme/1'}],None,'2027-06-01')
    with db.connect() as c:
        c.execute('UPDATE jobs SET ai_review=?',(json.dumps({'model':'test-model','reviewed_at':'2026-10-18T01:43:00+00:00'}),))
    db.set('chatgpt_usage',{'day':'2026-10-17','count':30})
    monkeypatch.setattr('tracker.db.now',lambda:'2026-10-18T02:00:00+00:00')
    status=plus.status()
    assert status['connected'] and status['email']=='ria@example.test'
    assert status['model_name']=='Test Model'
    assert status['last_success']['at']=='2026-10-18T01:43:00+00:00'
    assert status['daily_used']==0 and status['daily_remaining']==30
    assert status['busy'] is False
    # New imports/disconnects clear proof and mark migration complete, so retained
    # advice from a previous account cannot verify the next account.
    db.set('chatgpt_last_success',None)
    db.set('chatgpt_last_result',{'status':'success','message':'0 descriptions reviewed.'})
    plus.save({'access_token':'different-oauth','email':'other@example.test','scopes':['chatgpt.tokens.use.direct']})
    assert plus.status()['last_success'] is None
    async def busy_status():
        async with plus.lock:
            assert plus.status()['busy'] is True
    asyncio.run(busy_status())
