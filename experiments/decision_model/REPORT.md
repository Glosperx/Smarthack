# Model local de decizie: raport (Faza 2)

Data: 2026-11-08. Totul a rulat local pe MacBook-ul M5 cu 24 GB, prin transformers pe MPS, fără
niciun apel extern. Cifrele vin din `out/metrics.json`, iar fiecare decizie, marcată bună sau
proastă, e în `results/decisions_marked.csv`.

## Pe scurt

**Toate cele trei decizii rămân în cod, nu la un model.** Niciun model nu bate regula de azi
într-un mod care să conteze.

- **Decizia 1 (chemăm ML2?)**: toate modelele sunt clar mai slabe decât regula. Cel mai bun,
  Cerno 4B, ajunge la 0.838 acuratețe, regula la 0.950, iar intervalul de 95% al diferenței e
  negativ pentru fiecare model. Celelalte modele de 4B nu recunosc din cifre că două turbine cad
  în aceeași zi: la perechile din aceeași zi, Jeffan și KnowLine spun „nu” în 8 cazuri din 10.
- **Decizia 2 (canalul alertei)**: cu politica de azi scrisă în cerere, cele mai bune modele
  egalează regula, dar nu o depășesc. Jeffan are 0.938, Perplexity 0.912, regula 0.925, iar
  intervalul diferenței include 0. Unde eticheta mea diferă de regulă, modelele aplică politica
  literal, exact ca regula. Fără politica în cerere, scad la 0.45–0.68.
- **ROC AUC, „care decizii sunt cele mai bune”**: modelele decid bine doar canalul. AUC pentru
  „apel” este 0.97–0.99 la Jeffan, Perplexity, Cerno și GLiDE 2B, față de 0.941 la regulă, deci
  ordonează cazurile mai fin. Însă la un prag fixat pe cazurile clare, pe cazurile de graniță
  niciunul nu ia decizii mai bune decât regula (0.68–0.85 față de 0.853). La ML2, doar Cerno se
  apropie de regulă la AUC (0.953 față de 0.958); celelalte au 0.74–0.89.
- **Ce merită schimbat sunt regulile, nu modelul.** Testul a scos la iveală două slăbiciuni ale
  regulilor de azi, iar ambele se repară mai simplu în cod decât cu un model (vezi Recomandare).
- **Decizia 3 (ce turbină reparăm prima, cu timeline-ul în cerere)**: contează felul în care
  îi dai problema modelului.
  - Cu timeline-ul brut, Jeffan alege corect în 62–65% din cazuri.
  - Când codul calculează 2–4 planuri complete și Jeffan doar alege planul, ajunge la 88% (AUC
    0.964), cu 98% aceeași alegere în orice ordine a opțiunilor. Asta e peste „cel mai urgent
    întâi” (83%), dar nu semnificativ, și sub planificatorul exact (100%), care există deja în
    agent.
  - Ordinea pe care o folosește agentul azi nimerește doar în 37–45% din cazuri: asta trebuie
    reparat, tot în cod.
- **Costul unui model**: 9–13 GB memorie Metal și 0.8–1.6 s pe decizie la 4B. Regula costă 0.

## Ce am testat

| Model | Id pe Hub | Parametri | Licență | Full (Decision Index) |
|---|---|---:|---|---:|
| GLiDE 0.4B | `fastino/GLiDE-0.4B` | 0.39B | Fastino Community | 33.84 |
| GLiDE 0.8B | `fastino/GLiDE-0.8B` | 0.75B | Fastino Community | 36.36 |
| GLiDE 2B | `fastino/GLiDE-2B` | 1.88B | Fastino Community | 43.72 |
| Jeffan 4B | `tattrongvu/Jeffan-4B-2010` | 4.21B | Apache-2.0 | 52.21 |
| Perplexity Decider Flash | `perplexity-ai/pplx-decider-flash-v1.2` | 4.54B | Apache-2.0 | 54.29 |
| KnowLine 4B | `PelaAI/KnowLine-4B-Gen5.5` | 4.66B | Apache-2.0 | 55.99 |
| Cerno 4B | `apertixai/cerno-4b-v1.2` | 4.21B | Apache-2.0 | 53.88 |

