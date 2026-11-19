#!/usr/bin/env python3
"""Small sequential recommendation-latency experiment on the MAIN g15 GCP deployment (not a load test).

Stages (python3 -I run_experiment.py <stage>):
  env    capture deployed versions, model settings, resource limits (read-only)
  setup  register a DISPOSABLE test account through the normal API, make its profile private, mark 5 fixed movies as watched
  scan   compute eligible-candidate counts with the application's own code (read-only, no inference) and print filter options
  run    7 sequential user-requested generations (interleaved), capturing job rows, llama.cpp timings, cgroup counters
  report build the sanitized tables from raw/

Credentials and the session cookie live ONLY in the private directory ($G15_PRIVATE_DIR, outside this folder) and are never written to raw/.
Only the standard library is used. Cluster access is read-only (kubectl get/logs/exec of cat/psql SELECT) through ssh to the control plane.
"""
import base64, http.cookiejar, json, os, re, secrets, shlex, statistics, subprocess, sys, time, urllib.error, urllib.request
from datetime import datetime, timezone

BASE = 'http://34.175.197.152:30080'
HERE = os.path.dirname(os.path.abspath(__file__))
RAW = os.path.join(HERE, 'raw')
PRIVATE = os.environ.get('G15_PRIVATE_DIR', '')
KC = 'sudo kubectl --kubeconfig=/etc/kubernetes/admin.conf'
NS = 'g15-app'
HDR = {'X-G15-Request': '1', 'Content-Type': 'application/json'}


def now():
    return datetime.now(timezone.utc).isoformat(timespec='milliseconds')


def log(msg):
    line = '%s %s' % (now(), msg)
    print(line, flush=True)
    with open(os.path.join(HERE, 'run.log'), 'a') as handle:
        handle.write(line + '\n')


def ssh_base(host='g15-cp1'):
    out = subprocess.run(['gcloud', 'compute', 'ssh', host, '--zone=europe-southwest1-a', '--dry-run', '--command', 'true'],
                         capture_output=True, text=True).stdout.strip()
    return out[:-len(' -- true')] if out.endswith(' -- true') else out


_SSH = {}


def sh(cmd, host='g15-cp1', timeout=120):
    if host not in _SSH:
        _SSH[host] = ssh_base(host)
    proc = subprocess.run(['bash', '-c', 'timeout %d %s -- %s' % (timeout, _SSH[host], shlex.quote(cmd))], capture_output=True, text=True)
    return proc.stdout


def psql(sql):
    cmd = '%s -n %s exec recommendation-db-0 -- sh -c %s' % (KC, NS, shlex.quote('psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Atc "$0"') + ' ' + shlex.quote(sql))
    return sh(cmd).strip()


def cgroup():
    text = sh('%s -n %s exec deploy/inference -- cat /sys/fs/cgroup/cpu.stat' % (KC, NS))
    out = {k: int(v) for k, v in (line.split() for line in text.splitlines() if line.strip() and len(line.split()) == 2) if k in ('usage_usec', 'user_usec', 'system_usec', 'nr_periods', 'nr_throttled', 'throttled_usec')}
    mem = sh('%s -n %s exec deploy/inference -- cat /sys/fs/cgroup/memory.current' % (KC, NS)).strip()
    if mem.isdigit():
        out['memory_current_bytes'] = int(mem)
    return out


def save(name, data):
    os.makedirs(RAW, exist_ok=True)
    with open(os.path.join(RAW, name), 'w') as handle:
        json.dump(data, handle, indent=1, sort_keys=True)


def load(name):
    with open(os.path.join(RAW, name)) as handle:
        return json.load(handle)


# ------------------------------------------------------------------ HTTP (cookie jar kept in memory / private dir only)
def opener():
    jar = http.cookiejar.MozillaCookieJar(os.path.join(PRIVATE, 'cookies.txt'))
    if os.path.exists(jar.filename):
        jar.load(ignore_discard=True, ignore_expires=True)
    return urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar)), jar


def call(op, method, path, body=None, timeout=30):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(BASE + path, data=data, method=method, headers=HDR if data is not None else {'X-G15-Request': '1'})
    try:
        with op.open(req, timeout=timeout) as response:
            raw = response.read()
            return response.status, (json.loads(raw) if raw else None)
    except urllib.error.HTTPError as error:
        raw = error.read()
        try:
            return error.code, json.loads(raw)
        except ValueError:
            return error.code, None


