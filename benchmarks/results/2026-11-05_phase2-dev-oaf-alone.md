# phase2-dev-oaf-alone

```
MDB Drums, train: oaf alone: onset F at 50 ms
           KD     SD     HH     TT     CY  KD/SD/HH  all 5  F@30ms track-mean
drums   0.895  0.793  0.000  0.346  0.132     0.582  0.557   0.556      0.604
mix     0.685  0.421  0.000  0.087  0.044     0.348  0.321   0.312      0.384
sep     0.868  0.696  0.000  0.483  0.093     0.517  0.495   0.491      0.585

All 5 classes: precision, recall, missed and extra strokes, mean |timing error| of the matched ones, recall in fast passages (<= 100 ms apart on one drum):
drums  P 0.836  R 0.417  missed  2244 of  3850  extra   315  timing 4.3 ms  fast-passage R 0.61
mix    P 0.580  R 0.222  missed  2994 of  3850  extra   620  timing 7.1 ms  fast-passage R 0.16
sep    P 0.871  R 0.345  missed  2520 of  3850  extra   197  timing 6.3 ms  fast-passage R 0.244

Strokes not found on their own class: what was written instead within 50 ms (rows: the recording; 'missed': nothing), and strokes written where there was none:
drums:
            KD      SD      HH      TT      CY  missed
  KD         .       4       .       2       .      71
  SD         7       .       .       5       .     303
  HH        41     144       .      12       2    1404
  TT         .       1       .       .       .       .
  CY         5       3       .       2       .     238
  extra KD 7  SD 49  HH 0  TT 31  CY 0
mix:
            KD      SD      HH      TT      CY  missed
  KD         .      12       .       9       .     219
  SD        23       .       .      78       1     783
  HH        44     153       .      60       .    1346
  TT         1       1       .       .       .       3
  CY        12       5       .      14       .     230
  extra KD 67  SD 95  HH 0  TT 45  CY 0
sep:
            KD      SD      HH      TT      CY  missed
  KD         .       5       .       3       .     109
  SD         7       .       .       8       .     530
  HH        10      84       .      10       1    1498
  TT         .       1       .       .       .       .
  CY         7       .       .       .       .     247
  extra KD 25  SD 28  HH 0  TT 8  CY 0
```

- date: 2026-11-05 16:17
- commit: fa16547
- uncommitted_changes: False
- classifier: 4 (v2+v3)
- separation: htdemucs
- machine: Windows 11, Intel64 Family 6 Model 140 Stepping 1, GenuineIntel, Python 3.12.10
- seconds: 105
- model: oaf
- model_revision: 771fd5529062b9f6f0b58f01cc4b9819db046f4a
- evidence: None
- tracks: 80sRock, BebopJazz, Britpop, CoolJazz, Disco, FunkJazz, FusionJazz, Reggae, Rock, Rockabilly, Shadows, Zeppelin