GLiDE-9B a fost descărcat, dar scos din test la cererea ta: ar fi luat vreo 16 din cei 19 GB
Metal și 25 de minute, pentru o informație pe care regula o are deja exactă.

Fiecare model a primit 960 de cereri: 160 de scenarii × 2 variante de cerere × 3 ordini ale
opțiunilor.

- **Varianta `fara_politica`**: cererea explică doar ce înseamnă câmpurile (de exemplu, 8
  înseamnă „niciun defect prezis”, iar doar CRITICAL și WARNING au nevoie de reparație) și pune
  întrebarea.
- **Varianta `cu_politica`**: în plus, scrie în cerere regula de azi, cu pragurile ei.
- **Ordinea opțiunilor**: fiecare cerere a fost trimisă în 3 ordini. La ML2, a treia ordine o
  repetă pe prima, ca să verific și că aceeași cerere dă același răspuns.
- **Cererea**: o întrebare `choice` tipizată, iar răspunsul este o probabilitate pentru fiecare
  opțiune, citită dintr-un singur forward, fără text generat (`decision_model/requests.py`).
- **Cod de inferență**: am folosit codul de referință al fiecărui model, cu modificări mecanice
  pentru MPS, descrise în `decision_model/adapters.py`.

## Scenarii și etichete

- 80 de scenarii pentru fiecare decizie (`decision_model/scenarios.py`): 46 clare și 34 de
  graniță.
  - **Cazuri clare**: acoperă fiecare opțiune și au eticheta regulii, pe care o decide fără
    dubiu.
  - **Cazuri de graniță**: fereastra de exact 1 și exact 2 zile, rotunjirea în jos, turbine din
    alt parc, statusuri care nu cer reparație, valoarea 8 („niciun defect prezis”), încredere
    mică de la ML1, defecte deja produse, 0.69/0.70/0.71, 0.29/0.30/0.31, termenul de 2 zile,
    WATCH cu termen scurt, CRITICAL cu semnale contrare, statusuri necunoscute și două cazuri de
    text liber.
- **Etichetele cazurilor de graniță le-am pus eu (Opus)**, câte una cu motivul ei, în
  `data/border_labels.json`, înainte de a rula orice model (sha256
  `4b9f28e0…633fdc9`).
- Regula dură e respectată în etichete: o turbină CRITICAL primește întotdeauna și apel.

**Unde eticheta mea diferă de regula de azi (10 cazuri din 160).** Doar aici un model poate
câștiga ceva în fața regulii:

| Cazuri | Regula de azi | Eticheta mea | De ce |
|---|---|---|---|
| ML2: 4 cazuri cu `days_to_failure = 8` | `da` | `nu` | 8 înseamnă „niciun defect prezis în 7 zile”. Regula îl tratează ca ziua 8, iar două astfel de turbine „se suprapun”, deci ML2 e chemat degeaba. Aceeași problemă apare când lipsește termenul: agentul pune implicit 7 zile. |
| Canal: 4 cazuri NORMAL, termen ≤ 2 zile, probabilitate ≤ 0.10 | apel | doar email | Termenul vine de la un defect pe care ML1 însuși îl dă drept improbabil. Un apel trezește echipa de gardă pentru o alarmă aproape sigur falsă. |
| Canal: fum în nacelă (probabilitate 0.2) | nimic | apel | Risc de incendiu; regula nu citește textul. |
| Canal: scurgere de ulei vizibilă (0.25) | nimic | doar email | Merită cel puțin un email; regula nu citește textul. |

