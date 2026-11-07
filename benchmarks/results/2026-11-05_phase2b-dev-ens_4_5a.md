# phase2b-dev-ens_4_5a

```
MDB Drums, train, pipeline=detect, detector=auto (313s): onset F at 50 ms
           KD     SD     HH     TT     CY  KD/SD/HH  all 5  F@30ms track-mean
drums   0.954  0.854  0.853  0.696  0.554     0.871  0.855   0.853      0.889
mix     0.676  0.629  0.814  0.154  0.254     0.725  0.699   0.675      0.728
sep     0.853  0.709  0.822  0.615  0.481     0.793  0.777   0.762      0.817

All 5 classes: precision, recall, missed and extra strokes, mean |timing error| of the matched ones, recall in fast passages (<= 100 ms apart on one drum):
drums  P 0.832  R 0.879  missed   464 of  3850  extra   683  timing 9.1 ms  fast-passage R 0.798
mix    P 0.705  R 0.693  missed  1182 of  3850  extra  1119  timing 11.1 ms  fast-passage R 0.209
sep    P 0.786  R 0.768  missed   892 of  3850  extra   806  timing 11.2 ms  fast-passage R 0.261

Strokes not found on their own class: what was written instead within 50 ms (rows: the recording; 'missed': nothing), and strokes written where there was none:
drums:
            KD      SD      HH      TT      CY  missed
  KD         .       4       5       .       .      23
  SD         5       .      15       .       7     146
  HH         2       9       .       .       .      81
  TT         1       6       .       .       .       .
  CY         2       4      61       .       .      93
  extra KD 19  SD 192  HH 346  TT 0  CY 5
mix:
            KD      SD      HH      TT      CY  missed
  KD         .       4       7       1       1      61
  SD        77       .      55      12      16     460
  HH        14      18       .       3      11     210
  TT         6       3       2       .       .       .
  CY        13       5      64       1       .     138
  extra KD 379  SD 157  HH 233  TT 16  CY 21
sep:
            KD      SD      HH      TT      CY  missed
  KD         .       7      21       .       .      46
  SD         5       .     221       1       9     278
  HH         6       7       .       .       2     106
  TT         2       4       1       .       .       .
  CY         1       1      67       .       .     107
  extra KD 115  SD 115  HH 210  TT 2  CY 9
```

- date: 2026-11-05 19:49
- commit: 1c91256
- uncommitted_changes: False
- classifier: 4+5a
- separation: htdemucs
- machine: Windows 11, Intel64 Family 6 Model 140 Stepping 1, GenuineIntel, Python 3.12.10
- seconds: 313
- tracks: 80sRock, BebopJazz, Britpop, CoolJazz, Disco, FunkJazz, FusionJazz, Reggae, Rock, Rockabilly, Shadows, Zeppelin
