# Protokoll Quartierfuchs ↔ Home Assistant (Version 1)

Diese Beschreibung ist der Vertrag zwischen der Integration (`custom_components/quartierfuchs`) und dem Quartierfuchs-Portal (`module/HomeAssistant/`).

## 1. Kopplung (HTTPS)

Das Portal erzeugt pro Kopplungsvorgang einen Einmalcode (Vorschlag: Format `QF-XXXX-XXXX`, 15 Minuten gültig, nur einmal verwendbar), gebunden an `id_vermieter`.

### Anfrage

`POST https://api.quartierfuchs.de/v1/homeassistant-kopplung`, `Content-Type: application/json`

Die Integration setzt die Adresse aus der Portal-Adresse (Vorgabe `https://api.quartierfuchs.de`) und dem festen Pfad `/v1/homeassistant-kopplung` zusammen. Im Portal ist das die Route `'v1/homeassistant-kopplung'` mit `'zugang' => 'token'` (eigene Prüfung im Endpunkt, keine Portal-Sitzung).

```json
{
  "code": "QF-7K2M-9XPA",
  "instanz_id": "0f1c6d0e-…",
  "instanz_name": "Zuhause",
  "ha_version": "2026.10.2",
  "protokoll_version": 1
}
```

- `code` wird von der Integration in Großbuchstaben und ohne Leerzeichen gesendet.
- `instanz_id` ist die eindeutige, dauerhafte ID der Home-Assistant-Instanz.

### Antworten

| HTTP | Bedeutung |
|---|---|
| 200 | Kopplung erfolgreich, Zugangsdaten im Body |
| 400 | Anfrage fehlerhaft |
| 404 | Code unbekannt |
| 409 | Code bereits verwendet |
| 410 | Code abgelaufen |
| sonst | Portalfehler |

Body bei 200 (Format von `Antwort::erfolg()`; zusätzliche Felder wie `success` und `message` ignoriert die Integration):

```json
{
  "success": true,
  "message": "Gekoppelt.",
  "broker_host": "mqtt.kretix.de",
  "broker_port": 8883,
  "broker_tls": true,
  "benutzername": "v12-a3f9c2e1",
  "passwort": "…",
  "topic_basis": "qf/v12-a3f9c2e1",
  "vermieter_name": "Haffquartier"
}
```

Regeln für das Portal:

- `benutzername` besteht nur aus Kleinbuchstaben, Ziffern und Bindestrichen (keine `/`, `+`, `#`).
- `topic_basis` ist immer `qf/<benutzername>`.
- Bei erneuter Kopplung derselben `instanz_id` für denselben Vermieter wird **derselbe `benutzername`** mit einem **neuen Passwort** vergeben. Die Integration bricht sonst die Neuanmeldung mit „falsches Konto“ ab.
- Das Passwort wird nur einmal in dieser Antwort übertragen und im Portal nicht gespeichert; im Broker liegt es als Hash.

## 2. Broker

- Mosquitto 2.0 mit Dynamic-Security-Plugin, MQTT 3.1.1, TLS auf Port 8883 (`mqtt.kretix.de`).
- **Jede Verbindung braucht eine eigene, nicht leere Client-ID** (`allow_zero_length_clientid false`). Die Integration verwendet `ha-<benutzername>`.
- Last Will der Integration: `<topic_basis>/status` = `offline` (retained).

### Zugänge und Rollen

| Zugang | Rolle | Zweck |
|---|---|---|
| `qf-admin` | `admin` | nur für den Betreiber (Wartung per `mosquitto_ctrl`) |
| `qf-portal` | `qf-portal` | Datenverkehr des Portals |
| `qf-portal-verwaltung` | `qf-verwaltung` | Anlegen und Löschen der Instanz-Zugänge |
| `<benutzername>` | `qf-i-<benutzername>` | je gekoppelte Home-Assistant-Instanz |

Rolle `qf-portal`:

| ACL-Typ | Topic |
|---|---|
| subscribePattern | `qf/+/status`, `qf/+/entitaeten`, `qf/+/zustand/#`, `qf/+/antwort` |
| publishClientSend | `qf/+/befehl`, `qf/+/status`, `qf/+/entitaeten`, `qf/+/zustand/#` |

Schreibrecht auf `status`, `entitaeten` und `zustand/#` dient nur zum Aufräumen (leere Retained-Nachrichten beim Entkoppeln).

Rolle `qf-verwaltung`:

| ACL-Typ | Topic |
|---|---|
| publishClientSend | `$CONTROL/dynamic-security/v1` |
| subscribePattern | `$CONTROL/dynamic-security/v1/response` |
| publishClientReceive | `$CONTROL/dynamic-security/v1/response` |

### Instanz-Zugänge

Das Dynamic-Security-Plugin von Mosquitto 2.0 kennt **keine Platzhalter** wie `%u` in ACLs. Deshalb bekommt jede gekoppelte Instanz eine **eigene Rolle** `qf-i-<benutzername>` mit genau ihrem Bereich.

Kopplung – das Portal sendet als `qf-portal-verwaltung` an `$CONTROL/dynamic-security/v1`:

```json
{"commands": [
  {"command": "createRole", "rolename": "qf-i-v12-a3f9c2e1",
   "acls": [
     {"acltype": "publishClientSend", "topic": "qf/v12-a3f9c2e1/#", "priority": 5, "allow": true},
     {"acltype": "subscribePattern",  "topic": "qf/v12-a3f9c2e1/#", "priority": 5, "allow": true}
   ]},
  {"command": "createClient", "username": "v12-a3f9c2e1", "password": "…",
   "clientid": "ha-v12-a3f9c2e1",
   "roles": [{"rolename": "qf-i-v12-a3f9c2e1", "priority": 5}]}
]}
```

