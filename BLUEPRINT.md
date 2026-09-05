# YouDownloader — kompletní blueprint

## 1. Cíl produktu

YouDownloader bude lokální desktopová aplikace pro Windows 10/11. Uživatel
vloží odkaz na YouTube video, YouTube Shorts, skladbu nebo playlist. Aplikace odkaz zanalyzuje a
zobrazí náhledový obrázek, název, kanál, délku, datum zveřejnění a dostupné
výstupní možnosti. Uživatel zvolí například MP4 nebo MP3, kvalitu a spustí
stahování.

Výchozí cílovou složku lze trvale nastavit. Jedno video se uloží přímo do této
složky. Playlist se uloží do nové podsložky pojmenované podle playlistu a
jednotlivé soubory budou očíslované podle pořadí.

```text
C:\Users\Martin\Downloads\YouDownloader\
├── Samostatné video [video_id].mp4
└── Název playlistu\
    ├── 001 - První skladba [video_id].mp3
    ├── 002 - Druhá skladba [video_id].mp3
    └── 003 - Třetí skladba [video_id].mp3
```

> Aplikace je určena pouze pro obsah, který uživatel vlastní, má svolení jej
> uložit, nebo jehož licence stahování dovoluje. Nemá obcházet DRM, přihlášení,
> placený přístup ani jiná technická omezení. Uživatel musí respektovat autorská
> práva a podmínky YouTube.

## 2. Zvolený technologický stack

### Frontend

- **HTML5** — sémantická struktura aplikace.
- **CSS3** — vlastní responzivní design, CSS variables, světlý/tmavý režim.
- **Vanilla JavaScript ES modules** — bez Reactu, Vue a Node.js toolchainu.
- **Fetch API** — komunikace s Python REST API.
- **WebSocket API** — živý průběh stahování a převodu.

Externí data se budou vkládat přes `textContent`, nikdy přes `innerHTML`.
Frontend zůstane malý, přehledný a bez kompilace. Rozdělí se do ES modulů, aby
se z něj nestal jeden velký soubor `app.js`.

### Python backend

- **Python 3.13** — doporučená a v CI pevně nastavená verze.
- **FastAPI** — typované REST API a WebSocket endpoint.
- **Uvicorn** — lokální ASGI server naslouchající pouze na `127.0.0.1`.
- **Pydantic v2** — validace URL, nastavení a API payloadů.
- **pywebview** — nativní Windows okno s WebView2, takže uživatel neuvidí
  terminál ani nemusí ručně otevírat prohlížeč.
- **yt-dlp** — získání metadat, seznamu playlistu a samotné stahování.
- **FFmpeg + ffprobe** — spojení video/audio stop, převod do MP3 a kontrola
  výsledného souboru.
- **aiosqlite** — asynchronní přístup k SQLite.
- **platformdirs** — správné umístění databáze, logů a cache ve Windows.
- **httpx** — bezpečný proxy/cache náhledových obrázků.
- **psutil** — pozastavení, obnovení a ukončení celého stromu procesu yt-dlp a
  FFmpeg.
- **structlog** — strukturované lokální logy bez citlivých údajů.

### Databáze a distribuce

- **SQLite** — nejlepší volba pro jednu lokální aplikaci; nevyžaduje server,
  instalaci ani účet.
- **install.bat + scripts/install.ps1** — jednoduchá Windows instalace pro
  vývojovou/distribuční verzi z repozitáře: vytvoří `.venv`, nainstaluje
  závislosti, vytvoří zástupce `YouDownloader` na ploše a zkontroluje Node.js,
  FFmpeg/ffprobe a WebView2.
- **start.bat + scripts/start.ps1** — dvojklikový start aplikace; pokud už
  server běží na `127.0.0.1:8765`, otevře existující UI místo spuštění druhé
  instance.
- **stop.bat + scripts/stop.ps1** — bezpečné ukončení všech relací spuštěných z
  této složky projektu včetně potomků jako yt-dlp, FFmpeg nebo WebView2.
- **PyInstaller** — vytvoření samostatného `.exe` balíčku.
- **Inno Setup** — Windows instalátor, zástupce a odinstalace.
- **pytest, pytest-asyncio, Playwright, Ruff a mypy** — testy a kontrola kvality.

`yt-dlp` a FFmpeg budou přibalené jako ověřené binární sidecary. Uživatel tedy
nebude instalovat Python ani FFmpeg ručně.

