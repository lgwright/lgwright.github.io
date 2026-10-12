"""Build the LGW Lab blog into site/.

    python build.py                    # production build (posts marked `draft: true` left out)
    python build.py --drafts           # include drafts (marked "draft" on the page)
    python build.py --drafts --from DIR
                                       # also build every *.md in DIR (read only), with its
                                       # assets in DIR/<slug>/; DIR posts win over posts/ ones

Adapted from the build of jinchen-zhao.github.io, so one Markdown file builds the same
way in both places: pandoc (Markdown, citeproc) with filters/figures.lua and
filters/gallery.lua, then Jinja templates. Needs Python with jinja2 and pyyaml, and
pandoc >= 3 on PATH (or $PANDOC). A post with TeX math also needs Node and `npm install`
(mathjax.mjs renders it to static HTML).
"""

import argparse
import colorsys
import datetime as dt
import hashlib
import html
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import jinja2
import yaml

import sitekit

ROOT = Path(__file__).resolve().parent
POSTS = ROOT / "posts"          # YYYY-MM-DD-slug.md, assets in posts/<slug>/
STATIC = ROOT / "static"        # copied verbatim to the site root
OUT = ROOT / "site"


def pandoc_bin():
    if os.environ.get("PANDOC"):
        return os.environ["PANDOC"]
    found = shutil.which("pandoc")
    if found:
        return found
    local = Path(os.environ.get("LOCALAPPDATA", "")) / "Pandoc" / "pandoc.exe"
    if local.exists():
        return str(local)
    sys.exit("pandoc not found: install it or set $PANDOC")


def pandoc(args, text, cwd):
    r = subprocess.run([pandoc_bin(), *args], input=text, capture_output=True,
                       text=True, encoding="utf-8", cwd=cwd)
    if r.returncode:
        sys.exit(f"pandoc failed:\n{r.stderr}")
    if r.stderr.strip():
        print(r.stderr.strip(), file=sys.stderr)
    return r.stdout


def read_post(path, site):
    raw = path.read_text(encoding="utf-8").replace("\r\n", "\n")
    m = re.match(r"^---\n(.*?)\n---\n", raw, re.S)
    if not m:
        sys.exit(f"{path.name}: missing front matter")
    meta = yaml.safe_load(m.group(1))
    date = meta["date"]
    if isinstance(date, str):
        date = dt.date.fromisoformat(date)
    slug = meta.get("slug") or re.sub(r"^\d{4}-\d{2}-\d{2}-", "", path.stem)
    # The bibliography and citation style sit next to the post, else in posts/.
    def shared(name):
        return path.parent / name if (path.parent / name).exists() else POSTS / name
    args = ["-f", "markdown+tex_math_dollars+raw_tex", "-t", "html5",
            "--math-method=mathjax", "--wrap=none", "--section-divs",
            "--lua-filter", str(ROOT / "filters" / "gallery.lua"),
            "--lua-filter", str(ROOT / "filters" / "figures.lua"),
            "--citeproc", "--bibliography", str(shared("refs.bib")), "--csl", str(shared("aps.csl")),
            "--metadata", "link-citations=true",
            "--metadata", "reference-section-title=",
            "--syntax-highlighting=pygments"]
    if meta.get("toc"):
        args += ["--toc", "--toc-depth=2", "--template", str(ROOT / "templates" / "pandoc-body.html")]
    body = pandoc(args, raw, cwd=path.parent)
    toc = ""
    if meta.get("toc"):
        toc, _, body = body.partition("<!--BODY-->")
    # Authors' <!-- notes --> in the Markdown pass through pandoc into the HTML,
    # where any reader can see them with View Source. Drop them.
    body = re.sub(r"<!--.*?-->\n?", "", body, flags=re.S)
    authors = meta.get("authors") or [site["default_author"]]
    if isinstance(authors, str):
        authors = [authors]
    image = meta.get("image")
    if image and image.lower().endswith(".svg"):
        png = image[:-4] + ".png"
        image = png if (path.parent / slug / png).exists() else None
    return {
        "title": meta["title"], "date": date, "slug": slug,
        "summary": meta.get("summary", ""), "draft": bool(meta.get("draft")),
        "toc": toc.strip(), "body": body, "url": f"/{slug}/",
        "src": path, "dir": path.parent, "authors": authors,
        "affiliation": meta.get("affiliation", ""), "doi": meta.get("doi", ""),
        "image": f"/{slug}/{image}" if image else None,
    }


def surname_first(name):
    parts = name.split()
    return f"{parts[-1]}, {' '.join(parts[:-1])}" if len(parts) > 1 else name


