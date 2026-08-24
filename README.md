# Update hub

> Repository personale, non un servizio pubblico: vedi [`LEGAL.md`](LEGAL.md)
> per cosa contiene (e cosa non contiene) e per i termini d'uso.

Un solo posto dove si dichiara *cosa esiste* di ogni app, per ogni piattaforma.

Il punto: **il client non decide piu' quale file gli serve, legge la sua riga nel manifest**.
Aggiungere un'app o una piattaforma costa un file di configurazione, non codice.

Due backend per manifest+binari, a scelta per-app in `apps/<id>.toml`:

- **GitHub** (default, nessuna sezione `[firebase]`): Release del `release_repo`, manifest
  su GitHub Pages. Pubblico, nessuna autenticazione — pensato per repo dell'hub pubblici.
  Il client non chiama comunque l'API di GitHub, limitata senza autenticazione a
  60 richieste/ora *per indirizzo IP*.
- **Firebase Storage** (sezione `[firebase]` con `bucket = "..."`): manifest e binari nel
  bucket Storage dell'app, dietro **autenticazione Firebase** (`request.auth != null` nelle
  Storage Rules — vedi `storage.rules` nel repo dell'app). Adatto quando il repo dell'hub
  stesso e' privato e non deve esporre nulla pubblicamente: `com.luca2000123.mystreaming`
  usa questo backend.

```
apps/<app-id>.toml       cosa esiste (scritto a mano, una volta per app)
releases/<app-id>/*.json cosa e' pubblicato adesso (scritto dalla CI)
schema/manifest-v1.json  il contratto pubblico
tools/                   generatore e validatori (solo stdlib, zero dipendenze)
static/                  file copiati nella radice del sito
site/                    output generato, non committato
```

## Le due cose che non si cambiano piu'

**L'app-id** e **la platform key** finiscono compilati dentro i binari installati
sulle TV e sui telefoni della gente. Sbagliarli si paga con un rilascio manuale.

App-id: reverse DNS, minuscolo, uguale all'id webOS se l'app gira anche su webOS
(`com.luca2000123.mystreaming`). Il file deve chiamarsi `apps/<app-id>.toml`.

| Platform key | Quando |
|---|---|
| `android-all` | APK universale (`flutter build apk` senza `--split-per-abi`) |
| `android-arm64` | APK per ABI, se un giorno si divide |
| `webos-all` | `.ipk` per TV LG |
| `windows-x86_64` | Windows 64 bit |
| `darwin-aarch64` / `darwin-x86_64` | macOS Apple Silicon / Intel |
| `linux-x86_64` | Linux |
| `web-all` | PWA o sito, presente solo per comparire nel catalogo |

Sono le stesse chiavi che usa l'updater di Tauri: se un domani serve la sua
`latest.json`, e' una proiezione e non una traduzione.

## Nomi degli asset

```
<app-id>-<versione-normalizzata>-<platform-key>.<ext>
com.luca2000123.mystreaming-1.0.0-b67-android-all.apk
```

La versione normalizzata sostituisce il `+<build>` con `-b<build>`: **niente `+` nei nomi
dei file ne' nei tag**, perche' finirebbe nel path di un URL di download. Il `+` resta solo
nella versione mostrata all'utente.

La convenzione non e' solo documentata: `record_release.py` rifiuta un payload il cui
`filename` non corrisponde a quello atteso. Bonus, la regex di Obtainium diventa
`-android-all[.]apk$`.

## Versioni

Tre valori, tre usi distinti:

| Campo | Esempio | A cosa serve |
|---|---|---|
| `version` | `1.0.0+67` | quello che si mostra all'utente |
| `version_code` | `67` | **l'unico confronto che il client fa**: un intero, monotono crescente |
| versione webOS | `1.0.67` | semver puro, richiesto da `appinfo.json` e dal Homebrew Channel |

Se `version` contiene `+<build>`, `version_code` si deduce da solo. Se la versione e'
semver puro (`1.2.3`) va passato a mano con `--version-code`.

Registrare una release con un `version_code` non maggiore del precedente **fallisce**:
e' esattamente l'errore che rende un aggiornamento invisibile ai client.

## Changelog nel dialog

