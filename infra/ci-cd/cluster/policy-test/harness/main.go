package main

import (
	"encoding/json"
	"fmt"
	"os"
	"strings"

	"github.com/google/cel-go/cel"
	"gopkg.in/yaml.v3"
)

type Policy struct {
	Kind string `yaml:"kind"`
	Spec struct {
		MatchConstraints struct {
			ResourceRules []struct {
				Resources []string `yaml:"resources"`
			} `yaml:"resourceRules"`
		} `yaml:"matchConstraints"`
		MatchConditions []struct{ Name, Expression string } `yaml:"matchConditions"`
		Variables       []struct{ Name, Expression string } `yaml:"variables"`
		Validations     []struct{ Expression, Message string } `yaml:"validations"`
	} `yaml:"spec"`
}

type Case struct {
	Name, Kind, User, Op, Expect string
	Old, New                     map[string]interface{}
}

func main() {
	raw, _ := os.ReadFile(func() string { if p := os.Getenv("POLICY"); p != "" { return p }; return "../30-deployer-admission-policy.yaml" }())
	policies := map[string]*Policy{} // by resource
	for _, doc := range strings.Split(string(raw), "\n---\n") {
		var p Policy
		if yaml.Unmarshal([]byte(doc), &p) != nil || p.Kind != "ValidatingAdmissionPolicy" {
			continue
		}
		policies[p.Spec.MatchConstraints.ResourceRules[0].Resources[0]] = &p
	}
	var cases []Case
	b, _ := os.ReadFile("../cases.json")
	if err := json.Unmarshal(b, &cases); err != nil {
		panic(err)
	}
	env, err := cel.NewEnv(cel.OptionalTypes(), cel.Variable("object", cel.DynType), cel.Variable("oldObject", cel.DynType), cel.Variable("request", cel.DynType), cel.Variable("variables", cel.DynType))
	if err != nil {
		panic(err)
	}
	eval := func(expr string, act map[string]interface{}) (interface{}, error) {
		ast, iss := env.Compile(expr)
		if iss.Err() != nil {
			return nil, iss.Err()
		}
		prg, err := env.Program(ast)
		if err != nil {
			return nil, err
		}
		out, _, err := prg.Eval(act)
		if err != nil {
			return nil, err
		}
		return out.Value(), nil
	}
	pass, fail := 0, 0
	for _, c := range cases {
		res := "cronjobs"
		if c.Kind == "deployment" {
			res = "deployments"
		}
		p := policies[res]
		act := map[string]interface{}{"object": c.New, "oldObject": c.Old, "variables": map[string]interface{}{},
			"request": map[string]interface{}{"operation": c.Op, "userInfo": map[string]interface{}{"username": c.User}}}
		decision, why := "allow", ""
		applies := true
		for _, mc := range p.Spec.MatchConditions {
			v, err := eval(mc.Expression, act)
			if err != nil || v != true {
				applies = false
			}
		}
		if applies {
			vars := act["variables"].(map[string]interface{})
			for _, v := range p.Spec.Variables {
				val, err := eval(v.Expression, act)
				if err != nil {
					decision, why = "deny", "variable "+v.Name+": "+err.Error()
					break
				}
				vars[v.Name] = val
			}
			if decision == "allow" {
				for _, v := range p.Spec.Validations {
					val, err := eval(v.Expression, act)
					if err != nil || val != true {
						decision = "deny"
						why = v.Message
						if err != nil {
							why += " [eval error: " + err.Error() + "]"
						}
						break
					}
				}
			}
		}
		if decision == c.Expect {
			pass++
		} else {
			fail++
			fmt.Printf("FAIL %-95s expected=%s got=%s (%s)\n", c.Name, c.Expect, decision, why)
		}
	}
	fmt.Printf("RESULT: %d passed, %d failed, %d total\n", pass, fail, len(cases))
	if fail > 0 {
		os.Exit(1)
	}
}
