# Contributing to sheppy

## Setup

Requires Python 3.10+ and [uv](https://docs.astral.sh/uv/).

```bash
git clone git@github.com:rammp-org/sheppy.git
cd sheppy
uv sync                  # creates .venv from uv.lock
uv run sheppy examples/local-demo.yaml
```

## Tests

```bash
uv run pytest            # the whole suite
uv run pytest tests/cli  # one area
```

CI runs the suite on Python 3.10 and 3.13 for every pull request.

## Making a change

- `dev` is the default branch and where changes land; `main` holds releases.
  `install.sh` installs the latest release tag by default and `dev` with
  `SHEPPY_REF=dev`. Open a pull request against `dev`; both CI checks must
  pass before it merges.
- A behaviour change needs a test. A bug fix should come with a test that
  fails without the fix.
- Update the docs in the same pull request as the behaviour they describe.

## Releasing

Merge `dev` into `main`, set `sheppy.__version__` in `sheppy/__init__.py`,
and push a `vX.Y.Z` tag that matches it. The tag builds the package and
publishes the GitHub release.

## Documentation

User docs live in `docs/` as MDX. This repo doesn't build a site: the
[rammp-org.github.io](https://github.com/rammp-org/rammp-org.github.io) hub
pulls `docs/` in and publishes it at https://rammp-org.github.io/sheppy. To
preview locally, clone the hub next to this repo and run `npm install` and
`npm run dev` in its `website/` directory; it uses your sibling checkout.

Design records (specs and implementation plans) for larger changes live in
`docs/superpowers/`.

## License

By contributing, you agree that your contributions are licensed under the
[MIT License](LICENSE).