`notes` (testo libero, opzionale) finisce cosi' com'e' nel manifest e il client lo mostra
nel dialog di aggiornamento. Si passa con `--notes` a `make_payload.py`, tipicamente
alimentato dal body della Release GitHub appena creata (vedi il job `notify-hub` sotto).
Senza `--notes` il campo resta `null` e il client mostra un testo generico.

La versione webOS e' `<major>.<minor>.<build>`: monotona finche' il numero di build cresce
sempre, come fa un contatore globale in CI. Pubblicare tre build diverse tutte come `1.0.0`
(togliendo il `+build` e fermandosi la') significa che il Homebrew Channel non vedra' mai
un aggiornamento.

## Aggiungere un'app

Un file, `apps/<app-id>.toml`:

```toml
id = "com.luca2000123.mystreaming"
title = "MyStreaming"
description = "Client di streaming per Android, Windows e TV LG webOS."
icon = "https://raw.githubusercontent.com/Luca2000123/MyStreaming/main/webos/icon.png"
source_repo = "Luca2000123/MyStreaming"
release_repo = "Luca2000123/updates"
tag_prefix = "mystreaming"

[targets.android-all]
ext = "apk"
install = "apk"

[targets.windows-x86_64]
ext = "zip"
install = "zip-relay"

[targets.webos-all]
ext = "ipk"
install = "ipk-manual"
requires = { webosRelease = ">=5.0" }

[webos]
type = "web"
rootRequired = false
```

`release_repo` e' il repo dove stanno le Release; se manca vale `source_repo`.
La sezione `[webos]` e' obbligatoria se c'e' un target `webos-*`.
`requires` e' opzionale e viene passato al client cosi' com'e'.

Per usare Firebase Storage invece di GitHub Releases per binari+manifest (repo dell'hub
privato, niente di pubblico), aggiungi:

```toml
[firebase]
bucket = "mystreaming-e09a9.firebasestorage.app"
```

Con `[firebase]` presente, `asset_url()`/`manifest_url` puntano a
`https://firebasestorage.googleapis.com/v0/b/<bucket>/o/<path-url-encoded>?alt=media`
invece che a GitHub; `release_repo`/`tag_prefix` restano validi (servono comunque a evitare
collisioni di tag) ma non determinano piu' l'URL dei binari.

`tag_prefix` serve quando **piu' app pubblicano nello stesso `release_repo`**: i tag
diventano `mystreaming-v1.0.0-b67` invece di `v1.0.0-b67`, altrimenti la seconda app che
rilascia `v1.0.0` trova il tag occupato. Il generatore lo impone: un tag che non comincia col
prefisso viene rifiutato, e due app con lo stesso `(release_repo, tag_prefix)` non passano
la validazione. Se un'app ha il suo repo di release tutto suo, si puo' omettere.

## Pubblicare una release

Il repo dell'app compila, pubblica i binari (Release GitHub o bucket Firebase, secondo
`[firebase]` nel descrittore), poi manda un `repository_dispatch`. L'hub non ricompila e
non riscarica niente: si fida degli hash calcolati dove i file sono appena stati prodotti.

Serve **un solo secret** nel repo di ogni app, `UPDATE_HUB_TOKEN` (PAT fine-grained sul solo
repo `updates`, *Contents: read and write*): copre sia il checkout di `tools/` (se il repo
dell'hub e' privato) sia il dispatch. Col backend Firebase serve *anche* `GCP_SA_KEY` (la
chiave del service account che scrive sul bucket — vedi "Setup" sotto), nel repo dell'app.

Job da aggiungere al workflow di release dell'app (versione col backend Firebase — con
GitHub Releases il "Scarica gli asset" diventa `gh release download`, come nella cronologia
del repo prima di questa nota):

