#!/usr/bin/env python3
"""Site Usability Review: a website scanner focused on older adults.

Scans a small business website for problems that make it hard to use,
especially for older customers, and writes a review page for you to work through.

    python checkup.py https://example.com
    python checkup.py https://example.com --pages 8
    python checkup.py --list prospects.txt        (one address per line; writes summary.csv)

Output goes to out/<site>/<date>/review.html. Open that file in a browser.

Uses only the Python standard library. Outside services it contacts:
  - the site being scanned
  - Google PageSpeed Insights (runs Lighthouse; set PSI_API_KEY for a free, reliable quota)
  - dns.google (public mail records for the site's domain)
"""
import argparse
import csv
import datetime as dt
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse as up
import urllib.request as ur
import urllib.robotparser
from concurrent.futures import ThreadPoolExecutor
from html.parser import HTMLParser
from pathlib import Path

VERSION = "0.3"
UA = "site-usability-review/" + VERSION + " (low-volume manual review tool; +https://github.com/trevinp/site-usability-review)"
TIMEOUT = 20
HERE = Path(__file__).resolve().parent

# ---------------------------------------------------------------------------
# Plain-English wording for each finding.
# confidence "confirmed" = the scanner is reliable here; you can still drop it.
# confidence "check"     = YOUR CALL. It stays out of the report until you verify it.
# ---------------------------------------------------------------------------
A_SEE, A_NAV, A_FORM, A_SPEED, A_TRUST, A_MAIL, A_OTHER = (
    "Reading and seeing", "Finding your way around", "Forms and buttons",
    "Speed", "Trust and reliability", "Email", "Other technical findings")
A_MEDIA = "Video and sound"

KB = {
    "zoom-blocked": (A_SEE, "Visitors cannot zoom in on a phone",
        "The site switches off pinch-to-zoom. People with weaker eyesight rely on zooming to read small text.",
        "Remove the zoom limit from the page's viewport setting. This is a one-line change.",
        "high", "confirmed", ""),
    "meta-viewport": (A_SEE, "The site is not set up to fit phone screens properly",
        "Without the right setting, phones show a shrunken desktop page, or stop people zooming in.",
        "Add a standard viewport setting that allows zooming.",
        "high", "confirmed", ""),
    "color-contrast": (A_SEE, "Some text is too faint against its background",
        "Pale grey or coloured text is hard to read for anyone over 50, and harder still outdoors on a phone.",
        "Darken the text colour or lighten the background until it meets the standard contrast level.",
        "high", "confirmed", "Open the page and look at the listed items. Drop this if they are only decorative."),
    "small-text": (A_SEE, "Some text may be too small to read comfortably",
        "The site's style rules include text sizes under 14 pixels. Small print is the most common complaint from older readers.",
        "Raise body text to at least 16 pixels and anything else people must read to at least 14.",
        "med", "check",
        "The scanner only sees the style rules, not where they are used. Open the site and look for small text people must read (menus, footers, form hints, prices). Keep this only if you find some."),
    "image-alt": (A_SEE, "Some pictures have no text description",
        "People who use a screen reader hear nothing for these pictures, so they miss whatever the picture says.",
        "Add a short description to each meaningful picture, and mark purely decorative ones as decorative.",
        "med", "confirmed", ""),
    "reading-level": (A_SEE, "The wording may be harder to read than it needs to be",
        "Long sentences and long words slow everyone down. Plain wording helps customers find what they need.",
        "Shorten sentences and swap jargon for everyday words on the main pages.",
        "low", "check",
        "This is a rough formula, not a judgement. Read the home page yourself. Keep this only if the wording really is heavy going."),
    "html-has-lang": (A_NAV, "The pages do not say what language they are in",
        "Screen readers use this to choose the right voice and pronunciation.",
        "Add the language setting to the page template. This is a one-line change.",
        "low", "confirmed", ""),
    "document-title": (A_NAV, "A page has no title",
        "The title is what shows in the browser tab, in bookmarks and in search results.",
        "Give every page a short, specific title.",
        "med", "confirmed", ""),
    "heading-order": (A_NAV, "Headings are out of order",
        "Screen reader users move through a page by its headings. Missing or skipped heading levels make the page hard to follow.",
        "Use one main heading per page and keep the levels in order beneath it.",
        "low", "confirmed", ""),
    "link-name": (A_NAV, "Some links have no readable name",
        "A link that is only an icon or picture, with no text behind it, is announced as just \"link\" by a screen reader.",
        "Give each link a text name that says where it goes.",
        "med", "confirmed", ""),
    "label-content-name-mismatch": (A_NAV, "Some links and buttons have a hidden name that does not match what they say on screen",
        "People who control their device by voice say the words they can see. If the hidden name is different, the command does not work.",
        "Make the hidden name start with the same words that are shown on screen, or remove it and let the visible text do the job.",
        "low", "check",
        "A minor point that mainly affects voice-control users. Include it only if the report is short, or if the business has customers likely to use voice control."),
    "justified-text": (A_SEE, "Some text may be set in justified columns",
        "Justified text has uneven gaps between words, which makes lines harder to follow, especially when zoomed in.",
        "Align body text to the left.",
        "low", "check",
        "The style rules ask for justified text somewhere. Look at the main pages. Keep this only if paragraphs people read are justified."),
    "all-caps": (A_SEE, "Some text is written in all capitals",
        "Words in capitals all have the same outline, so they are slower to read, and a screen reader may spell them out letter by letter.",
        "Use ordinary upper and lower case, and bold for emphasis.",
        "low", "check",
        "Short headings and buttons in capitals are fine. Keep this only if whole sentences or paragraphs are in capitals."),
    "tight-lines": (A_SEE, "Lines of text may be set too close together",
        "Tightly packed lines are hard to follow from one to the next.",
        "Set line spacing to about one and a half times the text size.",
        "low", "check",
        "The style rules set a tight line height for body text. Look at a long paragraph and judge whether it feels cramped."),
    "underline-not-link": (A_NAV, "Some underlined text is not a link",
        "People expect underlined words to be clickable, and will try to click them.",
        "Use bold for emphasis and keep underlining for links.",
        "low", "confirmed", ""),
    "links-not-underlined": (A_NAV, "Links inside text may be hard to tell apart from ordinary words",
        "A link shown only by a change of colour is easy to miss, particularly for anyone whose colour vision has changed with age.",
        "Underline links that sit inside paragraphs.",
        "med", "check",
        "Look at a paragraph that contains a link. Keep this if the link is hard to spot without hovering over it."),
    "new-window": (A_NAV, "Some links open a new window without saying so",
        "A new window or tab breaks the Back button, which leaves less confident users stranded.",
        "Let links open in the same window, or add \"(opens in a new tab)\" to the link text.",
        "low", "check",
        "Very common on links to other websites. Include it only if it happens on links within the site itself, or if the report is short."),
    "no-search": (A_NAV, "There is no search box or site map",
        "When a menu does not make sense to someone, search or a site map gives them a second way to find a page.",
        "Add a simple search box or a site map page.",
        "low", "check",
        "Only worth raising on a larger site. On a site of a few pages, drop it."),
    "video-captions": (A_MEDIA, "Videos may have no captions",
        "Hearing loss is the most common change with age. Without captions, those customers miss what the video says.",
        "Add captions to each video, and a written transcript where you can.",
        "med", "check",
        "Play each video and switch captions on. Automatic captions full of mistakes do not count. Silent background videos need none: drop this if that is all there is."),
    "vague-links": (A_NAV, "Some links just say \"click here\" or \"read more\"",
        "Out of context these links say nothing about where they lead, which is confusing for screen reader users and for anyone skimming.",
        "Reword each link to say what it opens, such as \"See our opening hours\".",
        "low", "confirmed", ""),
    "no-phone-link": (A_NAV, "The phone number cannot be tapped to call",
        "Many older customers would rather call than fill in a form. On a phone, a tappable number saves them copying it down.",
        "Turn the phone number into a call link wherever it appears.",
        "med", "check",
        "The scanner found what looks like a phone number but no call link. Confirm on the site that it is a real customer phone number."),
    "broken-internal-links": (A_NAV, "Some links on the site lead to missing pages",
        "A dead link makes a customer wonder whether the business is still running.",
        "Fix or remove each broken link listed.",
        "high", "confirmed", "Click one or two of the listed links to be sure they are still broken today."),
    "broken-external-links": (A_NAV, "Some links to other websites no longer work",
        "Dead outside links make the site look out of date.",
        "Update or remove each one.",
        "low", "confirmed", "Click the listed links. Some sites block scanners but work fine for people."),
    "label": (A_FORM, "Some form boxes have no label",
        "Without a label, a screen reader cannot say what the box is for. Hint text inside the box disappears as soon as someone starts typing.",
        "Add a visible label to every box in every form.",
        "high", "confirmed", ""),
    "select-name": (A_FORM, "Some drop-down lists have no label",
        "A screen reader cannot say what the list is for.",
        "Add a visible label to each drop-down list.",
        "med", "confirmed", ""),
    "button-name": (A_FORM, "Some buttons have no readable name",
        "An icon-only button is announced as just \"button\" by a screen reader.",
        "Give each button a text name that says what it does.",
        "med", "confirmed", ""),
    "target-size": (A_FORM, "Some buttons and links are too small or too close together to tap",
        "Small tap targets are hard for anyone with less steady hands, and lead to tapping the wrong thing.",
        "Make tap targets larger and add space between them.",
        "med", "confirmed", ""),
    "autoplay": (A_TRUST, "Sound or video starts playing by itself",
        "Media that starts on its own is startling and can drown out a screen reader.",
        "Switch off autoplay and let the visitor press play.",
        "med", "check", "Open the page and confirm something really does play by itself with sound or movement."),
    "no-https": (A_TRUST, "The site is not served securely",
        "Browsers show a \"Not secure\" warning, which worries cautious customers, with good reason.",
        "Turn on HTTPS with the web host. It is usually free.",
        "high", "confirmed", ""),
    "no-https-redirect": (A_TRUST, "The old insecure address does not pass visitors on to the secure one",
        "Anyone using an old link or bookmark sees a \"Not secure\" warning.",
        "Set the web host to redirect every visitor to the secure address.",
        "med", "confirmed", ""),
    "slow-load": (A_SPEED, "The main page is slow to appear on a phone",
        "A slow page makes people give up, especially on an older phone or a weak signal.",
        "Shrink large images and remove scripts the page does not need.",
        "med", "confirmed",
        "This is a single lab test and results vary. Load the site on your own phone. Drop this if it feels quick."),
    "heavy-page": (A_SPEED, "The main page is very large to download",
        "Large pages are slow and use up mobile data.",
        "Compress and resize images. They are usually the cause.",
        "low", "confirmed", ""),
    "no-spf": (A_MAIL, "The domain has no SPF record for email",
        "Without it, email sent from the business is more likely to land in spam, and it is easier for scammers to fake.",
        "Add an SPF record that lists the services allowed to send the business's email.",
        "med", "check",
        "Confirm the business sends email from this domain (look at the contact page address). If they use a Gmail or Outlook address instead, drop this."),
    "no-dmarc": (A_MAIL, "The domain has no DMARC record for email",
        "DMARC tells other mail systems what to do with fake email that claims to come from the business. Large mail providers now expect it.",
        "Add a DMARC record, starting in monitoring mode.",
        "med", "check",
        "Confirm the business sends email from this domain. If they do not, drop this."),
    "multi-spf": (A_MAIL, "The domain has more than one SPF record",
        "Having two SPF records is an error, and mail systems may ignore both.",
        "Merge them into a single record.",
        "med", "check", "Confirm the business sends email from this domain."),
}

