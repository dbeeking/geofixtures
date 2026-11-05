# Reference data policy

The catalog has no third-party data. Fixtures are generated from code in this repository under the
MIT license.

Rules for adding real data later:

1. Document ownership and redistribution rights first.
2. Record the license in the fixture manifest.
3. Keep annotations and their provenance separate from generation code.
4. Mark annotated truth as `annotated`.
5. Exclude sensitive locations, personal data, and proprietary datasets.
6. Put larger samples in separate versioned archives.
7. Keep downloads off by default, with HTTPS, a host allowlist, byte limits, and checksums.
