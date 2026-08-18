# Sheppy docs site

[Nextra](https://nextra.site) (docs theme) + Next.js, statically exported and
deployed to GitHub Pages at <https://rammp-org.github.io/sheppy> by
`.github/workflows/docs.yml` on every push to `main` that touches `website/`.

Content lives in `content/` as MDX; `_meta.js` files control sidebar order and
titles.

```bash
npm install
npm run dev                          # http://localhost:3000/sheppy
npm run build                        # static export -> out/ (+ pagefind index)
DOCS_BASE_PATH= npm run build && npm start   # preview without the /sheppy prefix
```

Note: `zod` is pinned to 4.1.x via `overrides` — nextra-theme-docs 4.6 breaks
on newer zod (`Layout` validates its props after stripping `children`, and
zod ≥4.2 rejects the missing key).
