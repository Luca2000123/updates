# Update hub

Un solo posto dove si dichiara *cosa esiste* di ogni app, per ogni piattaforma.
I binari restano nelle GitHub Releases dei repo delle app; qui ci sono solo i manifest,
pubblicati come file statici su GitHub Pages.

Il punto: **il client non decide piu' quale file gli serve, legge la sua riga nel manifest**.
Aggiungere un'app o una piattaforma costa un file di configurazione, non codice.
E nessun client chiama piu' l'API di GitHub, che senza autenticazione e' limitata a
60 richieste/ora *per indirizzo IP*.

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
release_repo = "Luca2000123/my_streaming-releases"

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

## Pubblicare una release

Il repo dell'app compila e carica gli asset con i nomi convenzionali, poi manda un
`repository_dispatch` all'hub. L'hub non ricompila e non riscarica niente: si fida degli
hash calcolati dove i file sono appena stati prodotti.

Job da aggiungere al workflow di release dell'app:

```yaml
  notify-hub:
    needs: [build-and-release, build-windows, build-webos]
    runs-on: ubuntu-latest
    env:
      APP_ID: com.luca2000123.mystreaming
      HUB_REPO: Luca2000123/updates
      RELEASES_REPO: Luca2000123/my_streaming-releases
      TAG: ${{ needs.build-and-release.outputs.tag }}
      VERSION: ${{ needs.build-and-release.outputs.version }}
    steps:
      - uses: actions/setup-python@v6
        with:
          python-version: '3.12'

      - name: Prendi gli strumenti dell'hub
        run: |
          BASE="https://raw.githubusercontent.com/${HUB_REPO}/main/tools"
          curl -fsSL -o hublib.py "$BASE/hublib.py"
          curl -fsSL -o make_payload.py "$BASE/make_payload.py"

      - name: Scarica gli asset appena pubblicati
        env:
          GH_TOKEN: ${{ secrets.RELEASES_REPO_TOKEN }}
        run: gh release download "$TAG" --repo "$RELEASES_REPO" --dir assets --pattern "${APP_ID}-*"

      - name: Costruisci il payload
        run: python make_payload.py --app-id "$APP_ID" --version "$VERSION" --tag "$TAG" --repo "$RELEASES_REPO" --dir assets --out payload.json

      - name: Notifica l'hub
        env:
          GH_TOKEN: ${{ secrets.UPDATE_HUB_TOKEN }}
        run: |
          jq -n --slurpfile p payload.json '{event_type: "release-published", client_payload: $p[0]}' > dispatch.json
          gh api "repos/${HUB_REPO}/dispatches" --input dispatch.json
```

Poi `publish.yml` valida e committa `releases/**`, e il push fa ripartire `build-site.yml`
che rigenera e ridistribuisce il sito.

Per rimediare a una release sbagliata: lanciare `publish` a mano da Actions, incollando il
payload e spuntando `allow_rollback`.

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

- **Pages**: Settings → Pages → Source: **GitHub Actions**. Il primo `build-site` pubblica.
- **Token**: un PAT fine-grained sul solo repo `updates`, permesso *Contents: read and write*,
  salvato come secret `UPDATE_HUB_TOKEN` nel repo di ogni app. Se le app finiscono in una
  organizzazione, diventa un organization secret e si ruota in un posto solo.
- `base_url` in `hub.toml` deve combaciare con l'URL reale di Pages.

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