# ------------------------------------------------------------------ stages
def stage_env():
    env = {'captured_at': now()}
    env['deployments'] = json.loads(sh("%s -n %s get deploy -o json | jq -c '[.items[]|{name:.metadata.name,generation:.metadata.generation,image:.spec.template.spec.containers[0].image,resources:.spec.template.spec.containers[0].resources,args:.spec.template.spec.containers[0].args,replicas:.spec.replicas}]'" % (KC, NS)))
    env['pods'] = json.loads(sh("%s -n %s get pods -o json | jq -c '[.items[]|select(.metadata.name|test(\"^(frontend|proxy|user-service|movie-service|recommendation-service|inference)-\"))|{pod:.metadata.name,node:.spec.nodeName,imageID:.status.containerStatuses[0].imageID,restarts:.status.containerStatuses[0].restartCount,started:.status.startTime}]'" % (KC, NS)))
    env['cronjob'] = json.loads(sh("%s -n %s get cronjob recommendation-agent -o json | jq -c '{suspend:.spec.suspend,schedule:.spec.schedule,image:.spec.jobTemplate.spec.template.spec.containers[0].image,env:[.spec.jobTemplate.spec.template.spec.containers[0].env[]|select(.name|test(\"AGENT|AUTO\"))|{(.name):.value}]}'" % (KC, NS)))
    env['recommendation_env'] = json.loads(sh("%s -n %s get deploy recommendation-service -o json | jq -c '[.spec.template.spec.containers[0].env[]|select(.name|test(\"INFERENCE|AUTO|GENERATION\"))|{(.name):.value}]'" % (KC, NS)))
    env['cd_state'] = sh("%s -n %s get cm cd-state -o jsonpath='status={.data.status} lastVerifiedCommit={.data.lastVerifiedCommit}'" % (KC, NS))
    code = ("import urllib.request,json;m=json.load(urllib.request.urlopen('http://inference:4210/v1/models',timeout=5));"
            "print(json.dumps({'id':m['data'][0]['id'],'meta':m['data'][0].get('meta')}))")
    env['model'] = json.loads(sh("%s -n %s exec deploy/recommendation-service -- python -c %s" % (KC, NS, shlex.quote(code))))
    env['inference_cgroup_limit'] = sh('%s -n %s exec deploy/inference -- cat /sys/fs/cgroup/cpu.max' % (KC, NS)).strip()
    env['worker1_cpu'] = sh("lscpu | grep -E 'Model name|^CPU\\(s\\)|Thread\\(s\\) per core|Core\\(s\\) per socket' | sed 's/  */ /g'", host='g15-worker1')
    env['llama_temperature_sent_by_app'] = 0.2
    save('environment.json', env)
    log('environment captured')


def stage_setup():
    os.makedirs(PRIVATE, exist_ok=True)
    os.chmod(PRIVATE, 0o700)
    suffix = secrets.token_hex(4)
    creds = {'email': 'latency-test-%s@example.com' % suffix, 'username': 'latencytest%s' % suffix, 'password': secrets.token_urlsafe(18)}
    with open(os.path.join(PRIVATE, 'creds.json'), 'w') as handle:
        json.dump(creds, handle)
    os.chmod(os.path.join(PRIVATE, 'creds.json'), 0o600)
    op, jar = opener()
    status, body = call(op, 'POST', '/api/user/auth/register', {'email': creds['email'], 'password': creds['password'],
                        'password_confirmation': creds['password'], 'display_name': 'Latency Test (disposable)', 'username': creds['username']})
    jar.save(ignore_discard=True, ignore_expires=True)
    os.chmod(jar.filename, 0o600)
    log('register -> HTTP %s' % status)
    if status not in (200, 201):
        sys.exit('registration failed')
    status, _ = call(op, 'POST', '/api/user/profile/visibility', {'is_public': False})
    log('profile set private -> HTTP %s' % status)
    status, page = call(op, 'GET', '/api/movie/movies?offset=0')
    fixed = [m for m in page['movies'] if m.get('year') and m.get('genres')][:5]
    for movie in fixed:
        status, _ = call(op, 'POST', '/api/user/profile/watched/add', {'movie_id': movie['id']})
        log('watched add %s -> HTTP %s' % (movie['title'], status))
    save('fixed_profile.json', {'created_at': now(), 'profile_visibility': 'private', 'watched_movies': [{'id': m['id'], 'title': m['title'], 'year': m['year'], 'genres': m['genres']} for m in fixed]})


