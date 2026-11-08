### ml2

| model | varianta | acc | acc clar | acc granita | acc unde eticheta != regula | AUC | AUC medie ordini | ECE | Brier | aceeasi alegere in 3 ordini |
|---|---|---|---|---|---|---|---|---|---|---|
| cerno-4b | cu_politica | 0.838 | 0.913 | 0.735 | 0.250 | 0.953 | 0.956 | 0.127 | 0.205 | 0.938 |
| cerno-4b | fara_politica | 0.650 | 0.652 | 0.647 | 0.500 | 0.786 | 0.778 | 0.201 | 0.439 | 0.950 |
| glide-0.4b | cu_politica | 0.550 | 0.587 | 0.500 | 0.000 | 0.762 | 0.754 | 0.005 | 0.487 | 0.963 |
| glide-0.4b | fara_politica | 0.600 | 0.609 | 0.588 | 1.000 | 0.725 | 0.770 | 0.046 | 0.457 | 1.000 |
| glide-0.8b | cu_politica | 0.512 | 0.500 | 0.529 | 0.750 | 0.852 | 0.860 | 0.177 | 0.498 | 0.912 |
| glide-0.8b | fara_politica | 0.438 | 0.435 | 0.441 | 0.000 | 0.823 | 0.829 | 0.366 | 0.706 | 0.988 |
| glide-2b | cu_politica | 0.750 | 0.848 | 0.618 | 0.750 | 0.888 | 0.896 | 0.074 | 0.332 | 0.950 |
| glide-2b | fara_politica | 0.637 | 0.630 | 0.647 | 1.000 | 0.605 | 0.614 | 0.119 | 0.470 | 0.950 |
| jeffan-4b | cu_politica | 0.650 | 0.674 | 0.618 | 1.000 | 0.742 | 0.742 | 0.288 | 0.580 | 1.000 |
| jeffan-4b | fara_politica | 0.625 | 0.652 | 0.588 | 0.000 | 0.813 | 0.814 | 0.215 | 0.473 | 1.000 |
| knowline-4b | cu_politica | 0.637 | 0.674 | 0.588 | 0.750 | 0.748 | 0.765 | 0.252 | 0.553 | 0.988 |
| knowline-4b | fara_politica | 0.613 | 0.630 | 0.588 | 1.000 | 0.661 | 0.672 | 0.231 | 0.545 | 0.925 |
| pplx-flash-4b | cu_politica | 0.700 | 0.739 | 0.647 | 0.750 | 0.839 | 0.850 | 0.134 | 0.385 | 0.988 |
| pplx-flash-4b | fara_politica | 0.625 | 0.652 | 0.588 | 0.000 | 0.851 | 0.865 | 0.336 | 0.679 | 1.000 |
| regula-de-azi | cu_politica | 0.950 | 1.000 | 0.882 | 0.000 | 0.958 | 0.958 | 0.050 | 0.100 | 1.000 |
| regula-de-azi | fara_politica | 0.950 | 1.000 | 0.882 | 0.000 | 0.958 | 0.958 | 0.050 | 0.100 | 1.000 |

### channel

