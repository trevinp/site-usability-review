# Site Usability Review

Review a small business website for usability issues that affect older customers. Make the web better for seniors!

## Quick start

You need Python 3.8 or later and a web browser. The scanner uses the Python standard library. Keep `checkup.py` and `template.html` in the same folder and run this command from there:

```
python checkup.py https://example.com --no-lighthouse
```

Open the `review.html` path printed by the scanner. By default it is saved under `out/<site>/<YYYY-MM-DD>/` next to the script. The folder also holds `findings.json` and, when the scanner has a confident finding, `outreach-draft.txt`.

The scan requests web pages and checks links. It uses Google Public DNS for mail records and sends selected page URLs to Google PageSpeed Insights when Lighthouse is enabled.

Options:

- `--pages 8` reads more pages (default 5: the home page, then contact, about and service pages first).
- `--lighthouse-pages 3` sets how many of those pages get the Google Lighthouse test (default 3, or 1 with `--list`). Each takes up to two minutes; they run side by side.
- `--no-lighthouse` skips the Google test, for a quick look.
- `--desktop` switches Lighthouse from mobile to desktop.
- `--out PATH` changes where the scanner saves reports and the batch summary.
- `--compare PATH` compares with an earlier scan (a scan folder or its `findings.json`). Without it, the latest earlier-dated scan of the same site is used automatically.
- `--list prospects.txt` scans many sites (one address per line) and writes `out/summary.csv`, sorted by how many confident high-priority findings each has, with what each site is built on and where its outreach draft is.

## Optional Lighthouse setup

The colour contrast, tap-target and speed tests, and the screenshots, come from Google Lighthouse through PageSpeed Insights. The review page shows when these checks could not run.

Enable the PageSpeed Insights API in Google Cloud and create an API key. Set `PSI_API_KEY` in your current terminal session.

```powershell
$env:PSI_API_KEY = "your-key"
```

In Bash or Zsh, use `export PSI_API_KEY="your-key"`. Then run `python checkup.py https://example.com` to include Lighthouse.

## What is automated and what is yours

| Step | Who |
|---|---|
| Reading pages, testing links, checking mail records, running Lighthouse | Script |
| Plain-English wording for each finding | Script (edit any of it on the review page) |
| Screenshots with the problem outlined, exact colours for contrast failures | Script |
| Findings tagged **Scanner is confident** | Script includes them; you can drop or reword |
| Findings tagged **Your call: verify first** | Left out until you look and say yes |
| Hands-on checks (keyboard, zoom, contact details, form, pop-ups, five-second test, and visual contrast when needed) | You, about 15 minutes |
| Importance of each finding | Script suggests; you set |
| Opening summary, quote for fixes | You |
| Which "fixed since last time" items to show the client | Script lists; you untick any you never reported |
| Layout of the client report, "what I did" and "not covered" lists | Script |
| Outreach email | Script drafts; you verify the finding, add names and send by hand |

Print and download stay locked until every decision is made.

## The review page

- **Your decisions are saved as you go** when the browser allows local storage for the review file. Only what you change is stored. "Restore scanner wording" undoes your edits to one finding.
- **Save decisions to file / Load decisions from file** keeps a backup and lets you carry on in another browser or on another PC.
- **For your eyes only** shows what the site is built on and the Lighthouse scores per page. None of it goes in the client report.
- **Download report** saves the client report as one self-contained file, pictures included, that can be emailed or opened anywhere. **Print or save as PDF** does the same through the browser's print box.

## Before and after

Scan a site, send the report, and scan it again on a later date. The second review page shows what is no longer found, what is still there and what is new, and the client report gets a "Progress since" section. The comparison covers scanner findings only, not your hands-on checks, and it cannot know which findings you left out of the first report, so untick those.

Two scans of the same site on the same day share a folder and the second replaces the first. To compare same-day scans, copy the first `findings.json` somewhere and pass it with `--compare`.

## Limits

- It is a practical usability review of a sample of pages, not a legal compliance audit. Never tell a client their site is "compliant".
- The page reader does not run JavaScript. If a site is built that way the review page says so; rely on Lighthouse and the hands-on checks.
- Lighthouse results vary a little between runs, speed most of all.
- The small-text and reading-level findings are rough signals. That is why they are tagged "Your call".
- Screenshot outlines are placed from Lighthouse's measurements. Glance at each one before it goes to a client.
- Review outreach drafts before sharing them. The scanner saves them locally for you to edit and send.
- You are responsible for following the anti-spam rules that apply where you and the recipient are, such as CAN-SPAM in the US, CASL in Canada, and PECR and GDPR in the UK and EU. Some of these require consent before a first email.
- The wording, the reading-level estimate and the phone-number check assume an English-language site with US-style phone numbers.
- It reads a handful of pages and tests at most 60 links per run. It follows `robots.txt` when choosing which extra pages to read. The home page, its style sheets and the link checks are requested regardless.

## Changing the wording

All finding text lives in the `KB` table near the top of `checkup.py`. The hands-on checks are in `MANUAL` just below it, and the outreach email is `OUTREACH`.

## AI browser pass

[AI browser pass](ai-pass.md) is an optional checklist for a browser-enabled assistant. It collects evidence for findings marked **Your call** and makes a first pass at the hands-on checks. Review its observations and enter your decisions on the review page.

## License

Everything in this repository, including the scanner, the review page template, the finding wording and the documentation, is available under the [MIT License](LICENSE).