def stage_profile():
    """Fix the test account's viewing history: 5 watched movies taken from a fixed catalogue offset (title order), all with genres and a duration (the list endpoint returns year=null)."""
    op, jar = opener()
    status, page = call(op, 'GET', '/api/movie/movies?offset=2500')
    fixed = [m for m in page['movies'] if m.get('genres') and m.get('duration_minutes')][:5]
    added = []
    for movie in fixed:
        status, _ = call(op, 'POST', '/api/user/profile/watched/add', {'movie_id': movie['id']})
        log('watched add -> HTTP %s' % status)
        added.append({'id': movie['id'], 'title': movie['title'], 'genres': movie['genres'], 'duration_minutes': movie['duration_minutes'], 'http': status})
    save('fixed_profile.json', {'created_at': now(), 'profile_visibility': 'private', 'catalogue_offset': 2500, 'watched_movies': added})


SCAN_CODE = r'''
import os, json, itertools
from services.movie_client import fetch_catalog
from services import candidates as c
WATCHED = set(%(watched)s)
cat = fetch_catalog(os.environ['MOVIE_SERVICE_URL'])
def elig(f): return len(c.hard_filter(cat, WATCHED, f))
out = {'catalogue_size': len(cat), 'watched_excluded': len(WATCHED), 'pool_size_5': c.pool_size(5), 'pool_size_20': c.pool_size(20)}
out['broad_eligible'] = elig({})
genres = sorted({g for m in cat for g in m['genres']})
langs = ['English','Portuguese','French','Spanish','German','Italian','Japanese','Korean']
res = []
for g in genres:
    for d in ('any','short','medium','long','epic'):
        n = elig({'genres':[g],'duration':d})
        res.append({'filters':{'genres':[g],'duration':d},'eligible':n})
    for l in langs:
        res.append({'filters':{'genres':[g],'languages':[l]},'eligible':elig({'genres':[g],'languages':[l]})})
        for d in ('short','medium','long'):
            res.append({'filters':{'genres':[g],'languages':[l],'duration':d},'eligible':elig({'genres':[g],'languages':[l],'duration':d})})
out['narrow_options'] = sorted([r for r in res if 8 <= r['eligible'] <= 16], key=lambda r: abs(r['eligible'] - 12))[:25]
print(json.dumps(out))
'''


def eligible_for(filters_list, watched):
    code = ("import os, json\nfrom services.movie_client import fetch_catalog\nfrom services import candidates as c\n"
            "W=set(%s)\ncat=fetch_catalog(os.environ['MOVIE_SERVICE_URL'])\nprint(json.dumps([len(c.hard_filter(cat,W,f)) for f in %s]))\n" % (json.dumps(watched), json.dumps(filters_list)))
    b64 = base64.b64encode(code.encode()).decode()
    return json.loads(sh('echo %s | base64 -d | %s -n %s exec -i deploy/recommendation-service -- python -' % (b64, KC, NS)))


def stage_scan():
    watched = [m['id'] for m in load('fixed_profile.json')['watched_movies']]
    b64 = base64.b64encode((SCAN_CODE % {'watched': json.dumps(watched)}).encode()).decode()
    out = json.loads(sh('echo %s | base64 -d | %s -n %s exec -i deploy/recommendation-service -- python -' % (b64, KC, NS), timeout=300))
    save('candidate_scan.json', out)
    print(json.dumps({k: v for k, v in out.items() if k != 'narrow_options'}))
    for row in out['narrow_options'][:15]:
        print(row)


