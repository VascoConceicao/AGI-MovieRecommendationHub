#!/usr/bin/env python3
"""Fail if the live API schema has a Deployment/CronJob/Job/Pod/Container field that the policy neither compares nor explicitly frees.
Refresh the inputs first:  kubectl get --raw /openapi/v3/apis/apps/v1 > openapi-apps.json  (same for batch/v1 and api/v1)."""
import json, re, sys
pol = open('30-deployer-admission-policy.yaml').read()
mentioned = set(re.findall(r'\.\?([A-Za-z]+)', pol))
free = {'containers', 'imagePullSecrets', 'image', 'imagePullPolicy', 'template', 'jobTemplate'}   # handled by dedicated rules
apps, batch, core = (json.load(open(f)) for f in ('openapi-apps.json', 'openapi-batch.json', 'openapi-core.json'))
def props(doc, n): return set(doc['components']['schemas'][n]['properties'])
checks = {'DeploymentSpec': props(apps, 'io.k8s.api.apps.v1.DeploymentSpec'), 'CronJobSpec': props(batch, 'io.k8s.api.batch.v1.CronJobSpec'),
          'JobSpec': props(batch, 'io.k8s.api.batch.v1.JobSpec'), 'PodSpec': props(core, 'io.k8s.api.core.v1.PodSpec'), 'Container': props(core, 'io.k8s.api.core.v1.Container')}
bad = 0
for name, fields in checks.items():
    missing = sorted(f for f in fields if f not in mentioned and f not in free)
    print(f'{name:15s} {len(fields):3d} fields | not covered: {missing or "none"}'); bad += bool(missing)
sys.exit(1 if bad else 0)
