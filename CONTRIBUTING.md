# Contributing

Start from a bug with a reproduction or an enhancement with acceptance criteria.
Discuss new runtime dependencies, storage backends, or public contract changes in
an issue before a large implementation. Small fixes can go directly to a pull request.

Use a branch and a small, reviewable diff. Explain the behavior, why it changes,
how it was verified, and remaining limits. Include negative cases for policy and
coordination changes. Keep human-authored tests and contracts reviewable when AI
assists with the implementation.

```sh
python -m pip install -e '.[dev]'
python -m unittest discover -s tests -v
awh check examples/minimal
python -m build
```

Public contracts currently have schema_version `1`. Breaking changes need an
explicit migration plan and schema version decision. An adapter must declare its
runner/version and pass conformance tests before compatibility is advertised.

Do not submit third-party code or content without permission and attribution.
Keep all examples synthetic. Contributions are under this repository's Apache-2.0
license. Be respectful, discuss behavior rather than people, and avoid private
customer data in issues or pull requests.
