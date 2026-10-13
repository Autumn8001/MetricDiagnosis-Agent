"""Owned ephemeral PostgreSQL and SQL-backed controlled runner for Lab acceptance."""
from contextlib import contextmanager
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path
import os
import socket
import subprocess
import tempfile
from uuid import uuid4


@contextmanager
def temporary_postgres(binary):
    binary=Path(binary).resolve()
    with tempfile.TemporaryDirectory(prefix='metricsleuth-r5004-pg-') as temporary:
        root=Path(temporary);data=root/'data';sockets=root/'sockets';sockets.mkdir(mode=0o700)
        with socket.socket() as reservation:
            reservation.bind(('127.0.0.1',0));port=reservation.getsockname()[1]
        started=False
        with (root/'commands.log').open('wb') as log:
            def run(arguments):
                result=subprocess.run(arguments,stdout=log,stderr=log,timeout=30,
                    env={'PATH':'/usr/bin:/bin','LANG':'C','LC_ALL':'C'})
                if result.returncode:raise RuntimeError('isolated_postgres_command_failed')
            try:
                run([str(binary/'initdb'),'-D',str(data),'-U','metricsleuth_test','--auth=trust','--no-locale','-E','UTF8'])
                # No system service, existing cluster, global configuration or fixed port.
                run([str(binary/'pg_ctl'),'-D',str(data),'-l',str(root/'server.log'),'-o',
                    f'-h 127.0.0.1 -p {port} -k {sockets} -c shared_buffers=16MB -c max_connections=20','-w','start'])
                started=True
                yield lambda name:f'postgresql://metricsleuth_test@127.0.0.1:{port}/{name}'
            finally:
                if started:run([str(binary/'pg_ctl'),'-D',str(data),'-m','fast','-w','stop'])


def controlled_lab_runner(prompt, **kwargs):
    """One actual semantic SQL read; normal result can finish, anomalous one stops.

    This is a controlled Runner, not an LLM. It cannot verify autonomous strategy.
    """
    from app.agent_runtime.diagnosis_runtime import EvidenceDrivenRunSummary
    from app.agent_runtime.investigation_runtime import InvestigationRunSummary, InvestigationToolTraceEntry
    from app.observations.mapper import observations_from_metric_query
    from app.evidence import promote_observation_to_evidence, EvidenceRole
    from app.diagnosis.builder import build_diagnosis
    from app.diagnosis.models import DiagnosisStatus
    from app.diagnosis.composition import DiagnosisComposition
    tools=kwargs['analytics_tools'];target=date(2026,1,31)
    result=tools.query_metric('sales',target,target,'previous_7_days',filters={},group_by=[])
    call='controlled-lab-'+str(uuid4())
    created=datetime.now(timezone.utc)
    observations=observations_from_metric_query(result,tool_name='query_metric',tool_call_id=call,
        filters={},query_or_result_reference='analytics-result:'+call,created_at=created)
    trace=InvestigationToolTraceEntry(tool_call_id=call,tool_name='query_metric',
        arguments={'metric':'sales','start_date':target.isoformat(),'end_date':target.isoformat(),
                   'compare_to':'previous_7_days','filters':{},'group_by':[]},
        observation_ids=tuple(o.observation_id for o in observations))
    kwargs['progress_callback'](trace,observations)
    if len(observations)!=1 or observations[0].status.value!='normal':
        raise RuntimeError('controlled_anomalous_run_stopped_without_diagnosis')
    evidence=promote_observation_to_evidence(observations[0],role=EvidenceRole.SUPPORTING)
    diagnosis=build_diagnosis(diagnosis_id=kwargs['diagnosis_id'],status=DiagnosisStatus.NO_MATERIAL_ANOMALY,
        target_metric='sales',evidence=(evidence,),target_evidence_id=evidence.evidence_id,
        confidence=Decimal('1'),limitations=('Controlled SQL acceptance; no real model was invoked.',),created_at=created)
    summary=InvestigationRunSummary(final_output='Controlled Lab SQL result',tool_calls_count=1,
        max_tool_calls=kwargs['max_tool_calls'],tools_used=('query_metric',),tool_call_ids=(call,),
        observation_ids=trace.observation_ids,observation_count=len(observations),tool_trace=(trace,),
        trace_sequence=(call,),turns_count=1,max_turns=kwargs['max_turns'])
    return EvidenceDrivenRunSummary(investigation=summary,composition=DiagnosisComposition(evidence=(evidence,),diagnosis=diagnosis),
        observation_catalog=observations)