# Lighthouse audits that mean the same thing as one of our own checks.
LH_SAME = {"image-alt": "image-alt", "label": "label", "html-has-lang": "html-has-lang",
           "document-title": "document-title", "meta-viewport": "meta-viewport",
           "heading-order": "heading-order", "link-name": "link-name",
           "color-contrast": "color-contrast", "select-name": "select-name",
           "button-name": "button-name", "target-size": "target-size",
           "label-content-name-mismatch": "label-content-name-mismatch",
           "link-in-text-block": "links-not-underlined"}

# Things no scanner can do. These always need you.
MANUAL = [
    {"id": "m-keyboard", "title": "Use the site with the keyboard only",
     "how": "Put the mouse aside. Press Tab through the home page and the contact form. Can you always see where you are? Can you open the menu and send the form?",
     "problem": {"area": A_NAV, "title": "Parts of the site cannot be used without a mouse",
                 "why": "People who cannot use a mouse, and everyone using a screen reader, rely on the keyboard.",
                 "fix": "Make every menu, link, button and form box reachable with the Tab key, with a clear outline showing where you are.", "severity": "high"}},
    {"id": "m-zoom", "title": "Zoom the page to 200%",
     "how": "Press Ctrl and + until the browser shows 200%. Does text overlap, get cut off, or need sideways scrolling?",
     "problem": {"area": A_SEE, "title": "The page breaks when text is enlarged",
                 "why": "Many older readers keep their browser zoomed in. If the layout breaks, they cannot read the page.",
                 "fix": "Adjust the layout so content reflows instead of overlapping or being cut off.", "severity": "high"}},
    {"id": "m-contact", "title": "Find the phone number, address and opening hours",
     "how": "Start on the home page with a phone-width window. Time yourself. Can you find all three in under 15 seconds without opening a menu more than once?",
     "problem": {"area": A_NAV, "title": "Contact details are hard to find",
                 "why": "The phone number and opening hours are the most common reason people visit a local business website.",
                 "fix": "Put the phone number, address and hours at the top or bottom of every page.", "severity": "high"}},
    {"id": "m-form", "title": "Try the main form, without sending it",
     "how": "Leave a required box empty and make one deliberate mistake. Are the error messages clear and next to the right box? Type a phone number with spaces or hyphens: is it accepted? Do NOT submit a real enquiry.",
     "problem": {"area": A_FORM, "title": "The form is confusing when something goes wrong",
                 "why": "Unclear error messages make people give up and go elsewhere.",
                 "fix": "Show a plain message next to each box that needs attention, and keep what the person already typed.", "severity": "med"}},
    {"id": "m-popups", "title": "Look for pop-ups, sliders and moving parts",
     "how": "Load the home page fresh and wait 30 seconds. Does anything cover the page, slide by itself, or flash?",
     "problem": {"area": A_TRUST, "title": "Pop-ups or moving content get in the way",
                 "why": "Content that moves or covers the page is distracting, and hard to dismiss for anyone less confident with a mouse or touchscreen.",
                 "fix": "Remove automatic sliders and delay or remove pop-ups. Give every pop-up a large, obvious close button.", "severity": "med"}},
    {"id": "m-firstlook", "title": "The five-second test",
     "how": "Look at the home page for five seconds, then look away. Can you say what the business does, where it is, and what to do next?",
     "problem": {"area": A_NAV, "title": "It is not clear at a glance what the business offers",
                 "why": "Visitors decide in a few seconds whether they are in the right place.",
                 "fix": "Put one plain sentence at the top saying what the business does and who for, with one clear next step.", "severity": "med"}},
]
MANUAL_CONTRAST = {
    "id": "m-contrast", "title": "Check text contrast by eye",
    "how": "The automated contrast test did not run. Look for pale grey text, text over photos, and coloured buttons with white text. A free contrast checker will confirm any you doubt.",
    "problem": {"area": A_SEE, "title": KB["color-contrast"][1], "why": KB["color-contrast"][2],
                "fix": KB["color-contrast"][3], "severity": "high"}}

