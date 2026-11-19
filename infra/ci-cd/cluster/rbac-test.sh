#!/bin/sh
# Runs ON cp1 (admin kubeconfig) after the Role/RoleBinding exist. Pure read-only SubjectAccessReviews via impersonation.
KC="sudo kubectl --kubeconfig=/etc/kubernetes/admin.conf"; SA=system:serviceaccount:g15-cd:ci-deployer; bad=0
t() { exp=$1; shift; got=$($KC auth can-i "$@" --as=$SA 2>/dev/null); [ "$got" = "$exp" ] && s=ok || { s=MISMATCH; bad=1; }; echo "$s  expect=$exp got=$got  : $*"; }
# allowed
for d in frontend proxy user-service movie-service recommendation-service; do t yes patch deployment/$d -n g15-app; t yes update deployment/$d -n g15-app; done
t yes patch cronjob/recommendation-agent -n g15-app
t yes get deployments -n g15-app; t yes list pods -n g15-app; t yes watch replicasets -n g15-app; t yes get cronjobs -n g15-app; t yes get jobs -n g15-app
t yes patch configmap/cd-state -n g15-app; t yes get configmap/cd-state -n g15-app
# denied: everything sensitive. NOTE: subresources MUST be tested with --subresource (kubectl reads 'pods/log' as 'the pod named log')
t no patch deployment/inference -n g15-app; t no delete deployment/frontend -n g15-app; t no create deployments -n g15-app
t no patch deployments --subresource=scale -n g15-app; t no patch deployment/frontend --subresource=scale -n g15-app
t no update deployment/frontend --subresource=status -n g15-app; t no patch deployments --subresource=status -n g15-app
t no create jobs -n g15-app; t no create cronjobs -n g15-app; t no delete cronjob/recommendation-agent -n g15-app; t no patch cronjob/other -n g15-app
t no get secrets -n g15-app; t no list secrets -n g15-app; t no get pods --subresource=log -n g15-app; t no get pod/recommendation-service --subresource=log -n g15-app
t no create pods --subresource=exec -n g15-app; t no create pods --subresource=portforward -n g15-app; t no create pods -n g15-app
t no get persistentvolumeclaims -n g15-app; t no patch statefulsets -n g15-app; t no get statefulsets -n g15-app; t no patch services -n g15-app
t no get networkpolicies -n g15-app; t no patch networkpolicies -n g15-app; t no create configmaps -n g15-app; t no patch configmap/other -n g15-app
t no patch deployment/frontend -n g15-ci; t no get secrets -n g15-ci; t no get pods -n g15-ci; t no get secrets -n g15-cd
t no get nodes; t no list namespaces; t no create clusterrolebindings; t no '*' '*' --all-namespaces
echo; [ $bad -eq 0 ] && echo "RBAC MATRIX OK" || { echo "RBAC MATRIX HAS MISMATCHES"; exit 1; }