De aici vine acuratețea de 0.950 și 0.925 a regulii: greșește exact aceste cazuri. O observație
despre producție: în graful de azi, la decizia 2 ajung doar turbinele care au nevoie de reparație
(WARNING sau CRITICAL), deci `nimic` nu apare niciodată acolo. Testul acoperă tot domeniul
euristicii, cum ai cerut.

## Cum se citesc cifrele

- **acc**: acuratețea alegerii modelului (opțiunea cu probabilitatea cea mai mare, în ordinea
  inițială a opțiunilor) față de etichetă.
- **AUC**: ROC AUC.
  - La ML2, pe probabilitatea de `da`.
  - La canal, media one-vs-rest pe cele trei opțiuni. Separat, AUC pe întrebarea care contează
    cel mai mult: dăm apel sau nu.
  - Regula dă 0 sau 1, deci AUC-ul ei e punctul ei de funcționare. Un model cu probabilități
    gradate are aici un avantaj care nu înseamnă automat decizii mai bune.
- **Prag din clar**: pragul pe probabilitatea de `da` (respectiv de apel), ales doar pe cazurile
  clare și aplicat apoi pe cele de graniță. Arată dacă un model bine ordonat, dar prost
  calibrat, ar putea fi folosit cu un prag al nostru.
- **IÎ 95%**: interval bootstrap pereche (2 000 de reeșantionări pe scenarii) pentru diferența
  model minus regulă. Un interval care conține 0 înseamnă „nu se poate spune că e mai bun sau
  mai rău”.
- **ECE și Brier**: calibrarea probabilităților (0 e perfect).
- **Aceeași alegere în 3 ordini**: ponderea scenariilor în care alegerea nu se schimbă când
  schimbăm ordinea opțiunilor.

## Decizia 1: chemăm ML2?

Varianta `cu_politica` (cu `fara_politica`, toate modelele sunt și mai slabe sau egale):

| Model | acc | acc clar | acc graniță | AUC `da` | IÎ 95% acc față de regulă | ECE | aceeași alegere în 3 ordini |
|---|---:|---:|---:|---:|---|---:|---:|
| regula de azi | **0.950** | 1.000 | 0.882 | **0.958** | – | 0.050 | 1.000 |
| Cerno 4B | 0.838 | 0.913 | 0.735 | 0.953 | [−0.188, −0.037] | 0.127 | 0.938 |
| GLiDE 2B | 0.750 | 0.848 | 0.618 | 0.888 | [−0.300, −0.100] | 0.074 | 0.950 |
| Perplexity Flash | 0.700 | 0.739 | 0.647 | 0.839 | [−0.362, −0.138] | 0.134 | 0.988 |
| Jeffan 4B | 0.650 | 0.674 | 0.618 | 0.742 | [−0.425, −0.175] | 0.288 | 1.000 |
| KnowLine 4B | 0.637 | 0.674 | 0.588 | 0.748 | [−0.438, −0.200] | 0.252 | 0.988 |
| GLiDE 0.8B | 0.512 | 0.500 | 0.529 | 0.852 | [−0.562, −0.312] | 0.177 | 0.912 |
| GLiDE 0.4B | 0.550 | 0.587 | 0.500 | 0.762 | [−0.512, −0.300] | 0.005 | 0.963 |

Matricea de confuzie (rânduri: etichetă, coloane: alegerea modelului):

| | regula: da / nu | Cerno: da / nu | GLiDE 2B: da / nu | Perplexity: da / nu | Jeffan: da / nu |
|---|---|---|---|---|---|
| eticheta `da` (32) | 32 / 0 | 23 / 9 | 30 / 2 | 10 / 22 | 4 / 28 |
| eticheta `nu` (48) | 4 / 44 | 4 / 44 | 18 / 30 | 2 / 46 | 0 / 48 |

Ce se vede:

- Cerno 4B e excepția dintre modelele de 4B: recunoaște 8 din 10 perechi din aceeași zi și are
  un AUC aproape egal cu al regulii (0.953). Totuși ratează 9 din cele 32 de cazuri `da`, de
  exemplu jumătate din cazurile cu fereastra de exact o zi, deci la acuratețe rămâne sub regulă.