## 3. Architektura

```text
pywebview / WebView2
┌──────────────────────────────────────────┐
│ HTML + CSS + JavaScript                  │
│ REST požadavky + WebSocket průběh        │
└───────────────────┬──────────────────────┘
                    │ pouze localhost + session token
┌───────────────────▼──────────────────────┐
│ FastAPI backend                          │
│ URL parser │ Preview │ Fronta │ Nastavení│
└───────┬──────────┬───────────────┬───────┘
        │          │               │
   SQLite      yt-dlp.exe     FFmpeg/ffprobe
        │          │               │
 historie     metadata/data     mux/konverze
```

FastAPI servíruje i statický frontend. Backend se spustí na náhodném volném
portu pouze na loopback adrese. pywebview otevře jeho lokální URL v nativním
okně. Každé API volání musí obsahovat náhodně vygenerovaný session token.

Stahovací příkazy se nikdy neskládají do shellového řetězce. Python používá
`asyncio.create_subprocess_exec()` a předává každý argument samostatně. Název
videa, URL ani cesta tak nemohou vložit vlastní příkaz.

## 4. Obrazovky a uživatelský postup

### Hlavní obrazovka

1. Velké pole **Vložte odkaz na YouTube**.
2. Tlačítka **Vložit ze schránky** a **Načíst informace**.
3. Během analýzy skeleton/loading stav a možnost požadavek zrušit.
4. Karta výsledku: thumbnail, název, kanál, délka, datum zveřejnění, počet
   zhlédnutí (pokud je dostupný) a štítek **Video** nebo **Playlist**.
5. Výběr formátu, kvality a cílové složky.
6. Tlačítko **Přidat do fronty**.

Pokud URL obsahuje současně `v=` i `list=`, nejde rozhodnout z URL o záměru
uživatele. Aplikace proto zobrazí dvě jasné volby:

- **Stáhnout pouze toto video** — výchozí a bezpečnější volba.
- **Stáhnout celý playlist**.

Čistá playlistová URL se automaticky vyhodnotí jako playlist a čistá URL videa
jako samostatné video.

### Playlistový náhled

Zobrazí název playlistu, autora, počet nalezených videí, thumbnail a prvních
10 položek. Rozbalovací seznam umožní zobrazit všechny položky. MVP stáhne celý
playlist; pozdější verze může přidat checkboxy, rozsah a filtrování.

### Fronta stahování

Každá úloha zobrazuje:

- stav `Čeká`, `Stahuje se`, `Převádí se`, `Pozastaveno`, `Hotovo`, `Selhalo`,
- procenta, velikost, rychlost a odhad zbývajícího času,
- u playlistu například `12 / 45 položek`,
- tlačítka pozastavit, pokračovat, zrušit, opakovat a otevřít složku.

Playlist pokračuje i při selhání jedné položky. Na konci ukáže například
`43 hotovo, 1 nedostupné, 1 selhalo` a nabídne opakování pouze selhaných.

### Nastavení

- výchozí složka přes nativní dialog Windows,
- výchozí formát a kvalita,
- počet paralelních stahování: výchozí 1, maximum 3,
- chování při existujícím souboru: přeskočit / přejmenovat / zeptat se,
- automatické otevření složky po dokončení,
- světlý, tmavý nebo systémový režim,
- kontrola aktualizací a export diagnostického logu.

Při prvním spuštění bude cílem známá složka Windows
`Stažené soubory\YouDownloader`, nikoliv ručně sestavená cesta podle jazyka OS.

## 5. Výstupní předvolby

Uživatel nebude vybírat libovolné kombinace kontejnerů a kodeků. Rozhraní
nabídne ověřené předvolby:

| Předvolba | Kvalita | Chování |
|---|---|---|
| MP4 video | nejlepší, 2160p, 1440p, 1080p, 720p, 480p | nejlepší odpovídající obraz a zvuk, sloučení přes FFmpeg |
| WebM video | nejlepší, 1080p, 720p | preferuje WebM/Opus bez zbytečné konverze |
| MP3 audio | 320, 192, 128 kb/s | nejlepší zdrojový zvuk převede přes FFmpeg |
| M4A audio | nejlepší | preferuje M4A stopu bez další ztrátové konverze |
| Opus audio | nejlepší | preferuje Opus stopu bez další ztrátové konverze |

