# Seriale w serwisach

Samoaktualizująca się baza seriali dostępnych w polskich serwisach streamingowych
(Netflix, HBO Max, Disney+, Prime Video, SkyShowtime, Apple TV+) z jakością wideo,
ścieżkami audio, napisami, długością odcinków i dostępnością na świecie.

## Jak to działa

| Miejsce | Co tam jest |
|---|---|
| **Kod** (ten folder) | skrypty, szablon strony, ustawienia |
| **`.github/workflows/aktualizacja-seriali.yml`** (w głównym katalogu repo) | harmonogram – GitHub wymaga, żeby leżał tam, a nie w tym folderze |
| **Actions** | co 2 dni GitHub sam uruchamia aktualizację |
| **Releases → „dane-seriali”** | `seriale.html` (strona do pobrania), `seriale.db` (baza), comiesięczne kopie |

Każde uruchomienie:
1. pobiera ostatnią bazę z Releases,
2. pyta Streaming Availability API o **zmiany** od ostatniej aktualizacji (nowe seriale,
   nowe sezony, usunięte, zmienione audio/napisy/jakość, zapowiedzi),
3. uzupełnia dane z TMDB (długości odcinków, polskie opisy, dostępność na świecie),
4. generuje od nowa `seriale.html` i podmienia pliki w Releases.

Pełne pobranie całego katalogu robi się samo przy pierwszym uruchomieniu, a potem co 60 dni
(albo gdy aktualizacje nie działały dłużej niż 30 dni).

## Pierwsze uruchomienie

1. **Settings → Secrets and variables → Actions → New repository secret** – dodaj:
   - `SA_API_KEY` – klucz z developers.movieofthenight.com
   - `TMDB_API_KEY` – klucz z themoviedb.org (Ustawienia → API; krótki „API Key” albo długi „Read Access Token”)
2. **Actions → Aktualizacja bazy seriali → Run workflow** (tryb `auto`).
3. Po kilku minutach strona będzie w **Releases → dane-seriali → seriale.html**.

## Limit zapytań

W `config.json` ustawiony jest twardy limit **900 zapytań miesięcznie** do Streaming Availability.
Po jego osiągnięciu skrypt zapisuje postęp i kończy; resztę dokończy w kolejnym miesiącu.
Przewidywane zużycie: ok. 300 przy pierwszym pobraniu, potem ok. 150–350 miesięcznie.
Zużycie widać w podsumowaniu każdego uruchomienia (zakładka Actions). TMDB nie ma limitu miesięcznego.

## Tryby ręcznego uruchomienia

| Tryb | Co robi | Zużywa limit? |
|---|---|---|
| `auto` | to, co trzeba (domyślnie) | tak |
| `zmiany` | tylko zmiany od ostatniego razu | tak, mało |
| `pelne` | wymusza pełne pobranie katalogu | tak, ok. 300 |
| `tmdb` | tylko dane z TMDB | nie |
| `tylko_strona` | tylko generuje stronę od nowa (np. po zmianie szablonu) | nie |

## Zmiana ustawień (`config.json`)

- `serwisy` – lista serwisów. Podsumowanie uruchomienia pokazuje wszystkie serwisy, które API obsługuje w Polsce.
- `limit_zapytan_miesiecznie` – twardy limit zapytań.
- `pelne_odswiezenie_co_dni` – jak często robić pełne pobranie.

## Zmiana nazwy folderu

Jeśli zmienisz nazwę folderu `baza-seriali`, zmień też `FOLDER:` na górze pliku `.github/workflows/aktualizacja-seriali.yml`.

## Uruchomienie na własnym komputerze (opcjonalnie)

```
cd baza-seriali
export SA_API_KEY=...  TMDB_API_KEY=...
python skrypty/aktualizuj.py
python skrypty/generuj_strone.py
```

## Strona na GitHub Pages i logowanie

Każde uruchomienie workflow publikuje stronę pod adresem **https://cenflix.github.io/Projekt-Cenflix/**:
`seriale.html` jako `index.html` oraz `login.html` (strona logowania). Pliki w Releases zostają bez zmian.

**Jednorazowo:** Settings → Pages → Build and deployment → Source: **GitHub Actions**,
potem Actions → Aktualizacja bazy seriali → Run workflow (tryb `tylko_strona`).

Logowanie obsługuje [Supabase](https://supabase.com) (darmowy plan). Dopóki `supabase` w `config.json`
jest puste, przycisk „Zaloguj się” jest ukryty. W pliku pobranym z Releases i otwartym z dysku jest ukryty zawsze.

### Konfiguracja Supabase (jednorazowo)

1. Załóż konto i nowy projekt na supabase.com (region np. Frankfurt).
2. **Authentication → Sign In / Providers**: wyłącz **Allow new users to sign up** (rejestracji na razie nie ma).
3. **Authentication → Users → Add user → Create new user**: e-mail i hasło konta testowego,
   zaznacz **Auto Confirm User**.
4. **SQL Editor** – nadaj kontu wyświetlaną nazwę (podmień e-mail):
   ```sql
   update auth.users
   set raw_user_meta_data = coalesce(raw_user_meta_data, '{}'::jsonb) || '{"display_name": "Jan Flixer"}'
   where email = 'jan.flixer@example.com';
   ```
5. **Authentication → URL Configuration → Site URL**: `https://cenflix.github.io/Projekt-Cenflix/`.
6. **Project Settings → API** (lub **API Keys**): skopiuj **Project URL** i klucz publiczny
   (**publishable** albo **anon public** – NIE `service_role`/`secret`) i wpisz do `config.json`:
   ```json
   "supabase": {"url": "https://xxxx.supabase.co", "klucz": "sb_publishable_..."}
   ```
   Ten klucz jest z założenia publiczny i trafia do kodu strony. Klucza `service_role`/`secret` nigdy nie wpisuj.
7. Uruchom workflow w trybie `tylko_strona`.

## Źródła danych i regulamin

- Dostępność, jakość, audio i napisy: [Streaming Availability API by Movie of the Night](https://www.movieofthenight.com/about/api).
  Regulamin zabrania udostępniania samej bazy innym firmom/platformom – dlatego repozytorium jest prywatne.
- Długości odcinków, opisy i dostępność na świecie: [TMDB](https://www.themoviedb.org/) (dane o dostępności: JustWatch).
  *This product uses the TMDB API but is not endorsed or certified by TMDB.* Darmowy klucz TMDB – tylko do użytku niekomercyjnego.
- „Polskie audio” może oznaczać dubbing albo lektora – źródła tego nie rozróżniają.
