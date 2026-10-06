from truthtrace.sources.html import container_text, find_typed, first_heading, meta_content

PAGE = """<html><head>
<script type="application/ld+json">{"@type": ["Article"], "headline": "H"}</script>
<script type="application/ld+json">not json</script>
<meta name="description" content="Tom &amp; Jerry">
</head><body><h1 class="t">Hello <em>world</em></h1>
<div class="box"><p>One <a href="#">link</a>.</p><img src="a.png" alt="x"><p>Two</p></div>
<div class="other"><p>Outside</p></div></body></html>"""


def test_jsonld_meta_heading_and_container_text():
    assert find_typed(PAGE, "Article")[0]["headline"] == "H"
    assert meta_content(PAGE, "description") == "Tom & Jerry"
    assert first_heading(PAGE) == "Hello world"
    assert container_text(PAGE, "box") == ["One link.", "Two"]
    assert container_text(PAGE, "missing") == []
