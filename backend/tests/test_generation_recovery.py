"""Recovery/cancellation doubles never represent production music acceptance."""
import json
import threading
import time
import uuid

import pytest

from app.jobs import JobService, JobError
from app.providers.control import GenerationControl
from app.providers.errors import ProviderError
from app.providers.staged import HarmonyPlan, explicit_key
from app.music.pipeline import generate_work, PipelineError
from test_jobs_api import api, wait_final
from test_staged_provider import StageDouble


def test_lost_response_reuses_one_job_and_rejects_changed_payload(tmp_path):
    gate, started = threading.Event(), threading.Event()
    calls = []
    def runner(*args, **kwargs):
        calls.append(1); started.set(); gate.wait(2)
        raise RuntimeError('isolated failure')
    with api(JobService(tmp_path, runner=runner)) as client:
        try:
            identifier = str(uuid.uuid4())
            body = {'request_id':identifier, 'prompt':'warm'}
            assert client.post('/api/generate', json=body).json()['job_id'] == identifier
            assert started.wait(1)
            for _ in range(3):
                assert client.post('/api/generate', json=body).json()['job_id'] == identifier
            assert client.post('/api/generate', json={**body,'prompt':'different'}).status_code == 409
        finally: gate.set()
        assert wait_final(client, identifier)['status'] == 'failed'
        assert client.post('/api/generate', json=body).json()['job_id'] == identifier
    assert len(calls) == 1


def test_cancel_before_post_makes_delayed_submission_non_billable(tmp_path):
    calls = []
    with api(JobService(tmp_path, runner=lambda *a, **k:calls.append(1))) as client:
        identifier = str(uuid.uuid4())
        assert client.post('/api/jobs/'+identifier+'/cancel').status_code == 202
        assert client.post('/api/generate', json={'request_id':identifier,'prompt':'warm'}).json()['job_id'] == identifier
        assert client.get('/api/jobs/'+identifier).json()['error']['code'] == 'generation_cancelled'
        assert client.post('/api/jobs/not-a-uuid/cancel').status_code == 404
    assert not calls


def test_cancel_queued_job_never_runs_provider(tmp_path):
    gate, started = threading.Event(), threading.Event(); calls=[]
    def runner(prompt, **kwargs):
        calls.append(prompt); started.set(); gate.wait(2); raise RuntimeError('test')
    with api(JobService(tmp_path, runner=runner)) as client:
        try:
            client.post('/api/generate',json={'prompt':'first'}); assert started.wait(1)
            second=client.post('/api/generate',json={'prompt':'second'}).json()['job_id']
            client.post('/api/jobs/'+second+'/cancel')
            assert client.get('/api/jobs/'+second).json()['status']=='failed'
        finally: gate.set()
    assert calls==['first']


def test_deadline_and_cancel_are_checked_before_publication(tmp_path):
    control=GenerationControl(tmp_path,time.time()-1)
    with pytest.raises(ProviderError) as error: control.checkpoint()
    assert error.value.code=='generation_timeout'
    control.deadline=time.time()+10; (tmp_path/'.cancel').touch()
    with pytest.raises(ProviderError) as error:
        with control.publication(): pytest.fail('cancelled music was published')
    assert error.value.code=='generation_cancelled'


def test_mid_bar_network_failure_keeps_completed_receipts_in_manifest(tmp_path):
    provider=StageDouble(); original=provider.generate_structure; calls=[0]
    def generate(prompt,instruction,schema):
        calls[0]+=1
        if calls[0]==3: raise ProviderError('network_error','test connection failed')
        return original(prompt,instruction,schema)
    provider.generate_structure=generate
    with pytest.raises(PipelineError) as error: generate_work('warm',jobs_root=tmp_path,provider=provider)
    manifest=json.loads((tmp_path/error.value.job_id/'manifest.json').read_text())
    steps=manifest['attempts'][0]['request']['steps']
    assert [s['status'] for s in steps]==['accepted','accepted','failed']
    assert steps[-1]['code']=='network_error'
    assert not (tmp_path/error.value.job_id/'artifacts').exists()


def test_cancel_during_model_step_keeps_receipt_and_never_exports(tmp_path):
    provider=StageDouble(); original=provider.generate_structure
    def generate(prompt,instruction,schema):
        result=original(prompt,instruction,schema)
        if schema is not HarmonyPlan:
            next(tmp_path.glob('*/manifest.json')).parent.joinpath('.cancel').touch()
        return result
    provider.generate_structure=generate
    with pytest.raises(PipelineError) as error: generate_work('warm',jobs_root=tmp_path,provider=provider)
    assert error.value.code=='generation_cancelled'
    manifest=json.loads((tmp_path/error.value.job_id/'manifest.json').read_text())
    assert len(manifest['attempts'][0]['request']['steps'])>=2
    assert not manifest['files']


@pytest.mark.parametrize('prompt,key',[('B大调',(11,False)),('降B小调',(10,True)),('F# minor',(6,True)),('忧伤',None)])
def test_explicit_key_does_not_infer_minor_from_mood(prompt,key):
    assert explicit_key(prompt)==key


def test_unsupported_explicit_key_fails_before_first_model_call():
    p=StageDouble()
    with pytest.raises(ProviderError) as error: p.generate_candidate('B大调，四小节',production=True)
    assert error.value.code=='unsupported_key' and not p.calls


def test_queued_deadline_is_visible_without_waiting_for_worker(tmp_path):
    identifier=str(uuid.uuid4());folder=tmp_path/identifier;folder.mkdir()
    service=JobService(tmp_path)
    try:
        (folder/'manifest.json').write_text(json.dumps({'job_id':identifier,'status':'queued','files':{},'deadline_at':time.time()-1}))
        assert service.public_state(identifier)['error']['code']=='generation_timeout'
    finally:service.close()
