# Model local de decizie: shortlist (Faza 1)

Data: 2026-11-08. Sursa clasamentului: `data/index.json` din Space-ul HF
`multimodalart/jev-decision-index`, generat 2026-11-06 09:05 UTC (Decision Index 0.4.1).
Scorul Full este `scores.balanced_skill`: 60% teste private pe aceleași abilități și 40% sarcini
private din domenii noi. Jev însuși are Full 60.24.

Filtrul a fost refăcut de la zero (`decision_model/leaderboard.py`, rezultatul în
`out/leaderboard_under_9.6b.jsonl`): 155 de modele au cel mult 9.6B parametri. Valorile din sesiunea
anterioară s-au confirmat (Cerno 4B v1.2 53.88, Jeffan-4B 52.21, Perplexity Decider Flash 54.29,
GLiDE 0.4B 33.84, d3-edge 17.69), dar lista era incompletă: între timp au apărut KnowLine-4B-Gen5.5
(55.99) și StartLux 4B (54.80), iar GLiDE-9B (7.94B parametri) are 62.48, peste Jev. Licența
Perplexity Decider Flash este acum citită de pe Hub: Apache-2.0.

## Ce limitează alegerea pe acest MacBook

- Memorie: M5 cu 24 GB unificată. Metal permite cel mult 19.07 GB pentru GPU
  (`torch.mps.recommended_max_memory()`), iar acești 19 GB se împart cu restul aplicației.
- Arhitectură: aproape toate modelele bune pornesc de la Qwen3.5 (straturi hibride cu atenție
  liniară Gated DeltaNet), iar multe citesc promptul **non-cauzal** în straturile de atenție
  completă și au un cap de citire separat. Un runtime care citește cauzal (vLLM simplu, llama.cpp
  simplu, mlx-lm simplu) încarcă modelul fără eroare, dar întoarce răspunsurile altui model.
  Asta decide runtime-ul mai mult decât viteza.
- Kernelurile rapide pentru atenția liniară (`flash-linear-attention`, `causal-conv1d`) cer CUDA.
  Pe Mac, transformers folosește calea PyTorch de referință: corectă, dar mai lentă.

## Candidați

| | KnowLine-4B-Gen5.5 | Perplexity Decider Flash v1.2 | Cerno 4B v1.2 | GLiDE 2B |
|---|---|---|---|---|
| Id pe Hub | `PelaAI/KnowLine-4B-Gen5.5` | `perplexity-ai/pplx-decider-flash-v1.2` | `apertixai/cerno-4b-v1.2` | `fastino/GLiDE-2B` |
| Parametri | 4.66B (cu turnul de viziune) | 4.54B | 4.21B | 1.88B |
| Pe disc (bf16) | 9.34 GB | 9.10 GB | 8.43 GB | 3.78 GB |
| Licență (Hub) | Apache-2.0 | Apache-2.0 | Apache-2.0 | Fastino Community License |
| Full | **55.99** | 54.29 | 53.88 | 43.72 |
| Public | 66.76 | 60.06 | 65.05 | 60.64 |
| ECE (calibrare) | 0.047 | 0.052 | 0.074 | 0.066 |
| GGUF | comunitar (`mradermacher/...-GGUF`) | **oficial** Q8_0, 5.16 GB, verificat pe Apple Metal | oficial doar pentru v1.1 (Q4_0, 3.37 GB, alt model) | nu |
| MLX | comunitar, q5, 2.91 GB (`Liamariel/knowline-4b-gen5.5-mlx-q5`) | comunitar (`Jakevin/...-mlx`), neverificat | nu | nu |
| Atenție | **cauzală** | non-cauzală în straturile complete | bidirecțională pe blocuri (context, câte un bloc per întrebare) | non-cauzală în straturile complete |
| Citirea probabilităților | logits ale etichetelor A, B, ... după `Answer:`, softmax doar peste opțiunile date; temperatura 1.50 e inclusă în greutăți; promptul e citit de două ori sub 3 000 de tokeni | cap separat `[255, 2560]` citit la markerul `<\|fim_suffix\|>` al fiecărei întrebări; temperatura 1.554, apoi softmax peste opțiunile valide | logits ale literelor opțiunilor, softmax la T = 1.236; citit de două ori sub 3 000 de tokeni | cap separat cu 255 de ieșiri, citit la ultimul `(`; softmax peste opțiunile date |
| Cod de referință | SGLang (CUDA) + `knowline_layout.py`, care cere doar transformers | pachetul `pplx_decider` (transformers) | engine propriu pe transformers | pachetul `glide` (transformers) |
| Pe Mac | se portează `knowline_layout.py` + un forward în transformers; fiind cauzal, merge și cu mlx-lm simplu | codul de referință rulează în fp32 în afara CUDA: aproximativ 18 GB, la limita Metal. Trebuie un adaptor care trece modelul în bf16 și verificat pe exemplele lor | codul e scris pentru CUDA; pe MPS nu e verificat | **rulat aici** pe MPS, vezi mai jos |

