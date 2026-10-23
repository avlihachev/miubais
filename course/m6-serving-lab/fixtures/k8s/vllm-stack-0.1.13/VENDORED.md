# Vendored chart: vllm-stack 0.1.13

- Source: the vLLM production stack Helm repository, pulled on 2026-10-22 with
  `helm repo add vllm https://vllm-project.github.io/production-stack` and
  `helm pull vllm/vllm-stack --version 0.1.13 --untar`.
- Upstream: https://github.com/vllm-project/production-stack (chart under `helm/`).
- Licence: Apache-2.0, per the LICENSE file in the production-stack repository.
- Changes from the pulled chart:
  - `charts/` held the three optional dependencies (kube-prometheus-stack 82.4.3,
    prometheus-adapter 5.3.0, k8s-aibom 1.5.1, about 7.2 MB). They are removed. Helm refuses to
    render a chart whose `Chart.yaml` lists a dependency missing from `charts/`, even when its
    condition is false, so each one is replaced by a placeholder `charts/<name>/Chart.yaml` with
    the same name and version and no templates. Enabling one renders nothing here.
  - `Chart.yaml`, `Chart.lock`, `values.yaml`, `templates/` and the rest are unchanged.
- The course's values files set `kube-prometheus-stack.enabled`, `prometheus-adapter.enabled`
  and `k8s-aibom.enabled` to `false` explicitly.
- Rendering is offline: `serving_lab.k8s.render` runs `helm template` against this directory
  with a throwaway repository config and cache.