VAGUE = {"click here", "here", "read more", "more", "learn more", "more info", "details", "link", "this"}
PHONE_RE = re.compile(r"(?<!\d)(?:\+?1[\s.-]?)?\(?\d{3}\)?[\s.-]\d{3}[\s.-]\d{4}(?!\d)")
SKIP_TEXT = {"script", "style", "noscript", "svg", "template"}
BLOCK = {"p", "div", "section", "article", "aside", "main", "ul", "ol", "table", "form", "nav",
         "footer", "header", "h1", "h2", "h3", "h4", "h5", "h6"}
CONTRAST_RE = re.compile(r"contrast of ([\d.]+) \(foreground color: (#[0-9a-fA-F]+), background color: (#[0-9a-fA-F]+), "
                         r"font size: [\d.]+pt \(([\d.]+)px\).*?Expected contrast ratio of ([\d.]+)", re.S)
HOSTED = "A hosted website builder. Wording, colours, labels and picture descriptions can be changed in its editor, but structural fixes are limited by the template."
PLATFORMS = [
    ("WordPress", ("wp-content/", "wp-includes/"), "Most fixes can be made in the theme or the page editor. You will need an administrator login."),
    ("Wix", ("wixstatic.com", "wix.com"), HOSTED),
    ("Squarespace", ("squarespace.com", "squarespace-cdn.com"), HOSTED),
    ("Shopify", ("cdn.shopify.com",), "An online shop builder. Fixes are made in the theme editor or theme code."),
    ("Weebly", ("weebly.com",), HOSTED),
    ("GoDaddy Website Builder", ("wsimg.com",), HOSTED),
    ("Webflow", ("data-wf-site", "webflow.com"), "A visual builder. Most fixes are possible in its designer with an editor login."),
    ("Duda", ("multiscreensite.com", "dudaone"), HOSTED),
    ("Google Sites", ("sites.google.com",), HOSTED + " Google Sites is especially limited."),
    ("Drupal", ("/sites/default/files", "drupal-settings-json"), "A content system usually run by a developer or agency. Fixes are made in the theme."),
    ("Joomla", ("/media/jui/", "com_content"), "A content system. Fixes are made in the template."),
]
OUTREACH = """Subject: A small thing I noticed on {HOST}

Hello [name],

I was looking at your website and noticed that {TITLE}. {WHY}
{EVIDENCE}
It is usually a quick fix. {FIX}

I review websites for businesses whose customers are older, looking at things like text size, forms and how easy it is to find a phone number. If a short written review of your site would be useful, I would be glad to send details. If not, there is no need to reply and I will not email again.

[Your name]
[Your business name and postal address]
"""
CAPS_RUN = re.compile(r"(?:\b[A-Z][A-Z'\-]*\b[\s,;:.!?]*){6,}")     # six or more words in a row, all capitals
GLOBAL_LINK_SEL = re.compile(r"^((p|article|main)\s+)?a(:link|:visited)?$", re.I)   # not menu or button links
NEW_WINDOW_HINT = re.compile(r"new (window|tab)|opens in|external", re.I)
BODY_SEL = re.compile(r"(^|[\s>+~])(body|html|p|li|td|article|main)$", re.I)
LINK_SEL = re.compile(r"(^|[\s>+~])a(:link|:visited)?$", re.I)


def css_findings(css):
    """Rough checks on the site's style rules. Returns (finding key, evidence) pairs. All are 'your call'."""
    css = re.sub(r"/\*.*?\*/", " ", css, flags=re.S)
    justified, caps, tight, link_none, link_under = [], [], [], [], False
    for sel_text, body in re.findall(r"([^{}]+)\{([^{}]*)\}", css):
        decl = {}
        for part in body.split(";"):
            if ":" in part:
                k, v = part.split(":", 1)
                decl[k.strip().lower()] = v.strip().lower().replace("!important", "").strip()
        sels = [x.strip() for x in sel_text.split(",") if x.strip() and not x.strip().startswith("@")]
        body_sels = [x for x in sels if BODY_SEL.search(x)]
        link_sels = [x for x in sels if LINK_SEL.search(x)]
        if decl.get("text-align") == "justify" and sels:
            justified.append(sels[0])
        if decl.get("text-transform") == "uppercase" and body_sels:
            caps.append(body_sels[0])
        lh = decl.get("line-height", "")
        m = re.fullmatch(r"([\d.]+)(em|%)?", lh)
        if m and body_sels:
            value = float(m.group(1)) / (100 if m.group(2) == "%" else 1)
            if 0 < value < 1.4:
                tight.append("%s has line-height %s" % (body_sels[0], lh))
        deco = decl.get("text-decoration", "") + " " + decl.get("text-decoration-line", "")
        plain = [x for x in link_sels if GLOBAL_LINK_SEL.match(x)]
        if plain and "none" in deco:
            link_none.append(plain[0])
        if link_sels and "underline" in deco:
            link_under = True
    out = []
    if justified:
        out.append(("justified-text", "Style rule for: " + ", ".join(dict.fromkeys(justified))[:120]))
    if caps:
        out.append(("all-caps", "Style rule sets capitals for: " + ", ".join(dict.fromkeys(caps))[:120]))
    if tight:
        out.append(("tight-lines", "; ".join(dict.fromkeys(tight))[:160]))
    if link_none and not link_under:
        out.append(("links-not-underlined", "The style rules remove underlining from links (%s) and no rule puts it back" % ", ".join(dict.fromkeys(link_none))[:80]))
    return out


