#!/usr/bin/env python3
"""Generate the CD deployer admission policies from the LIVE API schema so no field can be forgotten.
Rule: the CD deployer may change ONLY container image, container imagePullPolicy and the single imagePullSecret 'gitlab-registry'.
Every other field of the Deployment / CronJob / Pod template / containers must be equal to the stored object."""
import json, sys
apps = json.load(open('openapi-apps.json')); batch = json.load(open('openapi-batch.json')); core = json.load(open('openapi-core.json'))
def props(doc, n): return sorted(doc['components']['schemas'][n]['properties'])
DEP = props(apps, 'io.k8s.api.apps.v1.DeploymentSpec')
CRON = props(batch, 'io.k8s.api.batch.v1.CronJobSpec')
JOB = props(batch, 'io.k8s.api.batch.v1.JobSpec')
POD = props(core, 'io.k8s.api.core.v1.PodSpec')
CTR = props(core, 'io.k8s.api.core.v1.Container')
META = ['annotations', 'finalizers', 'labels', 'ownerReferences']          # object metadata the deployer must not change
POD_FREE = {'containers', 'imagePullSecrets'}                              # handled by dedicated rules
CTR_FREE = {'image', 'imagePullPolicy'}
REG = 'registry.rnl.tecnico.ulisboa.pt/psia/groups26/g15/'

def eq(a, b, f): return f"{a}.?{f} == {b}.?{f}"
def chunks(lst, n): return [lst[i:i+n] for i in range(0, len(lst), n)]

def policy(kind_lower, kind, resource, group, component_expr, spec_prefix_new, spec_prefix_old, wl_checks):
    ns = f"{spec_prefix_new}"
    newpod, oldpod = f"{spec_prefix_new}.template.spec", f"{spec_prefix_old}.template.spec"
    v = []
    v.append(("update-only", "request.operation == 'UPDATE'", "the CD deployer may only update existing objects"))
    v.append(("metadata-unchanged", " && ".join(eq("object.metadata", "oldObject.metadata", m) for m in META), "object labels, annotations, owners and finalizers cannot change"))
    for i, grp in enumerate(chunks(wl_checks, 6)):
        v.append((f"workload-spec-{i+1}", " && ".join(grp), "workload settings (replicas, strategy, selector, schedule, suspend, concurrency, jobTemplate...) cannot change"))
    podfields = [f for f in POD if f not in POD_FREE]
    for i, grp in enumerate(chunks(podfields, 8)):
        v.append((f"pod-spec-{i+1}", " && ".join(eq(newpod, oldpod, f) for f in grp), "pod settings (init containers, volumes, service account, scheduling, security context, host namespaces...) cannot change"))
    ctrfields = [f for f in CTR if f not in CTR_FREE]
    v.append(("containers-same-names", f"{newpod}.containers.map(c, c.name) == {oldpod}.containers.map(c, c.name)", "containers cannot be added, removed, renamed or reordered"))
    for i, grp in enumerate(chunks(ctrfields, 8)):
        v.append((f"container-fields-{i+1}", f"{newpod}.containers.all(c, {oldpod}.containers.exists(o, o.name == c.name && " + " && ".join(eq("c", "o", f) for f in grp) + "))", "container command, args, env, ports, resources, probes, lifecycle, security context and mounts cannot change"))
    v.append(("images", f"{newpod}.containers.all(c, {oldpod}.containers.exists(o, o.name == c.name && (c.image == o.image || c.image == variables.legacy || (c.image.startsWith(variables.registryRef) && c.image.matches('^[^@]+@sha256:[0-9a-f]{{64}}$')))))", "image must stay unchanged, return to the legacy local image, or be a digest-pinned image of THIS component in the project registry"))
    v.append(("pull-policy", f"{newpod}.containers.all(c, {oldpod}.containers.exists(o, o.name == c.name && (c.imagePullPolicy == o.imagePullPolicy || c.imagePullPolicy in ['IfNotPresent', 'Never'])))", "imagePullPolicy may only be IfNotPresent or Never"))
    v.append(("pull-secret", f"!has({newpod}.imagePullSecrets) || {newpod}.imagePullSecrets.all(s, s.name == 'gitlab-registry')", "the only allowed imagePullSecret is 'gitlab-registry'"))
    out = [f"apiVersion: admissionregistration.k8s.io/v1\nkind: ValidatingAdmissionPolicy\nmetadata: {{name: ci-deployer-guardrails-{kind_lower}}}\nspec:\n  failurePolicy: Fail\n  matchConstraints:\n    resourceRules:\n      - apiGroups: [{group!r}]\n        apiVersions: ['v1']\n        operations: ['CREATE', 'UPDATE']\n        resources: ['{resource}']\n  matchConditions:\n    - name: only-the-cd-deployer\n      expression: \"request.userInfo.username == 'system:serviceaccount:g15-cd:ci-deployer'\"\n  variables:\n    - name: component\n      expression: \"{component_expr}\"\n    - name: legacy\n      expression: \"'g15-' + variables.component + ':local'\"\n    - name: registryRef\n      expression: \"'{REG}' + variables.component + '@sha256:'\"\n  validations:"]
    for name, expr, msg in v:
        out.append(f"    - expression: {json.dumps(expr)}\n      message: {json.dumps(name + ': ' + msg)}")
    out.append(f"---\napiVersion: admissionregistration.k8s.io/v1\nkind: ValidatingAdmissionPolicyBinding\nmetadata: {{name: ci-deployer-guardrails-{kind_lower}}}\nspec:\n  policyName: ci-deployer-guardrails-{kind_lower}\n  validationActions: [Deny, Audit]\n")
    return "\n".join(out)

dep_checks = [eq("object.spec", "oldObject.spec", f) for f in DEP if f != 'template'] + [eq("object.spec.template", "oldObject.spec.template", "metadata")]
job_checks = ([eq("object.spec", "oldObject.spec", f) for f in CRON if f != 'jobTemplate'] + [eq("object.spec.jobTemplate", "oldObject.spec.jobTemplate", "metadata")]
              + [eq("object.spec.jobTemplate.spec", "oldObject.spec.jobTemplate.spec", f) for f in JOB if f != 'template'] + [eq("object.spec.jobTemplate.spec.template", "oldObject.spec.jobTemplate.spec.template", "metadata")])
txt = ("# GENERATED by gen-policy.py from the live v1.36.5 OpenAPI schema -- do not edit by hand. Re-run after any Kubernetes upgrade\n"
       "# and run check-coverage.py. Applies ONLY to the identity system:serviceaccount:g15-cd:ci-deployer.\n"
       "# The deployer may change only: container image (digest-pinned image of THIS component in the project registry, or the legacy\n"
       "# local image for rollback), imagePullPolicy (IfNotPresent|Never) and the single imagePullSecret 'gitlab-registry'.\n")
txt += policy('deployments', 'Deployment', 'deployments', 'apps', "object.metadata.name", "object.spec", "oldObject.spec", dep_checks)
txt += "\n---\n"
# CronJob: the pod template lives under spec.jobTemplate.spec.template
cj = policy('cronjob', 'CronJob', 'cronjobs', 'batch', "'recommendation-service'", "object.spec.jobTemplate.spec", "oldObject.spec.jobTemplate.spec", job_checks)
txt += cj
open('30-deployer-admission-policy.yaml', 'w').write(txt)
print('generated', txt.count('- expression:'), 'validations;', 'deployment spec fields', len(DEP), '| cronjob', len(CRON), '| job', len(JOB), '| pod', len(POD), '| container', len(CTR))