Formáty, které konkrétní video nepodporuje, budou v UI skryté nebo označené.
„MP3 320 kb/s“ neznamená zvýšení kvality zdroje; pouze cílový datový tok.

Příklady interních parametrů yt-dlp:

```text
MP4 do 1080p:
-f bv*[height<=1080]+ba/b[height<=1080]
--merge-output-format mp4
--recode-video mp4

MP3 192 kb/s:
-f ba/b
--extract-audio
--audio-format mp3
--audio-quality 192K

M4A:
-f ba[ext=m4a]/ba/b
--extract-audio
--audio-format m4a
```

Formátové selektory budou v jedné backendové mapě `PRESETS`; frontend posílá
jen ID předvolby, nikdy vlastní yt-dlp argumenty.

## 6. Analýza URL a metadat

Backend přijme pouze `https` URL z explicitního seznamu hostů:

```text
youtube.com
www.youtube.com
m.youtube.com
music.youtube.com
youtu.be
```

Odstraní sledovací parametry a zachová pouze významné parametry, například
`v`, `list`, `index` a `t`. Ostatní weby a protokoly odmítne, aby nevznikl SSRF
nebo přístup k lokálním souborům.

Pro samostatné video backend použije ekvivalent:

```text
yt-dlp.exe --no-config --no-playlist --skip-download --dump-single-json URL
```

Pro playlist:

```text
yt-dlp.exe --no-config --yes-playlist --flat-playlist \
  --skip-download --dump-single-json URL
```

Výstup je JSON. Normální lidský konzolový text se neparsuje. Backend vrátí jen
vlastní stabilní `PreviewResponse` a nebude frontend vystavovat přímo internímu
formátu yt-dlp.

```json
{
  "kind": "playlist",
  "sourceUrl": "https://www.youtube.com/playlist?list=...",
  "id": "playlist_id",
  "title": "Název playlistu",
  "channel": "Autor",
  "thumbnailUrl": "/api/v1/thumbnails/preview-token",
  "itemCount": 42,
  "scopeOptions": ["playlist"],
  "items": [
    {"index": 1, "id": "video_id", "title": "První skladba", "duration": 218}
  ]
}
```

Thumbnail se načte přes omezený backendový proxy endpoint, který povolí jen
důvěryhodné domény obrázků, kontroluje MIME typ, maximální velikost a krátce jej
cacheuje. Tím frontend nemusí věřit libovolné vzdálené URL.

## 7. Ukládání videí a playlistů

Výstupní šablona pro samostatné video:

```text
%(title).150B [%(id)s].%(ext)s
```

Výstupní šablona playlistu relativní k výchozí složce:

```text
%(playlist_title).120B\%(playlist_index)03d - %(title).140B [%(id)s].%(ext)s
```

Backend přidá `--windows-filenames`, `--trim-filenames 180` a provede vlastní
kontrolu výsledné cesty. Zakázané znaky a rezervovaná Windows jména se nahradí.
Název podsložky bude odpovídat názvu playlistu, pouze se sanitizuje pro Windows.

Stahování probíhá nejprve do pracovní složky `.youdownloader-partials` uvnitř
cílového disku. Teprve úspěšně dokončený a pomocí ffprobe ověřený soubor se
atomicky přesune na finální místo. Přerušené `.part` soubory lze obnovit.

## 8. Backendové moduly

```text
backend/
├── main.py                    # start FastAPI, Uvicorn a pywebview
├── api/
│   ├── preview.py             # validace a načtení metadat
│   ├── jobs.py                # fronta a ovládání úloh
│   ├── settings.py
│   ├── thumbnails.py
│   └── websocket.py
├── core/
│   ├── config.py              # cesty, limity, session token
│   ├── security.py            # URL allowlist, token dependency
│   ├── errors.py
│   └── logging.py
├── domain/
│   ├── models.py
│   └── presets.py
├── services/
│   ├── metadata_service.py
│   ├── download_manager.py
│   ├── process_manager.py
│   ├── ytdlp.py
│   ├── ffmpeg.py
│   ├── filename.py
│   └── thumbnail_cache.py
├── repositories/
│   ├── database.py
│   ├── settings_repository.py
│   └── jobs_repository.py
└── migrations/
    └── 001_initial.sql
```

`DownloadManager` vlastní `asyncio.Queue` a `Semaphore`. Pro každou aktivní
úlohu spustí nový proces yt-dlp. PID a strom podprocesů sleduje `ProcessManager`.
Pozastavení a zrušení se vztahuje na celý strom, tedy i na běžící FFmpeg.