```yaml
  notify-hub:
    needs: [prepare, build-android, build-windows, build-webos]
    runs-on: ubuntu-latest
    env:
      APP_ID: com.luca2000123.mystreaming
      BUCKET: mystreaming-e09a9.firebasestorage.app
      HUB_REPO: Luca2000123/updates
      TAG: ${{ needs.prepare.outputs.tag }}
      VERSION: ${{ needs.prepare.outputs.version }}
    steps:
      # Repo updates privato: niente raw.githubusercontent.com senza token.
      - name: Checkout degli strumenti dell'hub
        uses: actions/checkout@v4
        with:
          repository: ${{ env.HUB_REPO }}
          token: ${{ secrets.UPDATE_HUB_TOKEN }}
          path: hub-tools

      - uses: actions/setup-python@v6
        with:
          python-version: '3.12'

      - uses: google-github-actions/auth@v2
        with:
          credentials_json: ${{ secrets.GCP_SA_KEY }}

      - name: Scarica gli asset appena pubblicati
        run: |
          mkdir -p assets
          gcloud storage cp "gs://${BUCKET}/releases/${APP_ID}/${TAG}/*" ./assets/

      # Le note vengono da un output del job che ha fatto il bump di versione
      # (il messaggio dell'ultimo commit "vero"), non da un body di Release:
      # senza Release non c'e' piu' nessun body da rileggere.
      - name: Costruisci il payload
        env:
          NOTES: ${{ needs.prepare.outputs.notes }}
        run: |
          python hub-tools/tools/make_payload.py --app-id "$APP_ID" --version "$VERSION" \
            --tag "$TAG" --dir assets --notes "$NOTES" --out payload.json

      - name: Notifica l'hub
        env:
          GH_TOKEN: ${{ secrets.UPDATE_HUB_TOKEN }}
        run: |
          jq -n --slurpfile p payload.json '{event_type: "release-published", client_payload: $p[0]}' > dispatch.json
          gh api "repos/${HUB_REPO}/dispatches" --input dispatch.json
```

Poi `publish.yml` valida e committa `releases/**`, e il push fa ripartire `build-site.yml`
che rigenera i manifest e li carica sul bucket (o su Pages, backend GitHub).

Per rimediare a una release sbagliata: lanciare `publish` a mano da Actions, incollando il
payload e spuntando `allow_rollback`.

## Taglio netto col vecchio updater

Scelta consapevole: **le installazioni antecedenti all'hub non si aggiornano da sole.** Il loro
updater non legge gli URL dal manifest, li ha compilati dentro nella forma
`releases/latest/download/<nome-fisso>` di un repo per app, e `latest` non significa piu' nulla
in un repo condiviso da tante app. Chi ha una versione vecchia la reinstalla a mano una volta;
dalla successiva l'aggiornamento passa dall'hub.

Il prezzo l'abbiamo pagato una volta sola per non trascinarlo: niente asset duplicati col nome
vecchio, niente tag col `+`, niente doppia sorgente nel client. Se un domani servisse una
transizione morbida per un'altra app, il descrittore supporta `legacy_name` per target e
`make_payload.py` ha `--legacy`: dichiarano gli asset col nome vecchio, il generatore ricorda a
ogni build che devono restare e avvisa se sparivano.

## Cosa fa il client con `install`

| `install` | Handoff |
|---|---|
| `apk` | scarica, verifica sha256, intent di installazione via FileProvider |
| `ipk-manual` | **solo notifica**: un'app webOS non puo' auto-installare un `.ipk` |
| `zip-relay` | scarica lo zip, scrive uno script staffetta che aspetta l'uscita del processo, sostituisce i file e riavvia |
| `nsis` / `msi` / `dmg` / `appimage` / `deb` | delega all'updater del framework |
| `script` | scarica, sostituisce, riavvia |
| `web` | niente, e' nel catalogo solo per essere elencata |

## L'algoritmo del client, identico in ogni stack

1. `GET <MANIFEST_URL>?t=<epoch>`, timeout ~10 s, segui i redirect.
   Il cache-buster serve perche' Pages sta dietro CDN.
2. Se `manifest_url_next` non e' `null`: rifai il GET su quell'URL, **una volta sola**, e
   persisti il nuovo indirizzo. E' la via d'uscita dall'hosting attuale senza ri-rilasciare
   le app: va onorata dalla prima versione.
3. Prendi `platforms[PLATFORM_KEY]` con la chiave **compilata nel build**. Se manca, esci in
   silenzio: per questa piattaforma non c'e' aggiornamento.
4. Confronta `version_code` con il tuo. Maggiore, aggiorna. Se `min_supported_code` e'
   maggiore del tuo, l'aggiornamento e' bloccante.