| model | varianta | acc | acc clar | acc granita | acc unde eticheta != regula | AUC | AUC medie ordini | ECE | Brier | aceeasi alegere in 3 ordini | incalcari regula dura | acc cu regula dura |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| cerno-4b | cu_politica | 0.900 | 1.000 | 0.765 | 0.167 | 0.985 | 0.983 | 0.083 | 0.152 | 0.988 | 0/11 | 0.900 |
| cerno-4b | fara_politica | 0.637 | 0.674 | 0.588 | 0.167 | 0.878 | 0.874 | 0.117 | 0.447 | 0.925 | 1/11 | 0.650 |
| glide-0.4b | cu_politica | 0.700 | 0.891 | 0.441 | 0.167 | 0.916 | 0.921 | 0.117 | 0.402 | 0.850 | 0/11 | 0.700 |
| glide-0.4b | fara_politica | 0.450 | 0.391 | 0.529 | 0.333 | 0.677 | 0.686 | 0.168 | 0.644 | 0.938 | 0/11 | 0.450 |
| glide-0.8b | cu_politica | 0.838 | 1.000 | 0.618 | 0.167 | 0.947 | 0.948 | 0.074 | 0.278 | 0.963 | 0/11 | 0.838 |
| glide-0.8b | fara_politica | 0.562 | 0.674 | 0.412 | 0.167 | 0.845 | 0.847 | 0.164 | 0.554 | 0.900 | 0/11 | 0.562 |
| glide-2b | cu_politica | 0.900 | 1.000 | 0.765 | 0.500 | 0.989 | 0.991 | 0.033 | 0.141 | 0.912 | 0/11 | 0.900 |
| glide-2b | fara_politica | 0.562 | 0.587 | 0.529 | 0.167 | 0.896 | 0.897 | 0.260 | 0.548 | 0.988 | 1/11 | 0.575 |
| jeffan-4b | cu_politica | 0.938 | 1.000 | 0.853 | 0.167 | 0.973 | 0.970 | 0.058 | 0.125 | 0.988 | 0/11 | 0.938 |
| jeffan-4b | fara_politica | 0.600 | 0.565 | 0.647 | 0.167 | 0.886 | 0.885 | 0.208 | 0.527 | 0.938 | 0/11 | 0.600 |
| knowline-4b | cu_politica | 0.900 | 1.000 | 0.765 | 0.000 | 0.931 | 0.943 | 0.096 | 0.196 | 0.963 | 0/11 | 0.900 |
| knowline-4b | fara_politica | 0.625 | 0.717 | 0.500 | 0.000 | 0.908 | 0.907 | 0.122 | 0.415 | 0.975 | 1/11 | 0.637 |
| pplx-flash-4b | cu_politica | 0.912 | 1.000 | 0.794 | 0.000 | 0.974 | 0.975 | 0.067 | 0.143 | 0.988 | 0/11 | 0.912 |
| pplx-flash-4b | fara_politica | 0.675 | 0.717 | 0.618 | 0.167 | 0.910 | 0.912 | 0.149 | 0.417 | 0.938 | 0/11 | 0.675 |
| regula-de-azi | cu_politica | 0.925 | 1.000 | 0.824 | 0.000 | 0.949 | 0.949 | 0.075 | 0.150 | 1.000 | 0/11 | 0.925 |
| regula-de-azi | fara_politica | 0.925 | 1.000 | 0.824 | 0.000 | 0.949 | 0.949 | 0.075 | 0.150 | 1.000 | 0/11 | 0.925 |

### intrebarea da/nu: ML2 = da, canal = apel