Změny průběhu se do SQLite zapisují nejvýše jednou za 500 ms a současně se
odesílají připojenému frontendu. Databáze tak nebude přetěžována každým řádkem.

## 9. Frontendová struktura

```text
frontend/
├── index.html
├── assets/
│   ├── icons/
│   └── logo.svg
├── css/
│   ├── tokens.css             # barvy, mezery, typography
│   ├── base.css
│   ├── components.css
│   └── responsive.css
└── js/
    ├── app.js                 # bootstrap aplikace
    ├── api.js                 # Fetch + API error mapping
    ├── socket.js              # reconnect WebSocketu
    ├── store.js               # minimální centrální stav
    ├── router.js              # hlavní pohled / historie / nastavení
    ├── formatters.js
    └── views/
        ├── preview.js
        ├── queue.js
        ├── history.js
        └── settings.js
```

Externí názvy a texty se zapisují pouze pomocí `textContent`. Obrázky dostanou
`loading="lazy"`, ovládací prvky popisky a celé UI bude ovladatelné klávesnicí.
HTML dialogy budou správně řídit fokus a průběh bude dostupný přes `aria-live`.

## 10. REST API a WebSocket

```text
POST   /api/v1/preview
POST   /api/v1/jobs
GET    /api/v1/jobs
GET    /api/v1/jobs/{job_id}
POST   /api/v1/jobs/{job_id}/pause
POST   /api/v1/jobs/{job_id}/resume
POST   /api/v1/jobs/{job_id}/cancel
POST   /api/v1/jobs/{job_id}/retry-failed
GET    /api/v1/settings
PATCH  /api/v1/settings
GET    /api/v1/thumbnails/{token}
WS     /api/v1/events
```

Příklad vytvoření úlohy:

```json
{
  "sourceUrl": "https://www.youtube.com/watch?v=...",
  "scope": "single",
  "preset": "video_mp4",
  "quality": "1080p",
  "targetDirectory": null,
  "conflictPolicy": "skip"
}
```

`targetDirectory: null` znamená použít uloženou výchozí složku. Backend nikdy
nepřijme vlastní format selector ani cestu k binárce z frontendu.

WebSocket event:

```json
{
  "type": "job.progress",
  "jobId": "uuid",
  "status": "downloading",
  "itemIndex": 12,
  "itemCount": 45,
  "percent": 63.4,
  "speedBytesPerSecond": 5823000,
  "etaSeconds": 38
}
```

Při odpojení WebSocketu se frontend exponenciálně znovu připojí a následně
obnoví stav přes `GET /jobs`, takže neztratí průběh.

## 11. Databázový model SQLite

```sql
PRAGMA foreign_keys = ON;
PRAGMA journal_mode = WAL;

CREATE TABLE settings (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    default_download_dir TEXT NOT NULL,
    default_preset TEXT NOT NULL DEFAULT 'video_mp4',
    default_quality TEXT NOT NULL DEFAULT 'best',
    concurrent_downloads INTEGER NOT NULL DEFAULT 1,
    conflict_policy TEXT NOT NULL DEFAULT 'skip',
    theme TEXT NOT NULL DEFAULT 'system',
    open_folder_on_complete INTEGER NOT NULL DEFAULT 0,
    updated_at TEXT NOT NULL
);

CREATE TABLE download_jobs (
    id TEXT PRIMARY KEY,
    source_url TEXT NOT NULL,
    source_kind TEXT NOT NULL CHECK (source_kind IN ('video', 'playlist')),
    title TEXT NOT NULL,
    source_id TEXT,
    channel TEXT,
    thumbnail_url TEXT,
    target_root TEXT NOT NULL,
    target_subfolder TEXT,
    preset TEXT NOT NULL,
    quality TEXT NOT NULL,
    status TEXT NOT NULL,
    item_count INTEGER NOT NULL DEFAULT 1,
    completed_count INTEGER NOT NULL DEFAULT 0,
    failed_count INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    started_at TEXT,
    finished_at TEXT,
    error_code TEXT,
    error_message TEXT
);

CREATE TABLE download_items (
    id TEXT PRIMARY KEY,
    job_id TEXT NOT NULL REFERENCES download_jobs(id) ON DELETE CASCADE,
    source_id TEXT,
    playlist_index INTEGER,
    title TEXT,
    status TEXT NOT NULL,
    progress REAL NOT NULL DEFAULT 0,
    downloaded_bytes INTEGER,
    total_bytes INTEGER,
    output_path TEXT,
    error_code TEXT,
    error_message TEXT,
    UNIQUE(job_id, source_id)
);

CREATE INDEX idx_jobs_status ON download_jobs(status);
CREATE INDEX idx_items_job ON download_items(job_id, playlist_index);
```

