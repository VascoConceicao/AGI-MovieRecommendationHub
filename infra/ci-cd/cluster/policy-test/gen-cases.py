#!/usr/bin/env python3
"""Build policy test cases from the LIVE objects: hand-written allow/deny cases + an automatic mutation test over EVERY schema field."""
import copy, json
apps = json.load(open('openapi-apps.json')); batch = json.load(open('openapi-batch.json')); core = json.load(open('openapi-core.json'))
def props(doc, n): return sorted(doc['components']['schemas'][n]['properties'])
DEP, CRON, JOB = props(apps,'io.k8s.api.apps.v1.DeploymentSpec'), props(batch,'io.k8s.api.batch.v1.CronJobSpec'), props(batch,'io.k8s.api.batch.v1.JobSpec')
POD, CTR = props(core,'io.k8s.api.core.v1.PodSpec'), props(core,'io.k8s.api.core.v1.Container')
deps = {i['metadata']['name']: i for i in json.load(open('live-deployments.json'))['items']}
cron = json.load(open('live-cronjob.json'))
DEPLOYER = 'system:serviceaccount:g15-cd:ci-deployer'
REG = 'registry.rnl.tecnico.ulisboa.pt/psia/groups26/g15/'
H = lambda c='a': c * 64
cases = []
def add(name, kind, old, new, expect, user=DEPLOYER, op='UPDATE'):
    cases.append({'name': name, 'kind': kind, 'user': user, 'op': op, 'old': old, 'new': new, 'expect': expect})
