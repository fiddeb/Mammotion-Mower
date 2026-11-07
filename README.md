# Mammotion Open API för Home Assistant

En fristående custom integration för **Mammotions officiella Open API**, med
konfiguration direkt i Home Assistant. Integrationen använder `client_id` och
`client_secret` från utvecklarportalen.

API-underlag: [Mower APIs](https://developer.mammotion.com/apis/debug/mowing),
[autentisering](https://developer.mammotion.com/docs/authorization) och den
[publika OpenAPI-specifikationen](https://api-open.mammotion.com/api-docs).
En kopia av specifikationen finns i [docs/mammotion-openapi.json](docs/mammotion-openapi.json).

## Funktioner

- Automatisk upptäckt av kontots klippare, även när nya tillkommer.
- En `lawn_mower` per klippare: starta, pausa, återuppta, stoppa och kör hem.
- Start utan sparad uppgift använder `CMD_START`. Start av pausad klippare använder `RESUME`.
- Välj en sparad uppgift och tryck på **Starta vald uppgift**. Valet återställs efter omstart;
  att välja en uppgift startar aldrig klipparen.
- Separata knappar för återuppta, avbryt hemkörning och uppdatera.
- Batteri, rå driftstatus, laddning, felstatus, firmware, nätverk, Wi-Fi- och mobilsignal.
- Anslutningssensor som visar frånkopplad klippare; övriga värden blir otillgängliga.
- Åtgärder för sparade uppgifter, samtliga sju API-kommandon, felhistorik och arbetsparametrar.
- SSE för **LUBA 3 AWD**, med förnyelse före tio minuters utgång, återanslutning med
  ökande väntetid och stopp vid serverns besked att en annan klient tagit över.
- Inställningar för hämtningsintervall och SSE, ominloggning och avidentifierad diagnostik.
- Svenska och engelska texter.

## Installera

Kräver Home Assistant **2026.10 eller senare**. Testad HA-version dokumenteras i
[docs/verification.md](docs/verification.md).

1. Kopiera `custom_components/mammotion_openapi` till
   `/config/custom_components/mammotion_openapi` på din Home Assistant-installation.
2. Starta om Home Assistant.
3. Skapa en credential i [Mammotions utvecklarportal](https://developer.mammotion.com/).
   Spara `client_id` och `client_secret` när de visas.
4. Öppna **Inställningar → Enheter och tjänster → Lägg till integration** och välj
   **Mammotion Open API**.
5. Ange `client_id` och `client_secret`. Kontots tillgängliga klippare läggs till automatiskt.

Integrationen kan installeras via HACS genom att lägga till
`https://github.com/fiddeb/Mammotion-Mower` som ett eget repository av typen **Integration**.
Starta om Home Assistant efter nedladdningen och lägg till **Mammotion Open API**
under **Inställningar → Enheter och tjänster**.

### Installation och uppdatering från en utcheckning

Kör i Home Assistants Terminal & SSH, där `/config` är din Home Assistant-konfiguration:

```sh
sh /sökväg/till/mammotion/scripts/package-homeassistant.sh \
  /config/custom_components/mammotion_openapi
```

Skriptet installerar integrationens filer och sparar den tidigare versionen i en separat
backupmapp vid uppdatering. Övriga integrationer och dina inställningar lämnas kvar.
Starta sedan om Home Assistant. Vid första installationen lägger du till **Mammotion Open API**
under **Inställningar → Enheter och tjänster** och anger `client_id` och `client_secret`.

Du kan också klona från GitHub och installera med samma upplägg som för Zaptec:

```sh
mammotion_update_dir=$(mktemp -d)
git clone --depth 1 --branch main \
  https://github.com/fiddeb/Mammotion-Mower.git "$mammotion_update_dir" &&
sh "$mammotion_update_dir/scripts/package-homeassistant.sh" \
  /config/custom_components/mammotion_openapi
```

Detta är en custom integration. Installationsmålet är Home Assistants `custom_components`-mapp.

Under integrationens **Konfigurera** kan du välja 30–3600 sekunders hämtningsintervall
(standard 60) och slå av eller på SSE. Sparade uppgifter hämtas var femtonde minut;
knappen **Uppdatera** hämtar listan direkt. Nya klippare upptäcks vid nästa hämtning.

## Automationer

Ersätt entitetsnamnen med dina egna. Uppgifterna måste först skapas i Mammotion-appen.

```yaml
alias: Klipp framsidan
triggers:
  - trigger: time
    at: "10:00:00"
actions:
  - action: mammotion_openapi.start_task
    target:
      entity_id: lawn_mower.min_klippare
    data:
      task_name: Framsidan
```

Alla dokumenterade kommandon finns via `mammotion_openapi.send_command`:

```yaml
action: mammotion_openapi.send_command
target:
  entity_id: lawn_mower.min_klippare
data:
  command: CANCEL_RETURN
```

Tillåtna värden: `CMD_START`, `START`, `PAUSE`, `RESUME`, `STOP`, `RETURN`, `CANCEL_RETURN`.
`START` kräver även `task_name`.

Felhistorik returnerar en sida med `records`, `total`, `pageNumber`, `pageSize` och
`hasMore`. Hämta nästa sida med `page_number` om fler poster finns. Historiska fel
används inte som indikator på ett aktivt fel.

```yaml
action: mammotion_openapi.get_error_history
target:
  entity_id: lawn_mower.min_klippare
data:
  page_number: 1
  page_size: 10
  start_date: "2026-11-01"
  end_date: "2026-11-07"
response_variable: historik
```

```yaml
action: mammotion_openapi.get_work_parameters
target:
  entity_id: lawn_mower.min_klippare
response_variable: parametrar
```

Home Assistant returnerar svaren under respektive entitets-ID i svarsdatan.
Arbetsparametrarna returneras med API:ts ursprungliga fältnamn. Enheter för bland annat
`knifeHeight` och `speed` är inte specificerade i schemat, så integrationen gissar inga enheter.

## Realtidsmeddelanden

SSE aktiveras automatiskt för modeller vars modellnamn innehåller `LUBA 3 AWD`, om
inställningen är på. Övriga modeller använder regelbunden REST-hämtning.
Alla dokumenterade egenskaper prenumereras, inklusive `ERR_CODE` och `MSG_NOTICE`.
Högst 20 klippare skickas i varje prenumerationsanrop.

Meddelanden skickas på Home Assistants lokala eventbuss som
`mammotion_openapi_message`, med fälten `config_entry_id` och `message`.
`message` innehåller serverns ursprungliga JSON, exempelvis `pushTag`, `pushType` och `pushData`.
Lyssna på eventet under **Utvecklarverktyg → Händelser** för att se ditt devices format.
Event kan innehålla position och andra enhetsuppgifter.

API:t beskriver egenskapsnycklarna men inte payloadformat för alla egenskaper. Därför
bevaras deras originalformat på eventbussen. Typade sensorer uppdateras med en samordnad
REST-hämtning efter push, som tätast var femtonde sekund. Stora kartor och körspår
lagras inte som sensorattribut. Det finns inget inbyggt kart- eller kamerakort.

En SSE-anslutning per utvecklarkonto används. Om en annan klient tar över stannar
automatisk återanslutning enligt API-dokumentationen. Ladda om integrationen när du
vill ansluta igen. REST-hämtningen fortsätter även när SSE är frånkopplat.

## Begränsningar och felsökning

- Stödet motsvarar de sju REST-operationerna i den sparade OpenAPI-specifikationen.
  API:t har ingen dokumenterad funktion för att ändra klipphöjd, rita zoner, redigera
  scheman, uppdatera firmware eller spela kameravideo. Sådana reglage exponeras inte.
- `Mapping`, `Updating` och okänd driftstatus visas i statussensorn. Gräsklipparens
  standardentitet har inget motsvarande aktivitetstillstånd och visar därför okänt.
  Laddning mappas till dockad; standby mappas till vilande, eftersom dockstatus saknas.
- Om API:t nekar behörighet eller inloggning ber Home Assistant om nya credentials.
  Vid HTTP 429 respekteras `Retry-After`. Kommandon återförsöks inte efter timeout,
  eftersom klipparen kan ha tagit emot dem trots ett förlorat svar.
- IP-sensorn är avstängd från början och kan aktiveras på enhetssidan.
- Diagnostik innehåller inte credentials, token, enhets-ID, namn, IP eller platsdata.
- Ingen fysisk klippare eller ditt konto har använts för verifiering. Installation,
  API-kontrakt och felhantering verifieras med simulerade HTTP-svar och Home Assistant.
  Praktisk verifiering med riktiga credentials och klippare återstår.

## Utveckling

```sh
uv venv --python 3.14 .venv-ha
UV_PROJECT_ENVIRONMENT=.venv-ha uv sync --frozen --group dev
.venv-ha/bin/ruff check .
.venv-ha/bin/pytest -q
```

Kontinuerliga kontroller finns i `.github/workflows/validate.yml`.
