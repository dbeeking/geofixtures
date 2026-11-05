# Quickstart

A custom adapter for a small overlap function. From the repository root:

```bash
pip install -e '.[vector,pytest]'
cd examples/quickstart
pytest -q
PYTHONPATH=. geofixtures run --adapter my_adapter:OverlapAdapter --select vector.overlap.001 --report report.json
geofixtures report report.json
```