def parse_llama(slice_text):
    """Extract the (single) completed request from a slice of llama.cpp log lines."""
    info = {}
    m = re.search(r'selected slot by (LCP similarity, f_sim_best = ([\d.]+) .*?f_keep = ([\d.]+)|LRU)', slice_text)
    if m:
        info['slot_selection'] = 'LCP' if m.group(2) else 'LRU'
        info['f_sim_best'] = float(m.group(2)) if m.group(2) else None
        info['f_keep'] = float(m.group(3)) if m.group(3) else None
    m = re.search(r'prompt eval time =\s+([\d.]+) ms /\s+(\d+) tokens \(\s*([\d.]+) ms per token,\s+([\d.]+) tokens per second\)', slice_text)
    if m:
        info.update(prompt_eval_ms=float(m.group(1)), prompt_tokens_processed=int(m.group(2)), prompt_tok_per_s=float(m.group(4)))
    m = re.search(r'\|\s+eval time =\s+([\d.]+) ms /\s+(\d+) tokens \(\s*([\d.]+) ms per token,\s+([\d.]+) tokens per second\)', slice_text)
    if m:
        info.update(gen_ms=float(m.group(1)), generated_tokens=int(m.group(2)), gen_tok_per_s=float(m.group(4)))
    m = re.search(r'total time =\s+([\d.]+) ms /\s+(\d+) tokens', slice_text)
    if m:
        info.update(llama_total_ms=float(m.group(1)), llama_total_tokens=int(m.group(2)))
    m = re.search(r'stop processing: n_tokens = (\d+), truncated = (\d)', slice_text)
    if m:
        info.update(n_tokens_at_release=int(m.group(1)), truncated=int(m.group(2)))
    if 'n_tokens_at_release' in info and 'generated_tokens' in info:
        info['prompt_tokens_total'] = info['n_tokens_at_release'] - info['generated_tokens'] + 1   # n_tokens counts the prompt plus generated tokens (last generated token is not yet in the cache)
        info['prompt_tokens_cached_reused'] = info['prompt_tokens_total'] - info.get('prompt_tokens_processed', 0)
    return info


def wait_for_window(lo=25, hi=60):
    """Start each request shortly after a */3 agent scan (epoch % 180 == 0 at scan time) so deterministic auto jobs do not overlap."""
    while True:
        phase = time.time() % 180
        if lo <= phase <= hi:
            return phase
        time.sleep(1.0)


def stage_run(plan, prefix=''):
    op, jar = opener()
    watched = [m['id'] for m in load('fixed_profile.json')['watched_movies']]
    sets = {name: spec['filters'] for name, spec in {s['case']: s for s in plan}.items()}
    eligibles = dict(zip(sets, eligible_for(list(sets.values()), watched)))
    results = []
    for index, spec in enumerate(plan, 1):
        run = {'run': index, 'case': spec['case'], 'criteria_sent': spec['filters'], 'requested_count': spec['filters']['count'], 'eligible_candidates': eligibles[spec['case']]}
        run['candidate_pool_sent_to_llm'] = min(run['eligible_candidates'], max(30, 2 * run['requested_count']))
        run['window_phase_s'] = round(wait_for_window(), 1)
        run['queued_or_running_before'] = psql("select count(*) from generation_jobs where status in ('queued','running')")
        run['llama_log_lines_before'] = int(sh('%s -n %s logs deploy/inference 2>/dev/null | wc -l' % (KC, NS)).strip() or 0)
        run['rec_logs_since'] = now()
        run['cgroup_before'] = cgroup(); run['cgroup_before_at'] = now()
        t0 = time.monotonic(); run['post_sent_at'] = now()
        status, body = call(op, 'POST', '/api/user/profile/recommendation-generations', {'filters': spec['filters']})
        run['post_status'] = status; run['post_return_s'] = round(time.monotonic() - t0, 3)
        if status != 202:
            run['error'] = body; results.append(run); log('run %d POST failed: %s %s' % (index, status, body)); break
        job_id = body['job_id']; run['job_id'] = job_id
        trace = []; final = None
        while time.monotonic() - t0 < 420:
            s, b = call(op, 'GET', '/api/user/profile/recommendation-generations/' + job_id)
            trace.append((round(time.monotonic() - t0, 2), b.get('status') if b else s))
            if b and b.get('status') in ('succeeded', 'failed'):
                final = b; break
            time.sleep(1.0)
        run['api_completion_s_poll_1s'] = round(time.monotonic() - t0, 2)   # POST sent -> first poll seeing the terminal state (1 s polling + GET latency)
        run['poll_trace_first_last'] = [trace[0], trace[-1]]; run['poll_count'] = len(trace); run['final_status_body_keys'] = sorted(final) if final else None
        run['cgroup_after'] = cgroup(); run['cgroup_after_at'] = now()
        run['cgroup_delta'] = {k: run['cgroup_after'][k] - run['cgroup_before'][k] for k in run['cgroup_before'] if k != 'memory_current_bytes'}
        row = psql("select row_to_json(t) from (select status, to_char(created_at at time zone 'utc','YYYY-MM-DD\"T\"HH24:MI:SS.MS\"Z\"') created_at, to_char(started_at at time zone 'utc','YYYY-MM-DD\"T\"HH24:MI:SS.MS\"Z\"') started_at, to_char(finished_at at time zone 'utc','YYYY-MM-DD\"T\"HH24:MI:SS.MS\"Z\"') finished_at, round(extract(epoch from (started_at-created_at))::numeric,3) queue_wait_s, round(duration_seconds::numeric,3) job_duration_s, round(extract(epoch from (finished_at-created_at))::numeric,3) created_to_finished_s, attempts, outcome, used_fallback, fallback_reason, recommendation_count, criteria from generation_jobs where id='%s') t" % job_id)
        run['job_row'] = json.loads(row)
        status, listing = call(op, 'GET', '/api/user/profile/recommendations?source=user_requested&offset=0')
        run['returned_items_api'] = len(listing.get('items') or listing.get('recommendations') or []) if isinstance(listing, dict) else None
        slice_text = sh('%s -n %s logs deploy/inference 2>/dev/null | tail -n +%d' % (KC, NS, run['llama_log_lines_before'] + 1))
        run['llama'] = parse_llama(slice_text); run['llama_log_slice'] = slice_text.strip().splitlines()
        rec = sh("%s -n %s logs deploy/recommendation-service --since-time=%s 2>/dev/null | grep -iE 'fallback|invalid|valid|retry|timeout|error' | sed -E 's/[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}/<uuid>/g' | head -5" % (KC, NS, run['rec_logs_since'].replace('+00:00', 'Z')))
        run['recommendation_service_warning_lines'] = rec.strip().splitlines()
        results.append(run)
        save('run_%s%02d_%s.json' % (prefix, index, spec['case']), run)
        log('run %s%d %-9s job=%s outcome=%s job=%ss api=%ss' % (prefix, index, spec['case'], job_id[:8], run['job_row'].get('outcome'), run['job_row'].get('job_duration_s'), run['api_completion_s_poll_1s']))
        time.sleep(5)
    save('all_runs%s.json' % (('_' + prefix) if prefix else ''), results)