def citation(post, site):
    """The "Cite as" line and BibTeX for a post."""
    host = site["url"].split("//", 1)[1]
    url = site["url"] + post["url"]
    d = post["date"]
    names = [surname_first(post["authors"][0])] + post["authors"][1:]
    who = names[0] if len(names) == 1 else ", ".join(names[:-1]) + (", and " if len(names) > 2 else " and ") + names[-1]
    title_word = re.sub(r"[^a-z0-9]", "", post["title"].split()[0].lower()) or "post"
    key = f"{re.sub(r'[^a-z]', '', post['authors'][0].split()[-1].lower())}{d.year}{title_word}"
    line = f"{who}. ({d.strftime('%b %Y')}). {post['title']}. {host}. "
    line += f"https://doi.org/{post['doi']}" if post["doi"] else url
    fields = [("title", post["title"]),
              ("author", " and ".join(surname_first(a) for a in post["authors"])),
              ("journal", host), ("year", str(d.year)), ("month", d.strftime("%b")),
              ("url", url)]
    if post["doi"]:
        fields.append(("doi", post["doi"]))
    width = max(len(k) for k, _ in fields)
    bib = f"@article{{{key},\n" + ",\n".join(
        f"  {k.ljust(width)} = {{{v}}}" for k, v in fields) + "\n}"
    return line, bib


# SVGs drawn by the schematic-figure skill (root element carries data-name) use one
# shared palette. The blog is light only, like the lab website. So each SVG gets only
# the light rules below, injected as CSS, and never turns dark inside <img>.
# Light mode deepens the two role hues to reach 3:1 contrast on white.
SVG_LIGHT = {
    "#3A8FD0": "#2F80C4",
    "#D9822B": "#C8701C",
}


def theme_svg(path):
    # sitekit.py (an exact copy of the personal site's file) also adds dark rules. The blog uses only its
    # light colour map.
    svg = path.read_text(encoding="utf-8")
    style = f"<style>{sitekit.recolour(SVG_LIGHT)}</style>"
    svg = re.sub(r"(<svg\b[^>]*>)", lambda m: m.group(1) + style, svg, count=1)
    path.write_text(svg, encoding="utf-8")


def external_links_new_tab(html_text, own):
    """Links to other sites open in a new tab. Links to this blog and to the lab
    website (`own`, a tuple of URL prefixes) keep the same tab."""
    def fix(m):
        tag = m.group(0)
        href = re.search(r'href="([^"]*)"', tag)
        if not href or "target=" in tag:
            return tag
        url = href.group(1)
        external = url.startswith(("http://", "https://")) and not url.startswith(own)
        if external or url.lower().endswith(".pdf"):
            return tag[:-1] + ' target="_blank" rel="noopener">'
        return tag
    return re.sub(r"<a\b[^>]*>", fix, html_text)


# AI suggestions: text that an agent puts into a post is marked with the Pandoc class `ai`,
# as a fenced div (::: {.ai}) or a span ([text]{.ai}). The author accepts or rejects each
# one in the personal site's editor. A post that is not a draft must not keep a marker.
AI_MARK = re.compile(r'<(?:div|span)\b[^>]*\bclass="(?:[^"]*\s)?ai(?:\s[^"]*)?"')
AI_CSS = (".ai{--ai:#c62828;--ai-bg:rgba(198,40,40,.08)}"
          "div.ai{background:var(--ai-bg);border-left:3px solid var(--ai);padding:.5em .9em;border-radius:0 4px 4px 0}"
          "span.ai{background:var(--ai-bg);text-decoration:underline 2px var(--ai);text-underline-offset:.2em;"
          "-webkit-box-decoration-break:clone;box-decoration-break:clone}")


def check_ai_markers(posts):
    """Stop the build when a post that is not a draft still holds AI suggestions."""
    bad = [Path(p["src"]).name for p in posts if not p["draft"] and AI_MARK.search(p["body"] + p["toc"])]
    if bad:
        sys.exit("build stopped: these posts are not drafts but still have AI suggestions (.ai markers): "
                 + ", ".join(bad) + ". Accept or reject each suggestion in the editor, or set draft: true.")


def atom_feed(site, posts):
    now = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    items = []
    for p in posts[:20]:
        ts = f"{p['date'].isoformat()}T00:00:00Z"
        items.append(
            f"<entry><title>{html.escape(p['title'])}</title>"
            f"<link href=\"{site['url']}{p['url']}\"/><id>{site['url']}{p['url']}</id>"
            f"<updated>{ts}</updated>"
            + "".join(f"<author><name>{html.escape(a)}</name></author>" for a in p["authors"])
            + f"<summary>{html.escape(p['summary'])}</summary>"
            f"<content type=\"html\">{html.escape(p['body'])}</content></entry>")
    return ("<?xml version=\"1.0\" encoding=\"utf-8\"?>"
            "<feed xmlns=\"http://www.w3.org/2005/Atom\">"
            f"<title>{html.escape(site['name'])}</title>"
            f"<link href=\"{site['url']}/\"/><link rel=\"self\" href=\"{site['url']}/feed.xml\"/>"
            f"<id>{site['url']}/</id><updated>{now}</updated>"
            f"<author><name>{html.escape(site['lab'])}</name></author>"
            f"<rights>{html.escape(site['license']['name'])}: {site['license']['url']}</rights>"
            + "".join(items) + "</feed>\n")