- Celelalte modele de 4B aproape că nu spun `da`. Nu deduc din numerele `days_to_failure` că două
  turbine cad în aceeași zi, chiar și când politica e scrisă în cerere: la „două în aceeași zi”
  au 2–3 din 10.
- GLiDE greșește invers: spune `da` și la turbine aflate departe una de alta.
- Singurul lucru pe care modelele îl prind și regula nu: cele 4 cazuri cu valoarea 8. Jeffan le
  nimerește pe toate 4, celelalte modele de 4B câte 3.

## Decizia 2: canalul alertei

Varianta `cu_politica`:

| Model | acc | acc clar | acc graniță | AUC macro | AUC apel | IÎ 95% acc față de regulă | IÎ 95% AUC apel față de regulă | ECE | aceeași alegere în 3 ordini | încălcări regula dură |
|---|---:|---:|---:|---:|---:|---|---|---:|---:|---:|
| regula de azi | 0.925 | 1.000 | 0.824 | 0.949 | 0.941 | – | – | 0.075 | 1.000 | 0/11 |
| Jeffan 4B | **0.938** | 1.000 | 0.853 | 0.973 | 0.970 | [0.000, +0.037] | [0.000, +0.066] | 0.058 | 0.988 | 0/11 |
| Cerno 4B | 0.900 | 1.000 | 0.765 | 0.985 | 0.977 | [−0.075, +0.025] | [+0.006, +0.075] | 0.083 | 0.988 | 0/11 |
| Perplexity Flash | 0.912 | 1.000 | 0.794 | 0.974 | 0.975 | [−0.037, 0.000] | [+0.004, +0.071] | 0.067 | 0.988 | 0/11 |
| GLiDE 2B | 0.900 | 1.000 | 0.765 | **0.989** | **0.986** | [−0.100, +0.050] | [+0.008, +0.089] | **0.033** | 0.912 | 0/11 |
| KnowLine 4B | 0.900 | 1.000 | 0.765 | 0.931 | 0.896 | [−0.062, 0.000] | [−0.088, −0.011] | 0.096 | 0.963 | 0/11 |
| GLiDE 0.8B | 0.838 | 1.000 | 0.618 | 0.947 | 0.951 | [−0.162, −0.012] | [−0.034, +0.055] | 0.074 | 0.963 | 0/11 |
| GLiDE 0.4B | 0.700 | 0.891 | 0.441 | 0.916 | 0.883 | [−0.325, −0.125] | [−0.152, +0.031] | 0.117 | 0.850 | 0/11 |

Fără politica în cerere, acuratețea cade la 0.45–0.68. GLiDE 2B, KnowLine și Cerno lasă atunci
o turbină CRITICAL fără apel (1 din 11). Modelele nu știu pragurile noastre (0.30, 0.70, 2 zile)
dacă nu le sunt scrise.

Ce se vede:

- Pe cazurile clare, toate modelele de 2B și 4B au 100%: aplică bine o politică scrisă.
- Avantajul lui Jeffan față de regulă înseamnă **un singur caz din 80**, scurgerea de ulei, pe
  care o trimite la email cu probabilitatea 0.56. Intervalul începe la 0.
- Pe cele 4 cazuri cu încredere mică de la ML1, Jeffan, Perplexity și KnowLine dau apel cu
  0.98–0.999, exact ca regula. Aplică politica literal, nu adaugă judecată. GLiDE 2B prinde 3
  din 4, dar greșește în schimb două cazuri unde apelul e corect.
- Fumul în nacelă: niciun model nu dă apel. Cerno trimite doar email (0.61), celelalte aleg
  `nimic` (0.41–0.997): urmează pragurile numerice și ignoră textul.