Databáze bude v `%LOCALAPPDATA%\YouDownloader\app.db`, logy v podsložce
`logs` a thumbnail cache v `cache\thumbnails`. Mediální soubory se nikdy
neukládají do aplikačních dat.

## 12. Stavový automat úlohy

```text
queued ──► resolving ──► downloading ──► postprocessing ──► completed
  │             │              │                │
  ├─────────────┴──────────────┴────────────────┴──► failed
  │                            │
  │                            ├──► paused ──► downloading
  └────────────────────────────┴──► cancelled
```

Po pádu aplikace se stavy `resolving`, `downloading` a `postprocessing` při
dalším spuštění změní na `interrupted`. Uživatel je může obnovit. Hotové položky
playlistu se znovu nestahují.

## 13. Chyby a zprávy pro uživatele

| Kód | Zpráva v UI |
|---|---|
| `INVALID_URL` | Vložte platný odkaz na YouTube. |
| `VIDEO_UNAVAILABLE` | Video není dostupné. |
| `PRIVATE_VIDEO` | Video je soukromé. |
| `AGE_OR_LOGIN_REQUIRED` | Obsah vyžaduje přihlášení a aplikace jej nestahuje. |
| `DRM_PROTECTED` | Obsah je technicky chráněný a nelze jej stáhnout. |
| `NO_COMPATIBLE_FORMAT` | Pro zvolený formát nebyla nalezena vhodná stopa. |
| `DISK_FULL` | Na cílovém disku není dostatek místa. |
| `TARGET_NOT_WRITABLE` | Do vybrané složky nelze zapisovat. |
| `NETWORK_ERROR` | Připojení bylo přerušeno; úlohu lze obnovit. |
| `POSTPROCESS_FAILED` | Stažení proběhlo, ale převod souboru selhal. |

UI ukáže lidskou zprávu a diagnostické ID. Podrobný stderr zůstane v lokálním
logu, oříznutý a zbavený tokenů či citlivých parametrů.

## 14. Bezpečnost

- Server naslouchá jen na `127.0.0.1` a náhodném portu.
- Každý požadavek vyžaduje náhodný session token; Uvicorn access log je vypnutý.
- CORS nepovoluje cizí originy.
- Přijímají se jen povolené YouTube HTTPS domény.
- Procesy běží bez shellu a s pevně definovanou sadou argumentů.
- Cílová cesta se normalizuje a kontroluje před vytvořením souboru.
- Frontend nesmí předat cestu k yt-dlp/FFmpeg ani vlastní parametry příkazu.
- Přibalené binárky mají v release manifestu SHA-256 a ověřený zdroj.
- Cookies, hesla a YouTube účet nejsou v MVP podporovány ani ukládány.
- Aplikace nepoužívá YouTube Data API, takže nepotřebuje API klíč.

## 15. Balení a aktualizace

```text
YouDownloader.exe
resources\frontend\...
resources\bin\yt-dlp.exe
resources\bin\ffmpeg.exe
resources\bin\ffprobe.exe
THIRD_PARTY_LICENSES.txt
VERSION.json
```

PyInstaller vytvoří adresářovou `onedir` distribuci; je spolehlivější a rychleji
startuje než `onefile`, který se při každém spuštění rozbaluje. Inno Setup z ní
vytvoří běžný instalátor.

FFmpeg licence závisí na přesné sestavě a zapnutých kodecích. Před distribucí je
nutné zvolit kompatibilní build, přiložit jeho licenci a splnit požadavky LGPL
nebo GPL. Licence všech Python balíčků, yt-dlp a FFmpeg se v CI vygenerují do
`THIRD_PARTY_LICENSES.txt`.

Aktualizace aplikace musí být podepsaná. yt-dlp se aktualizuje jen z ověřeného
release kanálu, s kontrolou podpisu/checksumu a nikdy během aktivní úlohy.

## 16. Struktura celého repozitáře

