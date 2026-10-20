# Ollama Qualification

The **Check Model** button is a one-card smoke test. It cannot qualify a model. For a local, repeatable evidence report, run:

```bash
/Library/Frameworks/Python.framework/Versions/3.13/bin/python3 -m scripts.qualify_ollama_model --model llama3.1:8b --output artifacts/copilot-benchmarks/llama3.1-8b.json
```

Use the same dependency-equipped Python interpreter as the desktop launcher; the path above is the one currently available on this Mac. This runs 20 fixed planner cases and 20 fixed analyst cases three times each on the current machine. The report records pass/fail by case, security screening, overall/fidelity rates, and median/p95 elapsed time. It does not fetch private provider data, pull models, update settings, or qualify anything automatically. Run it only when Ollama is available; the complete run can take several minutes. The benchmark fixture is still a screening suite: its automatic gates are not a full semantic fact audit or proof of betting accuracy.

Before approving a role, review failed and passing answers against evidence, confirm zero invented player/offer/probability claims, compare it against the existing model on the same hardware, and inspect latency. Only then create an explicit JSON registry file outside the Git repository. The report path must be absolute; compute its SHA-256 after the final report is saved. Example structure:

```json
{
  "schema_version": 1,
  "qualified_models": {
    "planner": {
      "model": "llama3.1:8b",
      "benchmark_version": "copilot-fixed-v2",
      "benchmark_report_path": "/absolute/path/to/llama3.1-8b.json",
      "benchmark_report_sha256": "64-lowercase-hex-characters-from-shasum-256",
      "hardware_profile": "Darwin-arm64-local-host-hash",
      "automatic_gates_passed": true,
      "fact_audit_passed": true,
      "baseline_comparison_passed": true,
      "manually_approved": true,
      "approved_by": "Reviewer name",
      "approved_at": "2026-10-14T12:00:00+00:00"
    }
  }
}
```

The example is a template, not an approval. Copy the exact hardware profile from the report; it includes a short hash of the local hostname without exposing the name. The registry verifies the report hash, model, role, benchmark version, hardware label, case coverage, and three-repetition gate. It fails closed on missing or invalid evidence. To use a reviewed registry, set `EDGEIQ_OLLAMA_USE_QUALIFIED_ROLES=true` and `EDGEIQ_OLLAMA_QUALIFICATION_FILE=/absolute/path/to/registry.json`. Explicit `OLLAMA_PLANNER_MODEL` or `OLLAMA_ANALYST_MODEL` settings override the registry; otherwise the app retains its existing `OLLAMA_MODEL` fallback. Vision is not covered. No benchmark or approval changes the statistical forecasts or paid-entry release gates.

Version `copilot-fixed-v2` preserves a security case's category when a model call fails and reports bounded outcomes such as `runtime_fallback` and `forbidden_claim`. A fallback protects the user but does not qualify the model. Reports from `copilot-fixed-v1` cannot activate a role under the v2 registry check.