| model | varianta | decizie | AUC | AUC granita | prag din clar | acc granita la prag | acc granita argmax |
|---|---|---|---|---|---|---|---|
| cerno-4b | cu_politica | channel | 0.977 | 0.907 | 0.447 | 0.765 | 0.765 |
| cerno-4b | cu_politica | ml2 | 0.953 | 0.875 | 0.319 | 0.794 | 0.735 |
| cerno-4b | fara_politica | channel | 0.896 | 0.763 | 0.832 | 0.529 | 0.647 |
| cerno-4b | fara_politica | ml2 | 0.786 | 0.654 | 0.815 | 0.618 | 0.647 |
| glide-0.4b | cu_politica | channel | 0.883 | 0.734 | 0.488 | 0.588 | 0.618 |
| glide-0.4b | cu_politica | ml2 | 0.762 | 0.529 | 0.545 | 0.441 | 0.500 |
| glide-0.4b | fara_politica | channel | 0.668 | 0.595 | 0.722 | 0.529 | 0.529 |
| glide-0.4b | fara_politica | ml2 | 0.725 | 0.529 | 0.460 | 0.471 | 0.588 |
| glide-0.8b | cu_politica | channel | 0.951 | 0.789 | 0.291 | 0.676 | 0.706 |
| glide-0.8b | cu_politica | ml2 | 0.852 | 0.738 | 0.715 | 0.676 | 0.529 |
| glide-0.8b | fara_politica | channel | 0.803 | 0.723 | 0.760 | 0.559 | 0.647 |
| glide-0.8b | fara_politica | ml2 | 0.823 | 0.752 | 0.831 | 0.676 | 0.441 |
| glide-2b | cu_politica | channel | 0.986 | 0.924 | 0.482 | 0.794 | 0.794 |
| glide-2b | cu_politica | ml2 | 0.888 | 0.877 | 0.514 | 0.618 | 0.618 |
| glide-2b | fara_politica | channel | 0.870 | 0.744 | 0.915 | 0.559 | 0.706 |
| glide-2b | fara_politica | ml2 | 0.605 | 0.614 | 0.430 | 0.647 | 0.647 |
| jeffan-4b | cu_politica | channel | 0.970 | 0.851 | 0.498 | 0.853 | 0.853 |
| jeffan-4b | cu_politica | ml2 | 0.742 | 0.732 | 0.246 | 0.647 | 0.618 |
| jeffan-4b | fara_politica | channel | 0.910 | 0.785 | 0.923 | 0.559 | 0.706 |
| jeffan-4b | fara_politica | ml2 | 0.813 | 0.718 | 0.811 | 0.706 | 0.588 |
| knowline-4b | cu_politica | channel | 0.896 | 0.737 | 0.476 | 0.794 | 0.794 |
| knowline-4b | cu_politica | ml2 | 0.748 | 0.686 | 0.257 | 0.588 | 0.588 |
| knowline-4b | fara_politica | channel | 0.895 | 0.744 | 0.854 | 0.529 | 0.618 |
| knowline-4b | fara_politica | ml2 | 0.661 | 0.680 | 0.058 | 0.588 | 0.588 |
| pplx-flash-4b | cu_politica | channel | 0.975 | 0.862 | 0.499 | 0.824 | 0.824 |
| pplx-flash-4b | cu_politica | ml2 | 0.839 | 0.773 | 0.256 | 0.647 | 0.647 |
| pplx-flash-4b | fara_politica | channel | 0.902 | 0.777 | 0.842 | 0.588 | 0.706 |
| pplx-flash-4b | fara_politica | ml2 | 0.851 | 0.754 | 0.951 | 0.735 | 0.588 |
| regula-de-azi | cu_politica | channel | 0.941 | 0.853 | 0.500 | 0.853 | 0.853 |
| regula-de-azi | cu_politica | ml2 | 0.958 | 0.900 | 0.500 | 0.882 | 0.882 |
| regula-de-azi | fara_politica | channel | 0.941 | 0.853 | 0.500 | 0.853 | 0.853 |
| regula-de-azi | fara_politica | ml2 | 0.958 | 0.900 | 0.500 | 0.882 | 0.882 |

### resurse

| model | incarcare s | memorie Metal GB | RSS GB | latenta mediana ms | p95 ms |
|---|---|---|---|---|---|
| cerno-4b | 7.2 | 9.96 | 0.86 | 1179 | 1947 |
| glide-0.4b | 20.6 | 1.10 | 2.98 | 45 | 54 |
| glide-0.8b | 3.4 | 2.41 | 1.03 | 242 | 323 |
| glide-2b | 4.2 | 5.38 | 0.77 | 306 | 403 |
| jeffan-4b | 7.9 | 8.87 | 0.70 | 815 | 1040 |
| knowline-4b | 7.2 | 12.73 | 0.97 | 1644 | 2678 |
| pplx-flash-4b | 7.1 | 9.48 | 0.72 | 873 | 1096 |

### decizii bune pe categorii (cu_politica)

ml2:

| categorie | tip | cerno-4b | glide-0.4b | glide-0.8b | glide-2b | jeffan-4b | knowline-4b | pplx-flash-4b | regula-de-azi |
|---|---|---|---|---|---|---|---|---|---|
| doua_aceeasi_zi | clar | 8/10 | 10/10 | 10/10 | 10/10 | 2/10 | 2/10 | 3/10 | 10/10 |
| doua_departe | clar | 10/10 | 0/10 | 1/10 | 3/10 | 10/10 | 10/10 | 10/10 | 10/10 |
| mai_multe_departe | clar | 6/6 | 0/6 | 0/6 | 6/6 | 6/6 | 6/6 | 6/6 | 6/6 |
| mai_multe_doua_aceeasi_zi | clar | 6/8 | 8/8 | 8/8 | 8/8 | 1/8 | 1/8 | 3/8 | 8/8 |
| nicio_turbina_de_reparat | clar | 2/2 | 2/2 | 2/2 | 2/2 | 2/2 | 2/2 | 2/2 | 2/2 |
| o_singura_turbina | clar | 10/10 | 7/10 | 2/10 | 10/10 | 10/10 | 10/10 | 10/10 | 10/10 |
| alt_parc | granita | 6/6 | 1/6 | 1/6 | 3/6 | 5/6 | 5/6 | 5/6 | 6/6 |
| deja_defect | granita | 2/2 | 1/2 | 1/2 | 1/2 | 2/2 | 2/2 | 2/2 | 2/2 |
| fara_defect_prezis_8 | granita | 1/4 | 0/4 | 3/4 | 3/4 | 4/4 | 3/4 | 3/4 | 0/4 |
| fereastra_exact_1_zi | granita | 2/4 | 4/4 | 4/4 | 4/4 | 0/4 | 1/4 | 1/4 | 4/4 |
| fereastra_exact_2_zile | granita | 4/4 | 0/4 | 0/4 | 0/4 | 4/4 | 4/4 | 4/4 | 4/4 |
| incredere_mica_ml1 | granita | 3/3 | 3/3 | 3/3 | 2/3 | 0/3 | 0/3 | 1/3 | 3/3 |
| multe_turbine | granita | 2/3 | 1/3 | 1/3 | 1/3 | 2/3 | 2/3 | 2/3 | 3/3 |
| rotunjire_in_jos | granita | 1/4 | 3/4 | 3/4 | 3/4 | 1/4 | 0/4 | 0/4 | 4/4 |
| status_fara_reparatie | granita | 4/4 | 4/4 | 2/4 | 4/4 | 3/4 | 3/4 | 4/4 | 4/4 |

