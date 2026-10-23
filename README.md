# Daily Paper for Kindle

A newspaper page with the day's top news, the weather and your calendar,
rebuilt every morning and shown on your jailbroken Kindle through KUAL.

```
GitHub Actions (every morning)          Kindle (KUAL menu)
  generate.py  ->  paper.png  ------->  "Fetch and show today's paper"
  news RSS + Open-Meteo + your iCal     downloads the PNG and draws it with eips
```

The heavy work happens off the Kindle. The Kindle only downloads one PNG.

## 1. Set the screen size

Edit `generator/config.json` -> `screen`:

| Kindle | width x height |
|---|---|
| Basic (7th-10th gen), Kindle 4/5 touch | 600 x 800 |
| Paperwhite 1/2 | 758 x 1024 |
| Paperwhite 3/4, Voyage, Oasis 1, Basic 11th gen | 1072 x 1448 |
| Paperwhite 5 (11th gen) | 1236 x 1648 |
| Oasis 2/3, Scribe is different, check yours | 1264 x 1680 |

Also set your city's `latitude` / `longitude` (default is Copenhagen) and
change `news_feeds` to whichever RSS feeds you like.

## 2. Test locally

```
pip install -r generator/requirements.txt
python generator/generate.py --demo     # fake data, writes generator/out/paper.png
python generator/generate.py            # real data
```

## 3. Publish it every morning (GitHub Actions + Pages)

1. Create a new GitHub repo and push this folder to it.
2. Repo -> Settings -> Pages -> Source: **GitHub Actions**.
3. Repo -> Settings -> Secrets and variables -> Actions, add:
   - `CALENDAR_ICS_URLS`: your calendar's **secret iCal address**
     - Google Calendar: Settings -> your calendar -> "Secret address in iCal format"
     - iCloud: Calendar -> share -> Public calendar (use the webcal link, change `webcal://` to `https://`)
     - Outlook: Settings -> Calendar -> Shared calendars -> Publish -> ICS link
     - Several calendars: separate the URLs with commas.
   - `PAPER_NAME`: a long random file name, e.g. `paper-k3j9x2m7q8w4.png`
4. Actions tab -> "Build daily paper" -> Run workflow once. Your paper will be at
   `https://USERNAME.github.io/REPO/<PAPER_NAME>`.

**Privacy:** GitHub Pages is public. Your event titles end up inside that image,
so the random file name is the only thing protecting it. If that is not
acceptable, leave `CALENDAR_ICS_URLS` empty (the agenda box then says
"No calendar configured"), or host it at home instead:

```
# on a Raspberry Pi / NAS / always-on PC, crontab -e
30 6 * * *  cd /path/to/dailypaper && CALENDAR_ICS_URLS="https://..." python3 generator/generate.py -o /var/www/paper.png
# and serve /var/www with any web server; use http://pi.local/paper.png as PAPER_URL
```

## 4. Install on the Kindle

1. Edit `kindle/extensions/DailyPaper/settings.conf` and set `PAPER_URL`.
2. Connect the Kindle by USB and copy the `DailyPaper` folder into the Kindle's
   `extensions/` folder (next to your other KUAL extensions).
3. Eject, open KUAL -> **Daily Paper** -> **Fetch and show today's paper**.

The menu has three entries:
- **Fetch and show today's paper**: turns on Wi-Fi, downloads, displays.
- **Show last downloaded paper**: works offline.
- **Fetch and set as screensaver**: copies the paper into
  `linkss/screensavers/` (needs the screensaver hack), so your Kindle shows
  the paper whenever it sleeps.

The image stays until you press a button or the Kindle redraws the home
screen. Log: `/mnt/us/dailypaper/log.txt`.

## Troubleshooting

- **"Download failed"**: open the PNG URL in a browser first. Some older
  firmwares cannot do modern HTTPS; the script already retries without
  certificate checking. If it still fails, serve the file over plain `http://`
  from a home server.
- **Image looks cut off or tiny**: wrong `screen` size in `config.json`.
- **A feed is empty**: some sites change or remove RSS URLs; swap in another.
- **Fonts look odd on your PC**: the generator uses DejaVu/Liberation fonts.
  Drop other `.ttf` files in `generator/fonts/` or set `font_dir` in the config.