Formatul cererii este același la toate patru (formatul System One `/v1/systemone`):

```json
{
  "state": {"park_id": "park-A", "turbine_id": 10, "health_status": "WARNING",
            "days_to_failure": 4.5, "fault_probability": 0.42},
  "questions": {
    "channel": {
      "type": "choice",
      "instructions": "How should the maintenance crew be alerted about this turbine?",
      "criteria": {"doar_email": "...", "email_si_apel": "...", "nimic": "..."}
    }
  }
}
```

Răspunsul este `{"answers": {"channel": {"choice": ..., "probabilities": {opțiune: p}, ...}}}`.
Probabilitățile sunt citite dintr-un singur forward, fără text generat, deci nu există parsare de
text și nici răspunsuri în afara opțiunilor. Ambele decizii se pun ca `choice`: `da`/`nu` și
`doar_email`/`email_si_apel`/`nimic` (`decision_model/requests.py`).

### Considerate și lăsate deoparte

- **GLiDE-9B** (7.94B, Full 62.48, Fastino Community License): cel mai bun model mic, dar bf16 are
  15.9 GB (descărcare peste 10 GB). Ar ocupa vreo 16 GB din cei 19 GB Metal, iar singura cuantizare
  (NVFP4) cere un GPU Blackwell. E varianta de rezervă dacă modelele de 4B nu ajung.
- **elephant-1** (9.41B, 60.26, MIT), **Cerno 9B v1.2** (8.95B, 58.98), **Adjudex-9B v2**
  (57.18), **Dexy-9B v2** (55.39), **d3-flash** (54.27): între 16.8 și 18.8 GB în bf16, la limita
  memoriei. Variantele lor comunitare MLX sau GGUF citesc promptul cauzal și dau alt model.
- **StartLux-Decision-v1.1-4B-Instant** (54.80): tehnic e cea mai bună potrivire pentru Mac (backend
  MLX propriu care aplică masca bidirecțională, MLX 8-bit și 4-bit oficiale, latență măsurată de
  autori pe un M5 Pro), dar licența e **CC BY-NC 4.0**, deci doar pentru uz necomercial. Merită luat
  doar dacă proiectul rămâne strict necomercial.
- **Jeffan-4B-2010** (52.21, Apache-2.0): cea mai bună calibrare dintre modelele de 4B (ECE 0.039)
  și cel mai simplu cod (un snippet transformers cu masca bidirecțională). E rezerva pentru Cerno.
- **Senova-4B v4** (52.79): calibrare slabă (ECE 0.138).
- **Sub 2B**: GLiDE 0.8B (36.36), GLiDE 0.4B (33.84), d3-edge 0.6B (17.69).

## Runtime: transformers pe MPS

Recomandare: **transformers pe MPS** pentru evaluare.

- Este singurul runtime în care rulează codul de referință al fiecărui candidat (mască non-cauzală
  sau pe blocuri, cap de citire separat) fără reimplementare. La evaluare vrem modelul publicat, nu
  o aproximare a lui.
- **MLX** e mai rapid pe Apple Silicon, dar mlx-lm citește cauzal. E fidel doar pentru KnowLine
  (care e cauzal) și pentru StartLux (care are backend propriu). Îl păstrez ca optimizare pentru
  modelul ales, după Faza 2.
- **llama.cpp**: `/v1/systemone` din `llama-server` implementează protocolul v1. Pentru Perplexity
  (protocolul v3) e nevoie de un runtime scris de noi, chiar dacă GGUF-ul lor oficial a fost
  verificat pe Metal. Cerno v1.2 refuză explicit llama.cpp.

## Smoke test (rulat pe acest MacBook)