PRIORITY_WORDS = ("contact", "about", "service", "location", "hours", "appointment", "book", "price", "faq")


# ---------------------------------------------------------------------------
# Fetching
# ---------------------------------------------------------------------------
def fetch(url, method="GET", limit=3_000_000, timeout=TIMEOUT):
    # Web addresses only. A scanned page must not be able to point the scanner at a local file.
    if up.urlsplit(url).scheme.lower() not in ("http", "https"):
        raise ValueError("not a web address: " + url[:80])
    req = ur.Request(url, method=method, headers={"User-Agent": UA, "Accept": "text/html,*/*;q=0.8"})
    with ur.urlopen(req, timeout=timeout) as r:
        body = r.read(limit) if method == "GET" else b""
        return r.status, r.geturl(), r.headers, body


def fetch_text(url):
    status, final, headers, body = fetch(url)
    return final, headers, body.decode(headers.get_content_charset() or "utf-8", "replace")


def get_json(url, timeout=TIMEOUT):
    req = ur.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
    with ur.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8", "replace"))


# ---------------------------------------------------------------------------
# Reading one page
# ---------------------------------------------------------------------------
class Page(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.lang = None
        self.title = ""
        self.viewport = None
        self.imgs_no_alt = []
        self.fields = []
        self.label_for = set()
        self.headings = []
        self.links = []
        self.autoplay = 0
        self.text = []
        self.css = []
        self.sheets = []
        self.has_tel = False
        self.para = []
        self.scripts = 0
        self.underlined = []
        self.videos = 0
        self.tracks = 0
        self.embeds = 0
        self.has_search = False
        self._u = None
        self._in_p = False
        self._skip = 0
        self._label = 0
        self._in_title = False
        self._in_style = False
        self._head = None
        self._link = None

    def handle_starttag(self, tag, attrs):
        a = {k: (v or "") for k, v in attrs}
        if "style" in a:
            self.css.append(a["style"])
        if self._link is not None and tag != "a":
            # A name on something inside the link counts. An icon may carry its own
            # title, which this reader cannot see, so give it the benefit of the doubt.
            self._link["name"] += " " + a.get("aria-label", "") + (" [icon]" if tag == "svg" else "")
        if tag in BLOCK:
            self._in_p = tag == "p"
        if a.get("role") == "search":
            self.has_search = True
        if tag in SKIP_TEXT:
            self._skip += 1
            if tag == "style":
                self._in_style = True
            elif tag == "script":
                self.scripts += 1
        elif tag == "html":
            self.lang = a.get("lang", "").strip() or None
        elif tag == "title":
            self._in_title = True
        elif tag == "meta" and a.get("name", "").lower() == "viewport":
            self.viewport = a.get("content", "")
        elif tag == "link" and "stylesheet" in a.get("rel", "").lower() and a.get("href"):
            self.sheets.append(a["href"])
        elif tag == "img":
            hidden = a.get("aria-hidden") == "true" or a.get("role") in ("presentation", "none")
            if "alt" not in a and not hidden:
                self.imgs_no_alt.append(a.get("src", "(no address)")[:120])
            if self._link is not None:
                self._link["name"] += " " + a.get("alt", "")
        elif tag in ("input", "select", "textarea"):
            kind = a.get("type", "text").lower() if tag == "input" else tag
            if kind == "search" or "search" in (a.get("name", "") + a.get("id", "") + a.get("placeholder", "") + a.get("aria-label", "")).lower():
                self.has_search = True
            if kind not in ("hidden", "submit", "button", "reset", "image"):
                named = bool(a.get("aria-label") or a.get("aria-labelledby") or a.get("title") or self._label)
                self.fields.append({"id": a.get("id", ""), "named": named,
                                    "desc": "%s box%s" % (kind, (' "%s"' % (a.get("name") or a.get("placeholder"))) if (a.get("name") or a.get("placeholder")) else "")})
        elif tag == "label":
            self._label += 1
            if a.get("for"):
                self.label_for.add(a["for"])
        elif tag in ("h1", "h2", "h3", "h4", "h5", "h6"):
            self._head = [int(tag[1]), ""]
        elif tag == "a" and "href" in a:
            self._link = {"href": a["href"].strip(), "text": "", "name": a.get("aria-label", "") + a.get("title", ""),
                          "blank": a.get("target", "").lower() == "_blank"}
            if a["href"].lower().startswith("tel:"):
                self.has_tel = True
        elif tag in ("video", "audio"):
            if "autoplay" in a:
                self.autoplay += 1
            if tag == "video" and "muted" not in a:      # a muted video is usually a silent background loop
                self.videos += 1
        elif tag == "track":
            self.tracks += 1
        elif tag == "iframe" and re.search(r"youtube|youtu\.be|vimeo|wistia", a.get("src", "") + a.get("data-src", ""), re.I):
            self.embeds += 1
        elif tag == "u" and self._link is None:
            self._u = ""

    def handle_endtag(self, tag):
        if tag in SKIP_TEXT:
            self._skip = max(0, self._skip - 1)
            if tag == "style":
                self._in_style = False
        elif tag == "title":
            self._in_title = False
        elif tag == "p":
            self._in_p = False
        elif tag == "u" and self._u is not None:
            if self._u.strip():
                self.underlined.append(" ".join(self._u.split())[:60])
            self._u = None
        elif tag == "label":
            self._label = max(0, self._label - 1)
        elif tag in ("h1", "h2", "h3", "h4", "h5", "h6") and self._head:
            self.headings.append((self._head[0], " ".join(self._head[1].split())[:80]))
            self._head = None
        elif tag == "a" and self._link is not None:
            self.links.append(self._link)
            self._link = None

    def handle_data(self, data):
        if self._in_style:
            self.css.append(data)
        if self._in_title:
            self.title += data
        if self._skip:
            return
        if self._u is not None:
            self._u += data
        if self._head:
            self._head[1] += data
        if self._link is not None:
            self._link["text"] += data
        if data.strip():
            self.text.append(data.strip())
            if self._in_p:
                self.para.append(data.strip())


def syllables(word):
    groups = re.findall(r"[aeiouy]+", word.lower())
    n = len(groups)
    if word.lower().endswith("e") and n > 1:
        n -= 1
    return max(1, n)


def reading_grade(text):
    words = re.findall(r"[A-Za-z']+", text)
    sentences = max(1, len(re.findall(r"[.!?]+", text)))
    if len(words) < 150:
        return None
    return round(0.39 * len(words) / sentences + 11.8 * sum(map(syllables, words)) / len(words) - 15.59, 1)


# ---------------------------------------------------------------------------
# Site-level checks
# ---------------------------------------------------------------------------
def check_link(url):
    """Return 'ok', 'broken' or 'unknown' for one address."""
    for method in ("HEAD", "GET"):
        try:
            status = fetch(url, method=method, limit=2000, timeout=12)[0]
            return "ok" if status < 400 else "broken"
        except urllib.error.HTTPError as e:
            if e.code in (404, 410):
                return "broken"
            if e.code in (401, 403, 405, 406, 429, 501, 999) or e.code >= 500:
                if method == "HEAD":
                    continue
                return "unknown"
            return "broken"
        except urllib.error.URLError as e:
            return "broken" if "getaddrinfo" in str(e.reason) or "Name or service" in str(e.reason) else "unknown"
        except Exception:
            return "unknown"
    return "unknown"


def dns_txt(name, rtype="TXT"):
    try:
        d = get_json("https://dns.google/resolve?" + up.urlencode({"name": name, "type": rtype}), timeout=10)
    except Exception:
        return None
    return [a.get("data", "").replace('" "', "").strip('"') for a in d.get("Answer", []) or []]


def lighthouse(url, strategy):
    """Run Lighthouse through Google PageSpeed Insights. Returns (result, problem). Tries three times."""
    q = [("url", url), ("strategy", strategy)] + [("category", c) for c in ("accessibility", "performance", "best-practices", "seo")]
    if os.environ.get("PSI_API_KEY"):
        q.append(("key", os.environ["PSI_API_KEY"]))
    last = ""
    for attempt in range(3):
        try:
            d = get_json("https://www.googleapis.com/pagespeedonline/v5/runPagespeed?" + up.urlencode(q), timeout=150)
            return d["lighthouseResult"], None
        except urllib.error.HTTPError as e:
            if e.code in (429, 403):
                return None, ("Google refused the request (HTTP %s). The free quota is used up or the key is not accepted. "
                              "Check that PSI_API_KEY is set and the PageSpeed Insights API is enabled." % e.code)
            if e.code == 400:
                return None, "Google could not test this page (HTTP 400)."
            last = "HTTP %s" % e.code
        except Exception as e:
            last = type(e).__name__
        time.sleep(4 * (attempt + 1))
    return None, "Google PageSpeed Insights failed three times (%s)." % last


def detect_platform(html_text):
    low = html_text.lower()
    gen = re.search(r"""<meta[^>]+name=["']generator["'][^>]+content=["']([^"']+)""", html_text, re.I)
    for name, marks, note in PLATFORMS:
        if any(m in low for m in marks) or (gen and name.split()[0].lower() in gen.group(1).lower()):
            return {"name": name, "note": note}
    if gen:
        return {"name": gen.group(1)[:60], "note": "Not a platform this tool knows. Ask who maintains the site and how changes are published."}
    return {"name": "Not recognised", "note": "Hand-built or unrecognised. Ask who maintains the site and how changes are published."}


def find_baseline(out_root, host, stamp, explicit=None):
    """The earlier scan to compare against: a file you name, or the latest earlier-dated scan of this site."""
    if explicit:
        path = Path(explicit)
        path = path / "findings.json" if path.is_dir() else path
        return path if path.exists() else None
    folder = Path(out_root) / re.sub(r"[^a-z0-9.-]", "_", host)
    older = sorted(d for d in folder.glob("*/findings.json") if d.parent.name < stamp) if folder.exists() else []
    return older[-1] if older else None


def outreach_text(host, finding):
    title = finding["title"][:1].lower() + finding["title"][1:]
    ev = finding["evidence"][0] if finding.get("evidence") else ""
    return (OUTREACH.replace("{HOST}", host).replace("{TITLE}", title.rstrip("."))
            .replace("{WHY}", finding["why"]).replace("{FIX}", finding["fix"])
            .replace("{EVIDENCE}", ("\nFor example: " + ev + "\n") if ev else ""))


# ---------------------------------------------------------------------------
# The scan
# ---------------------------------------------------------------------------
def scan(start, max_pages=5, lh_pages=3, strategy="mobile", out_root=None, compare=None, log=print):
    if not re.match(r"https?://", start, re.I):
        start = "https://" + start
    findings, positives, gaps = {}, [], []

    shots = {}

    def add(key, evidence=(), pages=(), source="scan", shots_for=(), **override):
        area, title, why, fix, sev, conf, how = KB[key]
        f = findings.setdefault(key, {"id": key, "area": area, "title": title, "why": why, "fix": fix,
                                      "severity": sev, "confidence": conf, "check_how": how,
                                      "evidence": [], "pages": [], "source": source})
        f.update(override)
        if f["source"] != source:
            f["source"] = "both"
        for e in evidence:
            if e and e not in f["evidence"]:
                f["evidence"].append(e)
        for p in pages:
            if p not in f["pages"]:
                f["pages"].append(p)
        f.setdefault("shots", [])
        f["shots"].extend(list(shots_for)[:max(0, 3 - len(f["shots"]))])

    # --- first page -------------------------------------------------------
    log("Fetching " + start)
    try:
        home_url, headers, home_html = fetch_text(start)
    except Exception as e:
        if start.startswith("https://"):
            try:
                home_url, headers, home_html = fetch_text("http://" + start[8:])
            except Exception:
                raise SystemExit("Could not load %s (%s)" % (start, e))
        else:
            raise SystemExit("Could not load %s (%s)" % (start, e))
    host = up.urlsplit(home_url).netloc.lower()

    robots = urllib.robotparser.RobotFileParser()
    try:
        robots.parse(fetch_text(up.urljoin(home_url, "/robots.txt"))[2].splitlines())
    except Exception:
        robots.parse([])

    # --- crawl a few pages ------------------------------------------------
    pages, queue, seen = [], [home_url], {home_url.split("#")[0].rstrip("/")}
    cache = {home_url: home_html}
    while queue and len(pages) < max_pages:
        url = queue.pop(0)
        try:
            html_text = cache.pop(url, None) or fetch_text(url)[2]
        except Exception:
            continue
        p = Page()
        try:
            p.feed(html_text)
        except Exception:
            pass
        p.url = url
        pages.append(p)
        log("  read " + url)
        if len(pages) == 1:
            internal = []
            for l in p.links:
                full = up.urljoin(url, l["href"]).split("#")[0]
                s = up.urlsplit(full)
                key = full.rstrip("/")
                if s.scheme in ("http", "https") and s.netloc.lower() == host and key not in seen \
                        and not re.search(r"\.(pdf|jpe?g|png|gif|zip|docx?|xlsx?|mp4)$", s.path, re.I) \
                        and robots.can_fetch(UA, full):
                    seen.add(key)
                    internal.append(full)
            internal.sort(key=lambda u: 0 if any(w in u.lower() for w in PRIORITY_WORDS) else 1)
            queue.extend(internal)

    platform = detect_platform(home_html)
    home_words = len(" ".join(pages[0].text).split()) if pages else 0
    if pages and home_words < 60 and pages[0].scripts >= 2:
        gaps.append("This site appears to be built with JavaScript: the page as delivered contains only %d words. "
                    "The page scan saw almost nothing, so an empty findings list here means little. "
                    "Rely on the Lighthouse results and your hands-on checks." % home_words)

    # --- per-page checks --------------------------------------------------
    all_text, css_text, link_set, phone_seen, any_tel, any_search = [], [], {}, None, False, False
    for p in pages:
        short = up.urlsplit(p.url).path or "/"
        if not p.lang:
            add("html-has-lang", [short + ": no language set"], [short])
        if not p.title.strip():
            add("document-title", [short + ": no title"], [short])
        if p.viewport is None:
            add("meta-viewport", ["No viewport setting found"], [short])
        else:
            v = p.viewport.replace(" ", "").lower()
            m = re.search(r"maximum-scale=([\d.]+)", v)
            if "user-scalable=no" in v or "user-scalable=0" in v or (m and float(m.group(1)) < 2):
                add("zoom-blocked", ["Viewport setting: " + p.viewport], [short])
        if p.imgs_no_alt:
            add("image-alt", ["%s: %s" % (short, s) for s in p.imgs_no_alt[:4]], [short])
        unnamed = [f["desc"] for f in p.fields if not f["named"] and f["id"] not in p.label_for]
        if unnamed:
            add("label", ["%s: %s" % (short, d) for d in unnamed[:4]], [short])
        levels = [h[0] for h in p.headings]
        if levels:
            notes = []
            if 1 not in levels:
                notes.append("no main heading")
            if levels.count(1) > 1:
                notes.append("%d main headings" % levels.count(1))
            for prev, cur in zip(levels, levels[1:]):
                if cur > prev + 1:
                    notes.append("jumps from level %d to level %d" % (prev, cur))
                    break
            if notes:
                add("heading-order", ["%s: %s" % (short, ", ".join(notes))], [short])
        vague, empty = [], 0
        for l in p.links:
            text = " ".join(l["text"].split())
            if not text and not l["name"].strip():
                empty += 1
            elif text.lower().strip(" .>»") in VAGUE and not l["name"].strip():
                vague.append(text)
            full = up.urljoin(p.url, l["href"]).split("#")[0]
            if up.urlsplit(full).scheme in ("http", "https"):
                link_set.setdefault(full, short)
        if empty:
            add("link-name", ["%s: %d link(s) with no text" % (short, empty)], [short])
        if vague:
            add("vague-links", ["%s: \"%s\" used %d time(s)" % (short, vague[0], len(vague))], [short])
        if p.autoplay:
            add("autoplay", ["%s: %d item(s) set to autoplay" % (short, p.autoplay)], [short])
        if p.underlined:
            add("underline-not-link", ["%s: \"%s\"" % (short, t) for t in p.underlined[:3]], [short])
        if p.videos > p.tracks or p.embeds:
            bits = []
            if p.videos > p.tracks:
                bits.append("%d video(s) with no caption track" % (p.videos - p.tracks))
            if p.embeds:
                bits.append("%d embedded player(s) to check by hand" % p.embeds)
            add("video-captions", ["%s: %s" % (short, ", ".join(bits))], [short])
        blanks = [l for l in p.links if l.get("blank") and not NEW_WINDOW_HINT.search(l["text"] + " " + l["name"])]
        if blanks:
            inside = len([l for l in blanks if up.urlsplit(up.urljoin(p.url, l["href"])).netloc.lower() == host])
            add("new-window", ["%s: %d link(s) to pages within the site, %d to other sites" % (short, inside, len(blanks) - inside)], [short])
        caps_run = CAPS_RUN.search(" ".join(p.para))
        if caps_run and len(caps_run.group(0)) >= 25:
            add("all-caps", ["%s: \"%s\"" % (short, " ".join(caps_run.group(0).split())[:80])], [short], confidence="confirmed",
                check_how="Short headings and buttons in capitals are fine. Keep this only if whole sentences or paragraphs are in capitals.")
        any_search = any_search or p.has_search or any("sitemap" in (l["href"] + l["text"]).lower().replace(" ", "").replace("-", "") for l in p.links)
        any_tel = any_tel or p.has_tel
        page_text = " ".join(p.text)
        m = PHONE_RE.search(page_text)
        if m and not phone_seen:
            phone_seen = "%s: %s" % (short, m.group(0))
        all_text.append(" ".join(p.para))
        css_text.extend(p.css)

    if phone_seen and not any_tel:
        add("no-phone-link", [phone_seen])

    # --- style sheets: small text ----------------------------------------
    for href in list(dict.fromkeys(h for p in pages for h in p.sheets))[:6]:
        try:
            css_text.append(fetch_text(up.urljoin(pages[0].url, href))[2])
        except Exception:
            pass
    sizes = [float(x) for x in re.findall(r"font-size\s*:\s*([\d.]+)px", " ".join(css_text))]
    tiny = sorted({s for s in sizes if 0 < s < 14})
    if tiny:
        add("small-text", ["Sizes found in the style rules: " + ", ".join("%gpx" % s for s in tiny[:8])])

    for key, evidence in css_findings(" ".join(css_text)):
        add(key, [evidence])
    if not any_search and len(seen) > 25:
        add("no-search", ["No search box or site map link on the pages read; the home page links to %d pages within the site" % (len(seen) - 1)])

    grade = reading_grade(" ".join(all_text))
    if grade and grade > 10:
        add("reading-level", ["Estimated US school grade level of the paragraph text: %s (aim for 8 or lower)" % grade])

    # --- security ---------------------------------------------------------
    if home_url.startswith("http://"):
        add("no-https", ["The site loaded at " + home_url])
    else:
        try:
            if fetch("http://" + host + "/", method="GET", limit=1000)[1].startswith("http://"):
                add("no-https-redirect", ["http://%s/ stays on the insecure address" % host])
        except Exception:
            pass

    # --- broken links -----------------------------------------------------
    todo = list(link_set.items())[:60]
    log("Checking %d links" % len(todo))
    with ThreadPoolExecutor(8) as pool:
        results = list(pool.map(lambda kv: check_link(kv[0]), todo))
    for (url, where), res in zip(todo, results):
        if res == "broken":
            inside = up.urlsplit(url).netloc.lower() == host
            add("broken-internal-links" if inside else "broken-external-links", ["%s (linked from %s)" % (url, where)])
    if len(link_set) > 60:
        gaps.append("Only the first 60 of %d links were tested." % len(link_set))

    # --- Lighthouse on the first few pages ----------------------------------
    lh_meta = {"ran": False, "reason": "Switched off for this run.", "scores": {}, "metrics": {}, "pages": []}
    targets = pages[:max(0, lh_pages)]
    if targets:
        log("Running Lighthouse on %d page(s) through Google PageSpeed Insights (up to 2 minutes each)" % len(targets))
        with ThreadPoolExecutor(3) as pool:
            runs = list(pool.map(lambda p: lighthouse(p.url, strategy), targets))
        for p, (lr, problem) in zip(targets, runs):
            short = up.urlsplit(p.url).path or "/"
            if lr is None:
                lh_meta["pages"].append({"page": short, "ran": False, "reason": problem})
                continue
            audits = lr.get("audits", {})
            fps = lr.get("fullPageScreenshot") or {}
            shot, nodes = fps.get("screenshot") or {}, fps.get("nodes") or {}
            if shot.get("data") and shot.get("width") and len(shot["data"]) < 2_500_000:
                # Outline positions are in page units. On a page with no phone setting the page is laid out
                # 980 units wide and the picture is a shrunken copy, so record the page width separately.
                cw = 980 if p.viewport is None else shot["width"]
                right = max([r.get("left", 0) + r.get("width", 0) for r in nodes.values()] or [0])
                if right > cw * 1.02:
                    cw = right
                shots[short] = {"data": shot["data"], "w": shot["width"], "h": shot.get("height", 0), "cw": cw}
            for ref in lr.get("categories", {}).get("accessibility", {}).get("auditRefs", []):
                a = audits.get(ref["id"], {})
                if a.get("score") != 0:
                    continue
                ev, sh = [], []
                for item in (a.get("details", {}).get("items") or [])[:4]:
                    node = item.get("node") or {}
                    label = " ".join((node.get("nodeLabel") or node.get("snippet") or "").split())[:110]
                    line = label
                    m = CONTRAST_RE.search(node.get("explanation") or "") if ref["id"] == "color-contrast" else None
                    if m:
                        line = '"%s" has contrast %s and needs %s. Text %s on background %s, size %spx' % (
                            label, m.group(1), m.group(5), m.group(2), m.group(3), m.group(4))
                    if line:
                        ev.append("%s: %s" % (short, line))
                    rect = nodes.get(node.get("lhId") or "") or node.get("boundingRect") or {}
                    # Skip outlines that cover most of the page (the whole document, say): they show nothing.
                    if short in shots and len(sh) < 2 and rect.get("width", 0) > 0 \
                            and 0 < rect.get("height", 0) < 0.5 * (shots[short]["h"] * shots[short]["cw"] / shots[short]["w"] or 1e9):
                        sh.append({"page": short, "label": label,
                                   "rect": {k: rect.get(k, 0) for k in ("top", "left", "width", "height")}})
                key = LH_SAME.get(ref["id"])
                if key:
                    extra = {"confidence": "confirmed"} if ref["id"] == "link-in-text-block" else {}
                    add(key, ev, [short], source="lighthouse", shots_for=sh, **extra)
                else:
                    f = findings.setdefault("lh-" + ref["id"], {
                        "id": "lh-" + ref["id"], "area": A_OTHER, "title": a.get("title", ref["id"]),
                        "why": "", "fix": "", "severity": "low", "confidence": "check",
                        "check_how": "This is the scanner's own technical wording. Decide whether it matters to a customer. If it does, rewrite the title, why and fix in plain English. If not, drop it.",
                        "evidence": [], "pages": [], "shots": [], "source": "lighthouse"})
                    f["evidence"].extend(ev)
                    f["pages"].append(short)
                    f["shots"].extend(sh[:max(0, 3 - len(f["shots"]))])
            lcp, weight = audits.get("largest-contentful-paint", {}), audits.get("total-byte-weight", {})
            entry = {"page": short, "ran": True, "reason": "",
                     "scores": {k: round((c.get("score") or 0) * 100) for k, c in lr.get("categories", {}).items()},
                     "metrics": {"Main content appears": lcp.get("displayValue", ""),
                                 "Page size": weight.get("displayValue", "").replace("Total size was ", "")}}
            lh_meta["pages"].append(entry)
            if not lh_meta["ran"]:
                lh_meta.update(ran=True, reason="", scores=entry["scores"], metrics=entry["metrics"])
            if (lcp.get("numericValue") or 0) > 4000:
                add("slow-load", ["%s: main content took %s to appear in a simulated phone test" % (short, lcp.get("displayValue", "over 4 s"))], [short], source="lighthouse")
            if (weight.get("numericValue") or 0) > 4_000_000:
                add("heavy-page", ["%s: %s" % (short, weight.get("displayValue", ""))], [short], source="lighthouse")
        failed = [x for x in lh_meta["pages"] if not x["ran"]]
        if failed and lh_meta["ran"]:
            gaps.append("Lighthouse did not run on: " + "; ".join("%s (%s)" % (x["page"], x["reason"]) for x in failed))
        elif failed:
            lh_meta["reason"] = failed[0]["reason"]
    if not lh_meta["ran"]:
        gaps.append("The Lighthouse test did not run, so colour contrast, tap-target size and speed were NOT scanned. " + lh_meta["reason"])
    lh_count = len([x for x in lh_meta["pages"] if x["ran"]])

    # --- email records ----------------------------------------------------
    domain = host.split(":")[0]
    domain = domain[4:] if domain.startswith("www.") else domain
    mx = dns_txt(domain, "MX")
    if mx is None:
        gaps.append("Mail records could not be looked up.")
    elif mx:
        txt = dns_txt(domain) or []
        spf = [t for t in txt if t.lower().startswith("v=spf1")]
        # A subdomain inherits the DMARC record of its parent domain, so look upwards too.
        dmarc, labels = [], domain.split(".")
        for i in range(max(1, len(labels) - 1)):
            dmarc = [t for t in (dns_txt("_dmarc." + ".".join(labels[i:])) or []) if t.lower().startswith("v=dmarc1")]
            if dmarc:
                break
        if not spf:
            add("no-spf", ["No SPF record found for " + domain])
        elif len(spf) > 1:
            add("multi-spf", spf[:2])
        if not dmarc:
            add("no-dmarc", ["No DMARC record found for " + domain])
        if spf and dmarc and len(spf) == 1:
            positives.append("Email records (SPF and DMARC) are in place for " + domain + ".")

    # --- what is working well --------------------------------------------
    def good(key, text):
        if key not in findings:
            positives.append(text)
    if home_url.startswith("https://"):
        good("no-https-redirect", "The site is served securely.")
    good("html-has-lang", "Every page scanned declares its language.")
    if "meta-viewport" not in findings and "zoom-blocked" not in findings:
        positives.append("Pages are set up for phone screens and allow zooming.")
    if any(p.imgs_no_alt is not None for p in pages):
        good("image-alt", "Pictures on the pages scanned have text descriptions.")
    if any(p.fields for p in pages):
        good("label", "Form boxes on the pages scanned are labelled.")
    if any_tel:
        positives.append("The phone number can be tapped to call.")
    if "broken-internal-links" not in findings:
        positives.append("No broken links were found among the links tested within the site.")
    if lh_meta["ran"] and "color-contrast" not in findings:
        positives.append("Text contrast passed the automated test on %s." % ("the home page" if lh_count == 1 else "the %d pages tested" % lh_count))

    order = {"high": 0, "med": 1, "low": 2}
    flist = sorted(findings.values(), key=lambda f: (order[f["severity"]], f["confidence"] != "confirmed", f["title"]))
    for f in flist:
        f["evidence"] = f["evidence"][:8]
        f.setdefault("shots", [])
    manual = list(MANUAL) + ([] if lh_meta["ran"] else [MANUAL_CONTRAST])
    today = dt.date.today()
    stamp = today.isoformat()

    comparison = None
    base = find_baseline(out_root, host, stamp, compare) if (out_root or compare) else None
    if base:
        try:
            old = json.loads(base.read_text(encoding="utf-8"))
            old_ids = {f["id"]: f["title"] for f in old.get("findings", [])}
            now_ids = {f["id"] for f in flist}
            comparison = {"since": old.get("meta", {}).get("date", base.parent.name),
                          "fixed": [{"id": k, "title": v} for k, v in old_ids.items() if k not in now_ids],
                          "still": [k for k in old_ids if k in now_ids],
                          "new": [k for k in now_ids if k not in old_ids]}
        except Exception:
            gaps.append("The earlier scan at %s could not be read, so there is no comparison." % base)

    best = next((f for f in flist if f["confidence"] == "confirmed"), None)
    return {
        "meta": {"site": home_url, "host": host, "date": today.strftime("%B %d, %Y").replace(" 0", " "),
                 "stamp": stamp, "pages": [p.url for p in pages], "platform": platform,
                 "lighthouse": lh_meta, "version": VERSION, "outreach_template": OUTREACH},
        "findings": flist, "manual": manual, "positives": positives, "gaps": gaps,
        "compare": comparison, "shots": shots,
        "outreach": outreach_text(host, best) if best else "",
    }


def write_report(data, out_root):
    folder = Path(out_root) / re.sub(r"[^a-z0-9.-]", "_", data["meta"]["host"]) / data["meta"]["stamp"]
    folder.mkdir(parents=True, exist_ok=True)
    slim = {k: v for k, v in data.items() if k != "shots"}   # screenshots are large; keep them out of the data file
    (folder / "findings.json").write_text(json.dumps(slim, indent=2), encoding="utf-8")
    if data.get("outreach"):
        (folder / "outreach-draft.txt").write_text(
            "DRAFT. Check this finding on the live site before sending. Add your name, postal address and the person's name.\n\n"
            + data["outreach"], encoding="utf-8")
    template = (HERE / "template.html").read_text(encoding="utf-8")
    blob = json.dumps(data).replace("<", "\\u003c")   # scanned text must not be able to open or close a tag
    (folder / "review.html").write_text(template.replace("/*__DATA__*/null", blob), encoding="utf-8")
    return folder / "review.html"


def main():
    ap = argparse.ArgumentParser(description="Scan a website and build a review page.")
    ap.add_argument("url", nargs="?", help="address of the site to scan")
    ap.add_argument("--list", help="text file with one address per line (prospecting mode)")
    ap.add_argument("--pages", type=int, default=5, help="how many pages to read (default 5)")
    ap.add_argument("--out", default=str(HERE / "out"), help="output folder")
    ap.add_argument("--no-lighthouse", action="store_true", help="skip the Google Lighthouse test")
    ap.add_argument("--lighthouse-pages", type=int, help="how many pages get the Lighthouse test (default 3, or 1 with --list)")
    ap.add_argument("--compare", help="earlier scan folder or findings.json to compare with (default: the latest earlier-dated scan of the same site)")
    ap.add_argument("--desktop", action="store_true", help="run Lighthouse as a desktop instead of a phone")
    args = ap.parse_args()
    if not args.url and not args.list:
        ap.error("give a site address or --list FILE")

    # utf-8-sig: Windows Notepad may put an invisible marker at the start of the file.
    urls = [args.url] if args.url else [l.strip() for l in Path(args.list).read_text(encoding="utf-8-sig").splitlines()
                                        if l.strip() and not l.strip().startswith("#")]
    rows = []
    for u in urls:
        try:
            n = 0 if args.no_lighthouse else args.lighthouse_pages if args.lighthouse_pages is not None else (1 if args.list else 3)
            data = scan(u, args.pages, n, "desktop" if args.desktop else "mobile", args.out, args.compare)
            path = write_report(data, args.out)
        except SystemExit as e:
            print("SKIPPED %s: %s" % (u, e))
            rows.append([u, "could not load", "", "", "", "", "", ""])
            continue
        except Exception as e:
            if not args.list:
                raise
            # One bad site must not lose the summary for the rest of the list.
            print("FAILED %s: %s: %s" % (u, type(e).__name__, e))
            rows.append([u, "scan failed", "", "", "", "", "", ""])
            continue
        conf = [f for f in data["findings"] if f["confidence"] == "confirmed"]
        check = [f for f in data["findings"] if f["confidence"] == "check"]
        rows.append([data["meta"]["host"], len([f for f in conf if f["severity"] == "high"]), len(conf), len(check),
                     conf[0]["title"] if conf else "", data["meta"]["platform"]["name"],
                     str(path.parent / "outreach-draft.txt") if data.get("outreach") else "", str(path)])
        print("\n%s\n  %d finding(s) the scanner is confident about\n  %d finding(s) that need your call\n  %d hands-on check(s) for you to do\n  Open: %s\n"
              % (data["meta"]["host"], len(conf), len(check), len(data["manual"]), path))
    if args.list:
        summary = Path(args.out) / "summary.csv"
        summary.parent.mkdir(parents=True, exist_ok=True)
        with summary.open("w", newline="", encoding="utf-8") as fh:
            w = csv.writer(fh)
            w.writerow(["site", "high-priority confirmed", "confirmed findings", "need your call", "strongest confirmed finding", "built with", "outreach draft", "review page"])
            w.writerows(sorted(rows, key=lambda r: -(r[1] if isinstance(r[1], int) else -1)))
        print("Prospect summary: %s" % summary)


if __name__ == "__main__":
    sys.exit(main())