channel:

| categorie | tip | cerno-4b | glide-0.4b | glide-0.8b | glide-2b | jeffan-4b | knowline-4b | pplx-flash-4b | regula-de-azi |
|---|---|---|---|---|---|---|---|---|---|
| critic_aproape | clar | 8/8 | 8/8 | 8/8 | 8/8 | 8/8 | 8/8 | 8/8 | 8/8 |
| normal_defect_iminent | clar | 6/6 | 6/6 | 6/6 | 6/6 | 6/6 | 6/6 | 6/6 | 6/6 |
| normal_fara_risc | clar | 10/10 | 10/10 | 10/10 | 10/10 | 10/10 | 10/10 | 10/10 | 10/10 |
| normal_probabilitate_medie | clar | 4/4 | 1/4 | 4/4 | 4/4 | 4/4 | 4/4 | 4/4 | 4/4 |
| warning_departe | clar | 8/8 | 6/8 | 8/8 | 8/8 | 8/8 | 8/8 | 8/8 | 8/8 |
| warning_iminent | clar | 4/4 | 4/4 | 4/4 | 4/4 | 4/4 | 4/4 | 4/4 | 4/4 |
| watch_departe | clar | 6/6 | 6/6 | 6/6 | 6/6 | 6/6 | 6/6 | 6/6 | 6/6 |
| critic_semnale_contrare | granita | 3/3 | 3/3 | 3/3 | 3/3 | 3/3 | 3/3 | 3/3 | 3/3 |
| deja_defect | granita | 1/2 | 0/2 | 1/2 | 1/2 | 2/2 | 1/2 | 1/2 | 2/2 |
| incredere_mica_ml1 | granita | 2/6 | 0/6 | 0/6 | 3/6 | 2/6 | 2/6 | 2/6 | 2/6 |
| prag_030 | granita | 3/3 | 2/3 | 3/3 | 3/3 | 3/3 | 3/3 | 3/3 | 3/3 |
| prag_070 | granita | 5/5 | 3/5 | 5/5 | 5/5 | 5/5 | 5/5 | 5/5 | 5/5 |
| prag_2_zile | granita | 3/5 | 2/5 | 2/5 | 5/5 | 5/5 | 4/5 | 5/5 | 5/5 |
| probabilitate_mare_fara_termen | granita | 1/1 | 1/1 | 1/1 | 1/1 | 1/1 | 1/1 | 1/1 | 1/1 |
| status_necunoscut | granita | 3/3 | 2/3 | 3/3 | 3/3 | 3/3 | 3/3 | 3/3 | 3/3 |
| text_liber | granita | 1/2 | 1/2 | 1/2 | 0/2 | 1/2 | 0/2 | 0/2 | 0/2 |
| warning_probabilitate_mica | granita | 1/1 | 1/1 | 1/1 | 1/1 | 1/1 | 1/1 | 1/1 | 1/1 |
| watch_termen_scurt | granita | 3/3 | 0/3 | 1/3 | 1/3 | 3/3 | 3/3 | 3/3 | 3/3 |
