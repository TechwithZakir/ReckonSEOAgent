# Reckon SEO Connector (WordPress plugin)

A small plugin that gives Reckon four SEO fields it can change safely, instead of depending on
a third-party SEO plugin.

| Post meta key | Output |
| --- | --- |
| `reckon_seo_title` | Document `<title>` (replaces the theme/core title when set) |
| `reckon_seo_description` | `<meta name="description">` |
| `reckon_seo_canonical` | `<link rel="canonical">` (replaces core's, never duplicated) |
| `reckon_seo_schema` | One `application/ld+json` block (JSON only, tags escaped) |

Fields are registered for posts and pages with `show_in_rest`, so Reckon reads and writes them
through the normal `wp/v2/posts|pages/{id}` endpoint as `meta.{key}` by a user who can edit
the post. The plugin adds no route of its own and no unauthenticated write path. Values are
sanitized on save and escaped on output, and nothing is printed for an unset field.

## Install (staging first)

1. Copy this folder to `wp-content/plugins/reckon-seo-connector/` and activate it.
2. Create an Application Password for a user who can edit the target posts.
3. Set in Reckon: `RECKON_CMS_WORDPRESS_SEO_CONNECTOR=true` together with the existing WordPress
   execution settings. Without it, only `heading` is executable.

## Compatibility

Run only one plugin that prints the title, description or canonical for the same page. If an
SEO plugin such as Yoast or Rank Math is active, it may print its own tags in addition to
these; check the live page, which is what Reckon verifies.

## Status

Not yet run on a real WordPress site, and not PHP-linted in this repository's environment.
Activate it on staging and run the drill before relying on it.