- AUC-ul mai mare pentru apel (Perplexity, GLiDE 2B) vine din probabilități gradate. La pragul
  ales pe cazurile clare, pe graniță au 0.82 și 0.79, față de 0.853 la regulă. Un AUC mai bun nu
  se transformă aici în decizii mai bune.

### Apel și email sau doar email?

Aici e diferența care contează la canal. Rânduri: eticheta, coloane: alegerea lui Jeffan, cu
politica în cerere.

| | doar email | email și apel | nimic |
|---|---:|---:|---:|
| eticheta: doar email (32) | 28 | 4 | 0 |
| eticheta: email și apel (35) | 0 | 34 | 1 |
| eticheta: nimic (13) | 0 | 0 | 13 |

- Cele 4 apeluri în plus sunt cazurile cu încredere mică de la ML1, iar apelul ratat e fumul în
  nacelă. Regula face exact aceleași greșeli.
- Jeffan sună exact când sună regula, în 79 din 80 de cazuri. Singura decizie diferită e
  scurgerea de ulei: email, cu probabilitatea 0.56.

## Decizia 3: ce turbină reparăm prima (cu timeline)

Test separat, cerut după primul raport (`decision_model/priority.py`).

- **Scenarii**: 60 de parcuri cu o singură echipă și 2–4 turbine cu defect.
- **Timeline-ul din cerere**: vântul pe fiecare din următoarele 7 zile; apoi, pentru fiecare
  turbină, ziua de defect, producția pe 7 zile de la ML2, statusul și probabilitatea de defect.
- **Criteriul**: cererea descrie în cuvinte criteriul de optimizare al planificatorului de
  reparații al agentului.
- **Eticheta corectă** nu e pusă de mână. E turbina din prima zi a planului exact
  (`schedule_repairs`, copiat în `decision_model/scheduler.py`).

Am rulat doar Jeffan, cum ai cerut, cu GLiDE 2B ca reper (rulat deja). Fiecare scenariu a fost
trimis în 3 ordini ale turbinelor.

| Cine alege | Turbina corectă | P medie pe turbina corectă | AUC | Aceeași alegere în 3 ordini | Latență |
|---|---:|---:|---:|---:|---:|
| planificatorul exact (există deja în agent) | 1.000 | – | – | 1.000 | ~0 |
| „cel mai urgent întâi” (ziua de defect, apoi producția) | **0.800** | – | 0.847 | 1.000 | ~0 |
| Jeffan 4B | 0.650 | 0.578 | 0.820 | 0.867 | 1 472 ms |
| GLiDE 2B | 0.650 | 0.504 | 0.854 | 0.883 | 567 ms |
| ordinea de azi a agentului (CRITICAL, producție, termen) | 0.367 | – | 0.515 | 1.000 | ~0 |

Interval bootstrap de 95% pentru Jeffan:
- față de ordinea de azi: [+0.10, +0.47], deci e clar mai bun;
- față de „cel mai urgent întâi”: [−0.30, 0.00], deci nu e mai bun și probabil e mai slab.

Ce se vede:

- **Ordinea de azi a agentului e aproape la întâmplare pentru „cine e primul”** (AUC 0.515).
  Pune primele turbinele CRITICAL și pe cele cu producție mare, fără să se uite la termen și la
  vânt. În graful de azi, ea decide ordinea alertelor și repartizarea echipelor, în timp ce
  zilele de reparație vin din planificatorul exact. Cele două nu se potrivesc între ele.
- Jeffan citește ceva din timeline: în cele 8 scenarii în care ambele reguli simple greșesc,
  nimerește 5. În total însă rămâne sub „cel mai urgent întâi”, iar în 13% din scenarii își
  schimbă alegerea dacă schimbi ordinea turbinelor.
- Un model nu poate depăși planificatorul exact: eticheta e chiar planul lui. Răspunsul corect
  există deja în agent, deterministic și instantaneu.

### Cum trebuie întrebat un model Jev: trei prompturi pentru Jeffan