Mit `clientid` darf sich der Zugang nur mit genau dieser Client-ID anmelden – das ist die ID, die die Integration verwendet.

Erneute Kopplung (Zugang existiert bereits): `setClientPassword` mit neuem Passwort, danach `enableClient`.

Die Antwort des Plugins kommt auf `$CONTROL/dynamic-security/v1/response`; jeder Befehl wird einzeln mit `error` gemeldet, wenn er fehlschlägt (z. B. „Role already exists“).

## 3. Topics

Alle Topics liegen unterhalb von `<topic_basis>`.

| Topic | Richtung | Retained | Inhalt |
|---|---|---|---|
| `status` | HA → Portal | ja | `online` / `offline` |
| `entitaeten` | HA → Portal | ja | Liste der freigegebenen Entitäten |
| `zustand/<entity_id>` | HA → Portal | ja | aktueller Zustand einer Entität |
| `befehl` | Portal → HA | nein | Befehl |
| `antwort` | HA → Portal | nein | Ergebnis eines Befehls |

QoS ist durchgehend 1.

### `entitaeten`

```json
{
  "protokoll_version": 1,
  "integration_version": "0.2.0",
  "ha_version": "2026.10.2",
  "entitaeten": [
    {
      "entity_id": "climate.fewo3_wohnzimmer",
      "domain": "climate",
      "name": "FeWo 3 Wohnzimmer",
      "bereich": "FeWo 3",
      "geraet": "Thermostat Wohnzimmer",
      "device_class": null,
      "einheit": null,
      "dienste": {
        "set_temperature": ["hvac_mode", "target_temp_high", "target_temp_low", "temperature"],
        "set_hvac_mode": ["hvac_mode"],
        "set_preset_mode": ["preset_mode"],
        "turn_off": [],
        "turn_on": []
      }
    }
  ]
}
```

Diese Liste ist maßgeblich. Zustände von Entitäten, die nicht (mehr) in der Liste stehen, ignoriert das Portal. Die Liste wird bei jedem Verbindungsaufbau, nach jeder Änderung der Freigaben und auf Anfrage (`synchronisieren`) neu gesendet.

### `zustand/<entity_id>`

```json
{
  "entity_id": "climate.fewo3_wohnzimmer",
  "state": "heat",
  "attribute": {
    "current_temperature": 19.5,
    "temperature": 21,
    "hvac_action": "heating"
  },
  "zuletzt_geaendert": "2026-10-29T18:12:04.512345+00:00",
  "zuletzt_aktualisiert": "2026-10-29T18:15:44.120001+00:00"
}
```

- Ist die Entität in Home Assistant nicht vorhanden: `{"entity_id": "…", "state": null}`.
- Wird eine Freigabe entzogen, sendet die Integration eine leere Retained-Nachricht (Löschung).

### `befehl`

Dienst aufrufen:

```json
{
  "id": "a81f3c",
  "typ": "dienst",
  "domain": "climate",
  "service": "set_temperature",
  "entity_id": "climate.fewo3_wohnzimmer",
  "data": {"temperature": 22}
}
```

Weitere Typen:

- `{"id": "…", "typ": "synchronisieren"}`: Integration sendet `status`, `entitaeten` und alle Zustände neu.
- `{"id": "…", "typ": "ping"}`: Integration antwortet nur.

Die Integration prüft vor jeder Ausführung:

1. `entity_id` ist freigegeben.
2. `domain` passt zur `entity_id`.
3. `service` ist für die Domain erlaubt.
4. `data` enthält nur erlaubte Parameter. `entity_id` wird von der Integration selbst gesetzt; Ziele wie `area_id` oder `device_id` sind nicht zulässig.

### `antwort`

```json
{"id": "a81f3c", "erfolg": true, "fehler": null}
```

Befehle ohne `id` werden ausgeführt, aber nicht beantwortet.

Fehlerwerte der Integration:

| `fehler` | Bedeutung |
|---|---|
| `unbekannter_typ` | `typ` ist nicht `dienst`, `synchronisieren` oder `ping` |
| `entitaet_nicht_freigegeben` | Entität nicht freigegeben |
| `domain_passt_nicht` | `domain` passt nicht zur `entity_id` |
| `dienst_nicht_erlaubt` | Dienst für diese Domain nicht erlaubt |
| `ungueltige_daten` | `data` ist kein Objekt |
| `unzulaessige_parameter: …` | nicht erlaubte Parameter in `data` |
| `zeitueberschreitung` | Dienst hat nicht innerhalb von 15 Sekunden geantwortet |
| sonstiger Text | Fehlermeldung von Home Assistant |

## 4. Entkoppeln

Das Portal

1. sendet als `qf-portal-verwaltung` `deleteClient` (trennt die Verbindung sofort) und `deleteRole` für `qf-i-<benutzername>`,
2. löscht als `qf-portal` die Retained-Nachrichten unter `qf/<benutzername>/` (leere Nachrichten auf `status`, `entitaeten` und jedes bekannte `zustand/<entity_id>`).

Lehnt der Broker danach die Anmeldung ab, beendet die Integration ihre Verbindungsversuche und fordert in Home Assistant zur erneuten Kopplung auf.