def podspec(o): return o['spec']['jobTemplate']['spec']['template']['spec'] if o['kind'] == 'CronJob' else o['spec']['template']['spec']
def comp(o): return 'recommendation-service' if o['kind'] == 'CronJob' else o['metadata']['name']
def mut(o, fn): n = copy.deepcopy(o); fn(n); return n
DUMMY = {'__mutated': 'x'}
targets = [(n, 'deployment', o) for n, o in deps.items()] + [('recommendation-agent', 'cronjob', cron)]
for name, kind, base in targets:
    c = comp(base); P = podspec
    img = f"{REG}{c}@sha256:{H()}"
    # ---- allowed
    add(f'{name}: identical object (no-op)', kind, base, copy.deepcopy(base), 'allow')
    add(f'{name}: image -> own registry digest', kind, base, mut(base, lambda n: P(n)['containers'][0].__setitem__('image', img)), 'allow')
    add(f'{name}: pullPolicy IfNotPresent', kind, base, mut(base, lambda n: P(n)['containers'][0].__setitem__('imagePullPolicy', 'IfNotPresent')), 'allow')
    add(f'{name}: add imagePullSecret gitlab-registry', kind, base, mut(base, lambda n: P(n).__setitem__('imagePullSecrets', [{'name': 'gitlab-registry'}])), 'allow')
    def full(n): p = P(n); p['containers'][0]['image'] = img; p['containers'][0]['imagePullPolicy'] = 'IfNotPresent'; p['imagePullSecrets'] = [{'name': 'gitlab-registry'}]
    mig = mut(base, full)
    add(f'{name}: full first migration (image+policy+secret)', kind, base, mig, 'allow')
    add(f'{name}: rollback to legacy local image', kind, mig, mut(mig, lambda n: (P(n)['containers'][0].__setitem__('image', f'g15-{c}:local'), P(n)['containers'][0].__setitem__('imagePullPolicy', 'Never'))), 'allow')
    add(f'{name}: roll forward digest -> another digest', kind, mig, mut(mig, lambda n: P(n)['containers'][0].__setitem__('image', f"{REG}{c}@sha256:{H('b')}")), 'allow')
    # ---- denied images / policy / secrets
    bad_images = {'tag instead of digest': f'{REG}{c}:latest', 'short digest': f'{REG}{c}@sha256:{"a"*63}', 'uppercase digest': f'{REG}{c}@sha256:{"A"*64}',
                  'trailing garbage': f'{REG}{c}@sha256:{H()}x', 'other component repo': f'{REG}{"frontend" if c != "frontend" else "proxy"}@sha256:{H()}',
                  'experiments repo': f'{REG}experiments/recommendation@sha256:{H()}', 'foreign registry': f'docker.io/evil/{c}@sha256:{H()}',
                  'prefix trick': f'{REG}{c}-evil@sha256:{H()}', 'legacy of another component': 'g15-frontend:local' if c != 'frontend' else 'g15-proxy:local',
                  'arbitrary local tag': f'g15-{c}:evil', 'empty': ''}
    for lbl, bi in bad_images.items():
        add(f'{name}: DENY image {lbl}', kind, base, mut(base, lambda n, bi=bi: P(n)['containers'][0].__setitem__('image', bi)), 'deny')
    add(f'{name}: DENY pullPolicy Always', kind, base, mut(base, lambda n: P(n)['containers'][0].__setitem__('imagePullPolicy', 'Always')), 'deny')
    add(f'{name}: DENY other pull secret', kind, base, mut(base, lambda n: P(n).__setitem__('imagePullSecrets', [{'name': 'g15-db-passwords'}])), 'deny')
    add(f'{name}: DENY good+bad pull secrets', kind, base, mut(base, lambda n: P(n).__setitem__('imagePullSecrets', [{'name': 'gitlab-registry'}, {'name': 'other'}])), 'deny')
    add(f'{name}: DENY CREATE operation', kind, base, copy.deepcopy(base), 'deny', op='CREATE')
    add(f'{name}: ALLOW same change by a human admin (policy must not apply)', kind, base, mut(base, lambda n: P(n)['containers'][0].__setitem__('env', [{'name': 'X', 'value': '1'}])), 'allow', user='kubernetes-admin')
    add(f'{name}: ALLOW same change by another service account', kind, base, mut(base, lambda n: P(n)['containers'][0].__setitem__('env', [])), 'allow', user='system:serviceaccount:kube-system:deployment-controller')
    # structural container changes
    add(f'{name}: DENY extra container', kind, base, mut(base, lambda n: P(n)['containers'].append({'name': 'sidecar', 'image': img})), 'deny')
    add(f'{name}: DENY removed container', kind, base, mut(base, lambda n: P(n).__setitem__('containers', [])), 'deny')
    add(f'{name}: DENY renamed container', kind, base, mut(base, lambda n: P(n)['containers'][0].__setitem__('name', 'renamed')), 'deny')
    add(f'{name}: DENY object metadata labels', kind, base, mut(base, lambda n: n['metadata'].setdefault('labels', {}).__setitem__('x', 'y')), 'deny')
    add(f'{name}: DENY object metadata annotations', kind, base, mut(base, lambda n: n['metadata'].setdefault('annotations', {}).__setitem__('x', 'y')), 'deny')
    add(f'{name}: DENY object finalizers', kind, base, mut(base, lambda n: n['metadata'].__setitem__('finalizers', ['x'])), 'deny')
    # ---- automatic mutation coverage over EVERY schema field
    def tmpl(o): return o['spec']['jobTemplate']['spec']['template'] if kind == 'cronjob' else o['spec']['template']
    def apply(o, container, path, field, how):
        n = copy.deepcopy(o); d = path(n)
        if how == 'delete':
            if field not in d: return None
            del d[field]
        else: d[field] = DUMMY if (field not in d or d[field] != DUMMY) else 'other'
        return n
    wl_fields = [(f, (lambda n: n['spec'])) for f in (CRON if kind == 'cronjob' else DEP) if f not in ('template', 'jobTemplate')]
    if kind == 'cronjob':
        wl_fields += [(f, (lambda n: n['spec']['jobTemplate']['spec'])) for f in JOB if f != 'template']
        wl_fields += [('metadata', lambda n: n['spec']['jobTemplate'])]
    wl_fields += [('metadata', lambda n: tmpl(n))]
    groups = [('workload', wl_fields),
              ('pod', [(f, lambda n: tmpl(n)['spec']) for f in POD if f not in ('containers', 'imagePullSecrets')]),
              ('container', [(f, lambda n: tmpl(n)['spec']['containers'][0]) for f in CTR if f not in ('image', 'imagePullPolicy')])]
    for g, fields in groups:
        for f, path in fields:
            for how in ('set', 'delete'):
                n = apply(base, None, path, f, how)
                if n is None: continue
                add(f'{name}: MUTATE {g}.{f} ({how})', kind, base, n, 'deny')
    # free fields MUST remain changeable (policy is not over-strict)
    for f in ('image', 'imagePullPolicy'):
        add(f'{name}: FREE container.{f} changes', kind, base, mut(base, lambda n, f=f: P(n)['containers'][0].__setitem__(f, img if f == 'image' else 'IfNotPresent')), 'allow')
json.dump(cases, open('cases.json', 'w'))
print('cases:', len(cases), '| deny:', sum(c['expect'] == 'deny' for c in cases), '| allow:', sum(c['expect'] == 'allow' for c in cases))
