#!/bin/sh
# One dedicated database per service: each Deployment's DB_HOST resolves
# (through the ConfigMap) to its own database, and it references no
# other *_DB_HOST keys.
CHECK_NAME="db-ownership"
. "$TESTS_DIR/lib.sh"
need kubectl
need python3
for triple in "movie-service:MOVIE:movie-db" "recommendation-service:RECOMMENDATION:recommendation-db" "user-service:USER:user-db"; do
  svc=${triple%%:*}; rest=${triple#*:}; prefix=${rest%%:*}; db=${rest##*:}
  keys=$(kubectl -n g15-app get deployment "$svc" -o json 2>/dev/null | python3 -c "
import json,sys
env = json.load(sys.stdin)['spec']['template']['spec']['containers'][0]['env']
print(' '.join(r.get('configMapKeyRef',{}).get('key','') for e in env for r in [e.get('valueFrom',{})] if 'configMapKeyRef' in e.get('valueFrom',{})))
" 2>/dev/null) || fail "cannot read env of $svc"
  case " $keys " in
    *" ${prefix}_DB_HOST "*) ;;
    *) fail "$svc does not reference ${prefix}_DB_HOST" ;;
  esac
  for other in MOVIE RECOMMENDATION USER; do
    if [ "$other" != "$prefix" ]; then
      case " $keys " in
        *" ${other}_DB_HOST "*) fail "$svc references foreign ${other}_DB_HOST" ;;
      esac
    fi
  done
  host=$(kubectl -n g15-app get configmap g15-app-config -o json 2>/dev/null | python3 -c "
import json,sys
print(json.load(sys.stdin)['data'].get('${prefix}_DB_HOST',''))
" 2>/dev/null) || fail "cannot read ConfigMap"
  [ "$host" = "$db" ] || fail "$svc resolves to '$host', want '$db'"
done
n=$(kubectl -n g15-app get statefulset --no-headers 2>/dev/null | grep -cE "^(movie|recommendation|user)-db" || true)
[ "$n" -eq 3 ] || fail "expected 3 database StatefulSets, found $n"
pass "3 dedicated databases, each owned exclusively through resolved config"
