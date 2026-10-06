"""
text_cleaner.py — Universal HTML to Clean Markdown / Text Sanitizer
====================================================================
Strips all raw HTML tags, unescapes entities (&lt;, &gt;, &quot;, &amp;, &nbsp;),
normalizes lists and headings, and guarantees zero residual HTML artifacts (<h2>, <div>, etc.).
"""

import html
import re
from bs4 import BeautifulSoup


def clean_html_to_markdown(raw_html: str) -> str:
    """
    Cleans raw HTML or unescaped entity-encoded strings into human-readable,
    properly-spaced markdown text without any residual HTML tags.
    """
    if not raw_html or not isinstance(raw_html, str):
        return ""

    try:
        # 1. Unescape HTML entities (e.g. &lt;div&gt; -> <div>, &amp; -> &, &quot; -> ", &#39; -> ')
        unescaped = html.unescape(raw_html)
        
        # In case double-encoded (e.g. &amp;lt;div&amp;gt;)
        if "&lt;" in unescaped or "&gt;" in unescaped or "&amp;" in unescaped:
            unescaped = html.unescape(unescaped)

        soup = BeautifulSoup(unescaped, "html.parser")

        # 2. Decompose all junk / metadata elements
        for junk in soup(["script", "style", "svg", "noscript", "iframe", "head", "meta", "link", "form", "button"]):
            junk.decompose()

        # 3. Format list items with standard bullet points
        for li in soup.find_all("li"):
            li.insert_before("\n• ")
            li.insert_after("\n")

        # 4. Handle line breaks
        for br in soup.find_all("br"):
            br.replace_with("\n")

        # 5. Format headings and block containers with clear paragraph breaks
        for h in soup.find_all(["h1", "h2", "h3", "h4", "h5", "h6"]):
            h_text = h.get_text().strip()
            if h_text:
                h.insert_before(f"\n\n### {h_text}\n")
                h.decompose()

        for block in soup.find_all(["p", "div", "article", "section", "tr", "blockquote"]):
            block.insert_after("\n")

        # 6. Extract text
        text = soup.get_text()

        # 7. Regex safety pass: eliminate any leftover XML/HTML tags
        text = re.sub(r'<[^>]+>', ' ', text)

        # 8. Clean up whitespace: normalize tabs/spaces and limit consecutive blank lines
        text = re.sub(r'[ \t]+', ' ', text)
        text = re.sub(r'\n[ \t]+', '\n', text)
        text = re.sub(r'\n{3,}', '\n\n', text)

        return text.strip()
    except Exception:
        # Fallback regex stripper
        cleaned = re.sub(r'<[^>]+>', ' ', raw_html)
        return html.unescape(re.sub(r'\s+', ' ', cleaned)).strip()
