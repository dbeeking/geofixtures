# Security

Report vulnerabilities through GitHub's private vulnerability reporting.

In scope: a manifest that reaches outside its fixture root, a file that bypasses checksum validation,
or a way around generation limits.

Adapters run with your user's permissions, and loading one by module path runs its code. A worker uses
pickle to receive its adapter, from a private run folder. The offline guard is best-effort. See
[docs/reproducibility.md](docs/reproducibility.md).