def stage_report(prefix=''):
    runs = load('all_runs%s.json' % (('_' + prefix) if prefix else ''))
    rows = []
    for r in runs:
        j, l, g = r['job_row'], r['llama'], r['cgroup_delta']
        overhead = round(float(j['job_duration_s']) - l.get('llama_total_ms', 0) / 1000, 2) if l.get('llama_total_ms') else None
        rows.append((r['run'], r['case'], r['requested_count'], r['eligible_candidates'], r['candidate_pool_sent_to_llm'], j['recommendation_count'],
                     j['queue_wait_s'], j['job_duration_s'], r['api_completion_s_poll_1s'], l.get('prompt_tokens_processed'), l.get('prompt_tokens_total'),
                     l.get('prompt_tokens_cached_reused'), l.get('generated_tokens'), l.get('prompt_eval_ms'), l.get('prompt_tok_per_s'), l.get('gen_ms'), l.get('gen_tok_per_s'),
                     l.get('llama_total_ms'), overhead, j['outcome'], j['used_fallback'], j['attempts'], l.get('f_sim_best'), g['nr_throttled'], g['throttled_usec'], g['usage_usec']))
    head = ('run case count eligible pool returned queue_s job_s api_s prompt_proc prompt_total cached gen_tok prompt_ms prompt_tps gen_ms gen_tps llama_total_ms '
            'non_inf_overhead_s outcome fallback attempts f_sim throttled_periods throttled_usec cpu_usage_usec').split()
    save('summary_rows%s.json' % (('_' + prefix) if prefix else ''), {'columns': head, 'rows': rows})
    print('\t'.join(head))
    for row in rows:
        print('\t'.join(str(x) for x in row))


if __name__ == '__main__':
    stage = sys.argv[1]
    if stage == 'env': stage_env()
    elif stage == 'setup': stage_setup()
    elif stage == 'profile': stage_profile()
    elif stage == 'scan': stage_scan()
    elif stage == 'run':
        stage_run(json.load(open(sys.argv[2])), sys.argv[3] if len(sys.argv) > 3 else '')
    elif stage == 'report': stage_report(sys.argv[2] if len(sys.argv) > 2 else '')
    else: sys.exit('unknown stage')