5. Scarica, verifica `sha256`, poi comportati secondo `install`.
6. Se qualcosa fallisce, nessun errore all'utente: e' un controllo in background.

## Setup, una volta sola

Backend GitHub (repo dell'hub pubblico):
- **Pages**: Settings → Pages → Source: **GitHub Actions**. Il primo `build-site` pubblica.
- **Token**: un PAT fine-grained sul solo repo `updates`, permesso *Contents: read and write*,
  salvato come secret `UPDATE_HUB_TOKEN` nel repo di ogni app. Copre creare la Release,
  caricare gli asset, mandare il dispatch.
- `base_url` in `hub.toml` deve combaciare con l'URL reale di Pages.

Backend Firebase (bucket per-app, repo dell'hub anche privato):
- **Attivare Storage una volta** sul progetto Firebase dell'app: Console → Storage →
  "Get started" (nessuna API automatizza questo primo click; serve anche il piano
  **Blaze**, pay-as-you-go — al volume di un'app personale resta nel livello sempre
  gratuito incluso, ma va collegato un metodo di pagamento).
- **Regole**: `storage.rules` nel repo dell'app (`allow read: if request.auth != null;`,
  stesso pattern di `firestore.rules`), deploy con `firebase deploy --only storage`.
- **Service account**, permesso *Storage Object Admin* **sul solo bucket** (non sul
  progetto): `gcloud iam service-accounts create` + `gcloud storage buckets
  add-iam-policy-binding gs://<bucket> --role=roles/storage.objectAdmin`, poi
  `gcloud iam service-accounts keys create` per la chiave JSON. Va salvata come secret
  `GCP_SA_KEY` **sia** nel repo dell'app (i job di build ci caricano i binari) **sia**
  in questo repo (`build-site.yml` ci carica i manifest).
- `UPDATE_HUB_TOKEN` serve comunque, per il checkout di `tools/` (repo privato) e il
  dispatch.

## Comandi locali

```
py tools/test_hub.py                              # test del generatore
py tools/build_manifests.py --strict              # genera site/
py tools/build_manifests.py --check --strict      # valida senza scrivere
py tools/validate_site.py --site site             # valida contro lo schema (serve jsonschema)
py tools/make_payload.py --app-id ... --version ... --dir assets
py tools/record_release.py --payload payload.json
```

`releases/**` e' la fonte di verita': `site/` e' rigenerabile e deterministico, quindi non
va committato.

## Trappole

- **I binari non vanno su Pages**: 1 GB di sito e 100 GB/mese di banda soft. Stanno nelle Release.
- **Il client non chiama l'API di GitHub**: 60 richieste/ora per IP, e gli utenti dietro CGNAT
  le esauriscono a vicenda.
- **Tauri pretende la firma** e valida tutto il documento: la vista `latest.json` per Tauri si
  genera solo quando la firma sara' attiva, non prima.
- **`signature` esiste ed e' `null`**: quando verra' popolata, i client vecchi non si rompono.
- **Il redirect dal dominio `*.github.io` verso un dominio custom non e' documentato**: l'unica
  garanzia di portabilita' e' `manifest_url_next`.
- **Piu' app nello stesso repo di release si pestano i tag**: `tag_prefix` per app, e
  `latest/download` non si usa mai (l'URL nel manifest ha il tag esatto).
- **Registrare due volte lo stesso `version_code`** rende il rilascio invisibile ai client: il
  generatore lo rifiuta invece di pubblicarlo.
- **Backend Firebase: l'anonimo non e' un muro.** Le Storage Rules con
  `request.auth != null` bloccano gli scraper occasionali e chi non ha mai visto l'app, ma
  l'API key del progetto (in `google-services.json`) non e' un segreto e chi ha l'APK puo'
  ottenere un token valido con `signInAnonymously()`. E' privacy/riduzione dell'esposizione
  pubblica, non un muro impenetrabile — per quello serve App Check (non implementato qui).
- **webOS col backend Firebase perde la scoperta automatica**: il Homebrew Channel non puo'
  autenticarsi, quindi non vede aggiornamenti da solo. L'app notifica comunque in-app
  (lei si autentica), ma l'installazione va fatta a mano (`ares-install` sull'ipk scaricato).