Primul prompt îi cerea lui Jeffan să facă singur planul pe 7 zile. Un model Jev e însă un
clasificator: citește o stare și alege între opțiuni, nu face optimizare. Am încercat două
variante în care aritmetica o face codul. Ca să nu potrivesc promptul pe scenariile pe care l-am
văzut, toate trei au rulat pe un set nou de 60 de scenarii (seed 11).

- **`timeline`**: promptul inițial. Timeline-ul brut, plus criteriul planificatorului descris în
  cuvinte.
- **`features`**: codul calculează pentru fiecare turbină ziua până la care trebuie reparată,
  ziua cea mai calmă dinainte de termen și vântul din acea zi. Opțiunile arată aceste cifre.
- **`plans`**: codul construiește planurile pe care le-ar cântări un dispecer (optimul,
  „cel mai urgent întâi”, ordinea de azi, „cel mai îndepărtat întâi”) și le elimină pe cele
  identice. Fiecare opțiune e un plan complet: ce turbină se repară în ce zi, câte turbine
  salvează și câtă producție pierde. Jeffan alege planul.

| Cine alege (seed 11) | Turbina corectă | AUC | Aceeași alegere în 3 ordini | Latență |
|---|---:|---:|---:|---:|
| planificatorul exact | 1.000 | – | 1.000 | ~0 |
| **Jeffan 4B, `plans`** | **0.883** | **0.964** | **0.983** | 1 457 ms |
| „cel mai urgent întâi” | 0.833 | 0.870 | 1.000 | ~0 |
| Jeffan 4B, `timeline` | 0.617 | 0.797 | 0.917 | 1 503 ms |
| Jeffan 4B, `features` | 0.617 | 0.790 | 0.900 | 1 703 ms |
| ordinea de azi a agentului | 0.450 | 0.571 | 1.000 | ~0 |

Intervale bootstrap de 95% pentru `plans`:
- față de promptul inițial: [+0.13, +0.40], diferență reală;
- față de ordinea de azi: [+0.30, +0.58];
- față de „cel mai urgent întâi”: [−0.07, +0.18], deci nu se poate spune că e mai bun.

În 5 scenarii există un singur plan distinct, iar fără ele `plans` are 0.873.

Concluzia despre prompt: **un model Jev merge bine când codul îi pregătește opțiuni complete
și el doar alege.** Nu merge când trebuie să calculeze singur, chiar și cu cifrele ajutătoare
din `features`. Chiar și în varianta bună alege greșit planul în 12% din cazuri, deși cifrele
din opțiuni arată care plan e mai bun. Pe deciziile pe care codul le poate calcula exact,
modelul tot pierde în fața codului.

## Ce decizii sunt cele mai bune (ROC AUC, pe întrebarea da/nu)

| Model (`cu_politica`) | AUC `da` la ML2 | AUC apel la canal | AUC apel, doar graniță | acc graniță la pragul din clar (ML2 / apel) |
|---|---:|---:|---:|---|
| regula de azi | **0.958** | 0.941 | 0.853 | **0.882** / **0.853** |
| Cerno 4B | 0.953 | 0.977 | 0.907 | 0.794 / 0.765 |
| GLiDE 2B | 0.888 | **0.986** | **0.924** | 0.618 / 0.794 |
| Perplexity Flash | 0.839 | 0.975 | 0.862 | 0.647 / 0.824 |
| Jeffan 4B | 0.742 | 0.970 | 0.851 | 0.647 / 0.853 |
| KnowLine 4B | 0.748 | 0.896 | 0.737 | 0.588 / 0.794 |
| GLiDE 0.8B | 0.852 | 0.951 | 0.789 | 0.676 / 0.676 |

- **Deciziile bune ale modelelor sunt la canal.** Pe întrebarea „apel sau nu”, Jeffan,
  Perplexity și GLiDE 2B ordonează cazurile cel puțin la fel de bine ca regula.