Cel mai mic candidat (GLiDE 0.4B) și GLiDE 2B, ca să testez și arhitectura Qwen3.5 a modelelor de
4B. Am rulat `decision_model/smoke.py` cu torch 2.14.0 și transformers 5.17.0, offline
(`HF_HUB_OFFLINE=1`), cu 30 de decizii măsurate pentru fiecare cerere, după o cerere de încălzire.

| | GLiDE 0.4B, MPS | GLiDE 0.4B, CPU | GLiDE 2B, MPS |
|---|---:|---:|---:|
| Încărcare | 19.4 s (16.6 s sunt inițializarea aleatoare a greutăților în codul lor, evitabilă) | 19.5 s | 4.5 s |
| Memorie de vârf | 1.09 GB Metal, 2.97 GB RSS | 2.97 GB RSS | 5.37 GB Metal, 0.71 GB RSS |
| Prima decizie | 87–596 ms | 1.1–1.3 s | 1.09 s |
| Latență mediană, o decizie | 27–29 ms | 1.1–1.4 s | 178–217 ms |
| p95 | 28–30 ms | 1.1–1.4 s | 179–221 ms |

- **Da, o cerere cu opțiuni tipizate se servește complet local.** Pachetul modelului rulează în
  procesul nostru și nu face niciun apel extern după descărcare. GLiDE are și un server HTTP
  System One propriu, pe care nu l-am instalat.
- Pentru un model de 4B estimez 0.4–0.5 s per decizie și 9–10 GB pe MPS. E o extrapolare din 2B,
  nu o măsurătoare. Pentru noi e suficient: decizia se ia o dată pe zi pentru fiecare turbină.
- **Observație, nu evaluare** (două cereri): pe ambele cereri, ambele modele GLiDE au contrazis
  regula de azi. La ML2, turbinele 10 și 11 au zilele de defect 1 și 2, deci fereastra de o zi se
  suprapune și regula spune `da`; modelele au răspuns `nu` cu 0.79 și 0.82. La canal, pentru o
  turbină WARNING cu 4.5 zile și probabilitatea 0.42, regula spune `doar_email`; modelele au
  răspuns `email_si_apel` cu 0.92 și 0.87. Cererea nu le spune pragurile noastre, așa că ele judecă
  după propriul simț. În Faza 2 trebuie decis dacă politica intră în `instructions`.

## Varianta fără model (regulile de azi)

E o alternativă reală, nu doar un baseline:

- **Decizia 1** este aritmetică pură: există două zile de defect la cel mult o zi distanță?
  Modelul nu are nicio informație în plus față de regulă, doar o poate greși, iar comparația de
  numere e punctul slab al modelelor mici (aria Knowledge are cele mai mici scoruri). Mă aștept ca
  regula să rămână regulă.
- **Decizia 2** este singura unde un model poate aduce ceva: cazuri de graniță (0.69 față de 0.71,
  WATCH cu termen scurt, încredere mică de la ML1) și, mai târziu, text liber, de exemplu
  `suspected_failure`. Regula dură (o alertă critică primește mereu apel) rămâne oricum deasupra
  modelului.
- Regulile costă 0 ms și 0 GB, sunt deterministe și se testează unitar. Un model trebuie să le bată
  pe cazurile de graniță etichetate, nu doar să le egaleze pe cele clare.

## Recomandare pentru Faza 2

Testăm **KnowLine-4B-Gen5.5** și **Perplexity Decider Flash v1.2**, cu **GLiDE 2B** ca model de
control sub 4B, toate față de regulile de azi.

- Sunt cele mai bune două modele Apache-2.0 de 4B și reprezintă cele două arhitecturi: citire cauzală
  a etichetelor (KnowLine, cel mai ușor de portat, merge și pe MLX) și citire non-cauzală cu cap
  separat (Perplexity, distilat din modelele de 27B, cu GGUF oficial verificat pe Metal).
- Cerno 4B v1.2 e al treilea, opțional: scor apropiat, dar calibrarea e cea mai slabă dintre cele
  patru și codul nu e verificat pe MPS.
- **Ceva sub 4B are sens doar ca martor.** Latența și memoria nu ne constrâng, iar la 2B scorul Full
  scade cu 10–12 puncte. Dacă GLiDE 2B egalează modelele de 4B pe deciziile noastre, înseamnă că
  deciziile sunt practic reguli, ceea ce întărește varianta fără model. 0.4B și d3-edge nu merită
  testate mai departe.