def empty_dir(d):
    # Empty site/ rather than delete it: on Windows a running preview server
    # holds the directory open and rmtree fails.
    if not d.exists():
        return
    for f in d.rglob("*"):
        if f.is_file():
            f.unlink()
    for sub in sorted((s for s in d.rglob("*") if s.is_dir()), key=lambda s: len(s.parts), reverse=True):
        try:
            sub.rmdir()
        except OSError:
            pass


def build(drafts, extra):
    site = yaml.safe_load((ROOT / "site.yaml").read_text(encoding="utf-8"))

    files = {f.name: f for f in sorted(POSTS.glob("*.md"))}
    if extra:
        # *.agent.md are reference drafts in the personal site's drafts folder: never built.
        files.update({f.name: f for f in sorted(Path(extra).glob("*.md"))
                      if not f.name.endswith(".agent.md")})
    posts = [read_post(f, site) for f in files.values()]
    check_ai_markers(posts)
    for p in posts:
        p["cite_line"], p["bibtex"] = citation(p, site)
    posts = [p for p in posts if drafts or not p["draft"]]
    posts.sort(key=lambda p: p["date"], reverse=True)

    env = jinja2.Environment(loader=jinja2.FileSystemLoader(ROOT / "templates"),
                             autoescape=jinja2.select_autoescape(["html"]))
    env.filters["longdate"] = lambda d: f"{d.day} {d.strftime('%B %Y')}"
    # Fingerprint the stylesheet so browsers fetch it again whenever it changes.
    css_v = hashlib.sha1((STATIC / "style.css").read_bytes()
                         + (STATIC / "gallery.js").read_bytes()).hexdigest()[:8]
    # The visit counter. Only the deploy workflow sets GOATCOUNTER, so previews never count.
    site["goatcounter"] = os.environ.get("GOATCOUNTER", "")
    ctx = {"site": site, "year": dt.date.today().year, "css_v": css_v}

    empty_dir(OUT)
    shutil.copytree(STATIC, OUT, dirs_exist_ok=True)
    (OUT / ".nojekyll").write_text("")
    # GitHub Pages reads a custom domain from this file. A github.io address needs none.
    host = site["url"].split("//", 1)[1]
    if not host.endswith(".github.io"):
        (OUT / "CNAME").write_text(host + "\n")

    own = (site["url"], site["lab_url"].rstrip("/"))

    def write(rel, text):
        dest = OUT / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        if rel.endswith(".html"):
            text = external_links_new_tab(text, own)
        dest.write_text(text, encoding="utf-8")
        return dest

    write("index.html", env.get_template("home.html").render(**ctx, posts=posts, page="home"))
    math_pages = []
    for p in posts:
        page_html = env.get_template("post.html").render(**ctx, post=p, page="post")
        if p["draft"] and AI_MARK.search(p["body"]):
            # Only a draft can hold AI suggestions: its page gets the red styling in its head.
            page_html = page_html.replace("</head>", f"<style>{AI_CSS}</style></head>", 1)
        dest = write(f"{p['slug']}/index.html", page_html)
        if 'class="math' in p["body"]:
            math_pages.append(str(dest))
        assets = p["dir"] / p["slug"]
        if assets.is_dir():
            shutil.copytree(assets, OUT / p["slug"], dirs_exist_ok=True)
            for svg in (OUT / p["slug"]).rglob("*.svg"):
                if re.search(r"<svg\b[^>]*\bdata-name=", svg.read_text(encoding="utf-8")[:2000]):
                    theme_svg(svg)
    write("404.html", env.get_template("404.html").render(**ctx, page="404"))
    write("feed.xml", atom_feed(site, [p for p in posts if not p["draft"]]))

    if math_pages:
        if not (ROOT / "node_modules" / "mathjax-full").is_dir():
            sys.exit("a post has math: run `npm install` once, then build again")
        r = subprocess.run(["node", str(ROOT / "mathjax.mjs"), *math_pages])
        if r.returncode:
            sys.exit("MathJax rendering failed")

    print(f"built {OUT} ({len(posts)} post(s), {len(math_pages)} with math)")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--drafts", action="store_true", help="include posts marked draft: true")
    ap.add_argument("--from", dest="extra", metavar="DIR",
                    help="also build the posts in DIR (for example the personal site's drafts)")
    a = ap.parse_args()
    import sync_shared
    stale = sync_shared.stale()
    if stale:
        print("warning: shared code out of date: " + ", ".join(stale) + " (run python sync_shared.py)", file=sys.stderr)
    build(a.drafts, a.extra)