- **La ML2 deciziile modelelor sunt proaste**, oricum le-am tăia. Cerno ordonează aproape la
  fel de bine ca regula (AUC 0.953), dar la pragul ales pe cazurile clare are 0.794 pe graniță,
  față de 0.882 la regulă.

Tabelul complet pe categorii, cu câte decizii bune din total are fiecare model, e în
`results/report_tables.md` („decizii bune pe categorii”).

## Resurse (MacBook M5, 24 GB, MPS)

| Model | Încărcare | Memorie Metal de vârf | Latență mediană per decizie | p95 |
|---|---:|---:|---:|---:|
| regula de azi | 0 | 0 | ~0 | ~0 |
| GLiDE 0.4B | 20.6 s | 1.10 GB | 45 ms | 54 ms |
| GLiDE 0.8B | 3.4 s | 2.41 GB | 242 ms | 323 ms |
| GLiDE 2B | 4.2 s | 5.38 GB | 306 ms | 403 ms |
| Jeffan 4B | 7.9 s | 8.87 GB | 815 ms | 1 040 ms |
| Perplexity Flash | 7.1 s | 9.48 GB | 873 ms | 1 096 ms |
| Cerno 4B | 7.2 s | 9.96 GB | 1 179 ms | 1 947 ms |
| KnowLine 4B | 7.2 s | 12.73 GB | 1 644 ms | 2 678 ms |

KnowLine și Cerno sunt cei mai lenți pentru că își citesc cererea de două ori (layout-ul
publicat). Toate
modelele bazate pe Qwen3.5 rulează pe MPS calea PyTorch de referință a atenției liniare: e
corectă, dar lentă, pentru că kernelurile rapide există doar pentru CUDA.

## Verificarea portării pe Mac

| Model | Verificare | Rezultat |
|---|---|---|
| Jeffan 4B | exemplul din model card | aceeași alegere, diferență maximă 0.002 |
| GLiDE 0.4B | exemplul din model card | aceeași alegere, dar încrederea e 0.69 în loc de 0.956. Am obținut același lucru pe CPU și pe MPS, deci nu e o problemă de MPS. Exemplul publicat pare să vină din altă versiune. |
| Perplexity Flash | – | nu are exemple publicate. Rulează în bf16 pe MPS, nu în fp32 ca pe calea lor de referință din afara CUDA. Nu pot verifica abaterea. |
| KnowLine 4B | – | folosește backend-ul lor transformers, nemodificat, în locul SGLang |
| Cerno 4B | cele 2 cereri din `inference/examples` (8 întrebări) față de `answers.json`, rulate de ei pe H200 | aceeași alegere la 8/8, diferență maximă 0.013. Înlocuitorul pentru kitul Decision Index și rularea pe MPS sunt corecte. |

## Recomandare

1. **Decizia 1 rămâne regulă.** Merită reparată în regulă: o turbină cu
   `days_to_failure >= 8` sau fără termen nu are o zi de defect și nu trebuie să intre în
   `overlapping_failures`. Azi, termenul lipsă devine implicit 7 și poate porni ML2 degeaba. E o
   schimbare de câteva rânduri în `node_check_failure_overlap`, plus un test.
2. **Decizia 2 rămâne regulă.** Dacă ești de acord cu eticheta mea pentru încrederea mică de la
   ML1, se adaugă tot în regulă: status NORMAL, probabilitate ≤ 0.10 și termen ≤ 2 zile duc la
   doar email. Modelele nu fac asta singure, nici cu politica scrisă.
3. **Un model nu merită integrat acum.** Câștigul maxim e un caz din 80, cu un cost de 9 GB și
   0.8 s pe decizie, iar fără politica scrisă în cerere modelele sunt mult mai slabe decât
   regula.
4. **Dacă mai târziu vine text liber** (note ale tehnicienilor, alarme cu descriere), atunci are
   sens un al doilea test, cu scenarii de text reale. Rolul modelului ar fi doar de consilier:
   poate ridica un caz la apel, nu poate coborî unul, iar regula dură rămâne deasupra lui.
   Candidați, în ordinea asta: Jeffan 4B (cel mai bun la canal, cod simplu, Apache-2.0) și
   Perplexity Flash (AUC apel 0.975, GGUF oficial verificat pe Metal).
