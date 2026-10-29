# Quartierfuchs für Home Assistant

Verbindet Home Assistant mit [Quartierfuchs](https://quartierfuchs.de), der Verwaltung für Ferienwohnungen. Freigegebene Thermostate, Lampen, Schalter und Sensoren erscheinen im Quartierfuchs-Portal und lassen sich dort anzeigen und steuern, zum Beispiel um Wohnungen vor der Anreise aufzuheizen.

- **Keine Portfreigabe, kein VPN:** Home Assistant baut die Verbindung selbst verschlüsselt auf (MQTT über TLS). Das funktioniert hinter jedem Router, auch bei DS-Lite oder Mobilfunk.
- **Du entscheidest, was Quartierfuchs sieht:** Nur ausdrücklich freigegebene Geräte werden übertragen. Alle anderen bleiben unsichtbar.
- **Nur erlaubte Aktionen:** Quartierfuchs darf ausschließlich die unten aufgeführten Dienste aufrufen.

## Installation über HACS

[![In HACS öffnen](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=Quartierfuchs&repository=ha-quartierfuchs&category=integration)

Oder von Hand:

1. In HACS oben rechts auf die drei Punkte klicken und **Benutzerdefinierte Repositories** wählen.
2. `https://github.com/Quartierfuchs/ha-quartierfuchs` eintragen, Typ **Integration**, hinzufügen.
3. **Quartierfuchs** suchen, herunterladen und Home Assistant neu starten.

### Ohne HACS

Den Ordner `custom_components/quartierfuchs` nach `config/custom_components/` kopieren und Home Assistant neu starten.

## Einrichtung

1. Im Quartierfuchs-Portal **Home Assistant verbinden** öffnen und einen Kopplungscode erzeugen.
2. In Home Assistant unter **Einstellungen → Geräte & Dienste → Integration hinzufügen** nach **Quartierfuchs** suchen.
3. Den Kopplungscode eingeben.
4. Die Geräte auswählen, die Quartierfuchs sehen und steuern darf.

Die Auswahl lässt sich jederzeit über **Konfigurieren** bei der Integration ändern. Der Diagnose-Sensor **Verbindung** zeigt, ob die Verbindung zu Quartierfuchs besteht.

## Unterstützte Geräte und erlaubte Aktionen

| Typ | Anzeige | Erlaubte Aktionen |
|---|---|---|
| Klima (`climate`) | Ist- und Solltemperatur, Modus | `set_temperature`, `set_hvac_mode`, `set_preset_mode`, `turn_on`, `turn_off` |
| Licht (`light`) | Zustand, Helligkeit, Farbe | `turn_on` (Helligkeit, Farbtemperatur, Farbe, Übergang), `turn_off`, `toggle` |
| Schalter (`switch`) | Zustand | `turn_on`, `turn_off`, `toggle` |
| Sensor (`sensor`, `binary_sensor`) | Messwert bzw. Zustand | keine |

Alle anderen Dienste und Parameter werden von der Integration abgelehnt, auch wenn das Portal sie anfordert.

## Kopplung aufheben

Integration in Home Assistant löschen und die Kopplung im Portal entfernen. Wird die Kopplung nur im Portal entfernt, fordert Home Assistant zur erneuten Kopplung auf.

## Technik

Das Nachrichtenprotokoll zwischen Integration und Portal ist in [PROTOKOLL.md](PROTOKOLL.md) beschrieben.

## Lizenz

MIT, siehe [LICENSE](LICENSE).