```text
YouDownloader/
├── frontend/
├── backend/
├── resources/
│   └── bin/
├── tests/
│   ├── unit/
│   ├── integration/
│   ├── e2e/
│   └── fixtures/               # uložené anonymizované yt-dlp JSON
├── scripts/
│   ├── download_sidecars.ps1
│   ├── verify_checksums.py
│   └── build_installer.ps1
├── packaging/
│   ├── youdownloader.spec
│   └── installer.iss
├── pyproject.toml
├── requirements.lock
├── THIRD_PARTY_LICENSES.txt
└── BLUEPRINT.md
```

## 17. Testovací strategie

### Unit testy

- detekce `video`, `playlist` a hybridní URL,
- normalizace URL a odmítnutí nepovolených hostů,
- sanitizace názvů, rezervovaných jmen a dlouhých cest,
- převod předvolby na bezpečné yt-dlp argumenty,
- stavový automat úloh a mapování chyb.

### Integrační a E2E testy

- FastAPI endpointy proti dočasné SQLite databázi,
- parsování uložených JSON fixtures,
- fake proces generující průběh a chyby,
- obnovení přerušené úlohy,
- playlist s jednou nedostupnou položkou,
- zrušení procesu včetně potomků FFmpeg,
- vložení URL, načtení preview a přidání do fronty,
- změna výchozí složky a zachování po restartu,
- ovládání klávesnicí a accessibility kontrola.

Běžné CI nebude záviset na živém YouTube. Použije fixtures a lokální fake
server. Volitelný smoke test může pracovat jen s veřejným testovacím videem, ke
kterému má projekt oprávnění.

## 18. Realizační etapy

1. **Základ projektu — 1 až 2 dny:** FastAPI, pywebview, statické UI, SQLite
   migrace, známé systémové cesty a základní nastavení.
2. **Preview — 2 až 3 dny:** validace URL, yt-dlp JSON, video/playlist detekce,
   thumbnail proxy a chybové stavy.
3. **Jedno video — 3 až 4 dny:** fronta, MP4/MP3, WebSocket průběh, zrušení,
   temp soubory a historie.
4. **Playlisty — 2 až 4 dny:** podsložka, pořadí, částečná selhání, obnovení a
   opakování selhaných položek.
5. **Produkční dokončení — 4 až 7 dní:** testy, přístupnost, logy, licence,
   PyInstaller, instalátor a aktualizace.

Použitelné MVP představuje přibližně 2 až 3 týdny práce jednoho vývojáře.
Vyladěná podepsaná distribuční verze přibližně 3 až 5 týdnů.

## 19. Akceptační kritéria MVP

- Platná URL zobrazí metadata a thumbnail nebo srozumitelnou chybu.
- Aplikace správně rozliší video, playlist a hybridní odkaz.
- Uživatel může zvolit MP4, MP3, M4A nebo WebM a podporovanou kvalitu.
- Výchozí složka se uloží a přežije restart aplikace.
- Samostatné video se uloží přímo do cílové složky.
- Playlist vytvoří sanitizovanou podsložku podle názvu a soubory očísluje.
- Selhání jedné položky nezastaví celý playlist.
- Úlohu lze pozastavit, obnovit, zrušit a po pádu aplikace znovu obnovit.
- Finální soubor se objeví až po úspěšném dokončení a ověření.
- Cesty s mezerami, diakritikou a dlouhými názvy fungují na Windows.
- Aplikace neukládá hesla ani cookies a neobchází chráněný obsah.

## 20. Funkce po MVP

- výběr konkrétních videí nebo rozsahu playlistu,
- vložení thumbnailu, názvu interpreta a dalších tagů do MP3,
- titulky, kapitoly a volba audio jazyka,
- historie vyhledávání a hromadné vložení více URL,
- omezení rychlosti a plánování downloadů,
- buildy pro macOS a Linux.

Navržené API a databáze s těmito funkcemi počítají, ale nezvětšují první verzi.

## 21. Referenční dokumentace

- [yt-dlp — oficiální repozitář a použití](https://github.com/yt-dlp/yt-dlp)
- [FastAPI — WebSockets](https://fastapi.tiangolo.com/advanced/websockets/)
- [pywebview — API](https://pywebview.flowrl.com/3.7/guide/api.html)
- [Python sqlite3](https://docs.python.org/3/library/sqlite3.html)
- [FFmpeg — formáty](https://ffmpeg.org/ffmpeg-formats.html)