5. **Sub 4B**: GLiDE 2B are cea mai bună calibrare și cel mai bun AUC la canal, cu 5 GB și 0.3 s
   pe decizie. Ca alegere ia însă decizii mai proaste decât Jeffan (0.900 față de 0.938) și se
   schimbă cel mai des la altă ordine a opțiunilor (0.912). GLiDE 0.4B nu e utilizabil.
6. **Decizia 3 (cine e reparat primul) rămâne la planificatorul exact.** Ordinea turbinelor din
   `node_rank_and_match_crews` ar trebui să vină din zilele de reparație ale planului: întâi
   ziua de reparație, apoi turbinele care nu mai pot fi salvate. Azi vine dintr-o sortare care
   nimerește prima turbină doar în 37% din cazuri. E o schimbare mică în graf, fără model.
7. **Dacă vrem neapărat un model Jev în agent**, rolul în care se descurcă e cel de judecător
   între opțiuni pregătite de cod, nu de calculator:
   - la decizia 3, codul face planurile (inclusiv optimul) și Jeffan alege planul (88% pe
     testul de mai sus). O verificare în cod respinge planurile care salvează mai puține
     turbine decât cel mai bun;
   - la decizia 2, Jeffan cu politica în cerere, sub regula dură (79 din 80 de decizii, la fel
     ca regula);
   - decizia 1 rămâne regulă.

   În ambele cazuri trebuie spus deschis că modelul nu aduce încă o decizie mai bună decât
   codul. Valoarea lui apare abia când în cerere intră lucruri pe care codul nu le poate
   calcula, de exemplu notele tehnicienilor sau restricții de acces. Atunci poate cântări
   planurile și după ele.

## Riscuri și limite

- **Etichetele sunt ale mele.** Pe cazurile clare coincid cu regula prin construcție. Pe cele
  de graniță sunt judecata mea, cu motivul scris; doar 10 cazuri din 160 diferă de regulă, deci
  orice model poate câștiga cel mult acolo.
- **80 de scenarii pe decizie dau intervale largi.** Un caz înseamnă 1.25 puncte de acuratețe.
- **Scenariile sunt sintetice**, construite din câmpurile pe care agentul le are, nu din
  istoricul real al turbinelor.
- **Formularea cererii contează mult**: între `fara_politica` și `cu_politica` sunt 25–35 de
  puncte. N-am optimizat formularea pentru fiecare model, ca să nu potrivesc testul pe
  scenarii.
- **Rularea pe Mac diferă de referință**: Perplexity e în bf16 în loc de fp32, la Cerno am pus
  un înlocuitor pentru două nume din kitul Decision Index și nu există kernelurile CUDA pentru
  atenția liniară. Rezultatele pot diferi puțin de cele pe CUDA.
- **Ordinea opțiunilor schimbă uneori alegerea**: la 1–9% din scenarii pentru modelele de 2B și
  4B, la 15% pentru GLiDE 0.4B. Regula nu are această problemă.

## Cum se reproduce

Din `experiments/decision_model`:

```
uv sync
uv run hf download PelaAI/KnowLine-4B-Gen5.5 --local-dir models/KnowLine-4B-Gen5.5
uv run python -I -m decision_model.evaluate run knowline-4b
uv run python -I -m decision_model.evaluate report
uv run python -I -m decision_model.golden jeffan-4b
uv run python -I -m decision_model.priority run jeffan-4b
uv run python -I -m decision_model.priority run jeffan-4b --variant plans --seed 11
uv run python -I -m decision_model.priority report
```

Numele modelelor sunt în `decision_model/adapters.py` (`MODELS`). Rezultatele se scriu în
`out/`; copiile păstrate în git sunt în `results/`.