## Descărcări

- Făcute: GLiDE 0.4B (0.81 GB) și GLiDE 2B (3.78 GB), în `models/` (ignorat de git).
- Pentru recomandarea de mai sus: KnowLine 9.34 GB și Perplexity 9.10 GB, fiecare sub 10 GB, în
  total 18.4 GB (cu Cerno, 26.9 GB). Spațiu liber pe disc: 278 GB.
- **Peste 10 GB**: doar GLiDE-9B (15.9 GB), dacă îl vrei ca rezervă. Nu îl descarc fără
  confirmarea ta.

## Anexă: toate modelele verificate pe Hub

Parametrii și mărimea vin din API-ul Hub (`safetensors.total` și suma fișierelor), iar licența din
model card. Coloanele GGUF și MLX spun doar dacă o căutare după nume pe Hub găsește o variantă.
Cele mai multe variante sunt comunitare și citesc cauzal, deci nu reproduc modelul publicat, cu
excepțiile notate mai sus (GGUF-ul oficial Perplexity, MLX-ul oficial StartLux).

| Id pe Hub | Parametri | Pe disc | Licență | Full | GGUF | MLX |
|---|---:|---:|---|---:|---|---|
| `fastino/GLiDE-9B` | 7.94B | 15.90 GB | fastino-community | 62.48 | nu | nu |
| `baselabs/elephant-1` | 9.41B | 18.84 GB | MIT | 60.26 | comunitar | comunitar 8-bit |
| `apertixai/cerno-9b-v1.2` | 8.95B | 17.93 GB | Apache-2.0 | 58.98 | comunitar | nu |
| `newsbang/adjudex-9b-v2` | 8.39B | 16.81 GB | Apache-2.0 | 57.18 | nu | nu |
| `PelaAI/KnowLine-4B-Gen5.5` | 4.66B | 9.34 GB | Apache-2.0 | 55.99 | comunitar | comunitar q5 |
| `Patrick-18/Dexy-Decision-9B-V2` | 8.39B | 16.81 GB | Apache-2.0 | 55.39 | nu | nu |
| `startlux-models/StartLux-Decision-v1.1-4B-Instant` | 4.66B | 9.34 GB | CC BY-NC 4.0 | 54.80 | oficial | oficial 8/4-bit |
| `perplexity-ai/pplx-decider-flash-v1.2` | 4.54B | 9.10 GB | Apache-2.0 | 54.29 | oficial Q8_0 | comunitar |
| `vllm-sr/d3-flash` | 8.39B | 16.82 GB | Apache-2.0 | 54.27 | comunitar | comunitar |
| `apertixai/cerno-4b-v1.2` | 4.21B | 8.43 GB | Apache-2.0 | 53.88 | oficial doar v1.1 | nu |
| `OmniJev/OneJev1.6-9B` | 9.41B | 18.84 GB | Apache-2.0 | 53.05 | comunitar | doar în merge-uri |
| `WangSenQWQ/Senova-4B-v4` | 4.54B | 9.10 GB | Apache-2.0 | 52.79 | comunitar | nu |
| `tattrongvu/Jeffan-4B-2010` | 4.21B | 8.43 GB | Apache-2.0 | 52.21 | comunitar | nu |
| `fastino/GLiDE-2B` | 1.88B | 3.78 GB | fastino-community | 43.72 | nu | nu |
| `startlux-models/StartLux-Decision-v1.1-2B-Instant` | 2.27B | 4.57 GB | CC BY-NC 4.0 | 40.11 | oficial | oficial 8/4-bit |
| `fastino/GLiDE-0.8B` | 0.75B | 1.53 GB | fastino-community | 36.36 | nu | nu |
| `fastino/GLiDE-0.4B` | 0.39B | 0.81 GB | fastino-community | 33.84 | nu | nu |
| `vllm-sr/d3-edge` | 0.59B | 1.22 GB | Apache-2.0 | 17.69 | comunitar | comunitar |

Licența Fastino Community: utilizare gratuită, inclusiv modificare și redistribuire. O firmă cu venit
anual peste 10 milioane USD are nevoie de un acord separat pentru producție comercială, iar orice uz
comercial trebuie să afișeze „Built with Fastino GLiDE”. Evaluarea, testarea și cercetarea nu
contează ca producție.
